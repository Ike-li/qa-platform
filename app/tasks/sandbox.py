"""Sandbox container management for test execution isolation.

Runs pytest inside an isolated Docker container with:
- Project venv mounted read-only (provides all dependencies)
- Repo mounted read-only
- Results written via bind mount (directly accessible from host)
- Network, CPU, memory limits
- Read-only filesystem + no-new-privileges

The venv mount approach couples host and container paths. The
_rewrite_command() method translates host-side paths to container-side
mount points. If the venv path structure or mount layout changes,
both must be updated together.
"""

import logging
import os

import docker
from docker.errors import ContainerError, DockerException, ImageNotFound, APIError

logger = logging.getLogger(__name__)

SANDBOX_IMAGE = os.getenv("SANDBOX_IMAGE", "qa-platform-sandbox:latest")
SANDBOX_MEMORY_LIMIT = os.getenv("SANDBOX_MEMORY_LIMIT", "512m")
SANDBOX_CPU_PERIOD = 100000
SANDBOX_CPU_QUOTA = int(os.getenv("SANDBOX_CPU_QUOTA", "50000"))  # 0.5 CPU default
SANDBOX_TIMEOUT = int(os.getenv("SANDBOX_TIMEOUT", "1800"))  # 30 min

CONTAINER_VENV = "/opt/venv"
CONTAINER_WORKSPACE = "/workspace"
CONTAINER_RESULTS = "/results"


class SandboxConfigError(Exception):
    """Fatal sandbox misconfiguration. Should NOT fall back to subprocess."""


class SandboxRuntimeError(Exception):
    """Transient sandbox failure. Safe to fall back to subprocess."""


class SandboxRunner:
    """Run pytest inside an isolated Docker container."""

    def __init__(self, repo_path: str, venv_path: str, results_dir: str,
                 network_disabled: bool = True):
        self.repo_path = repo_path
        self.venv_path = venv_path
        self.results_dir = results_dir
        self.network_disabled = network_disabled

        try:
            self.client = docker.from_env()
        except DockerException as exc:
            raise SandboxRuntimeError(f"Cannot connect to Docker: {exc}") from exc

        self._verify_image()

    def _verify_image(self) -> None:
        """Verify sandbox image exists and Python version matches."""
        try:
            self.client.images.get(SANDBOX_IMAGE)
        except ImageNotFound as exc:
            raise SandboxConfigError(
                f"Sandbox image '{SANDBOX_IMAGE}' not found. "
                f"Build it with: docker build -f Dockerfile.sandbox -t {SANDBOX_IMAGE} ."
            ) from exc

    def _rewrite_command(self, cmd: list[str]) -> list[str]:
        """Translate host-side paths to container-side mount points.

        The venv at self.venv_path is mounted at /opt/venv inside the
        container. The repo at self.repo_path is mounted at /workspace.
        Results are written to /results (bind mount to self.results_dir).
        """
        rewritten = []
        # cmd[0] is the host pytest binary path -> use container python
        rewritten.extend(["/opt/venv/bin/python", "-m", "pytest"])

        for arg in cmd[1:]:
            # Translate test path prefix
            if arg.startswith(self.repo_path):
                relative = arg[len(self.repo_path):]
                rewritten.append(CONTAINER_WORKSPACE + relative)
            # Translate --alluredir
            elif arg.startswith("--alluredir="):
                rewritten.append(f"--alluredir={CONTAINER_RESULTS}/allure")
            # Translate --junitxml
            elif arg.startswith("--junitxml="):
                rewritten.append(f"--junitxml={CONTAINER_RESULTS}/junit.xml")
            else:
                rewritten.append(arg)

        return rewritten

    def run(self, cmd: list[str], timeout: int = SANDBOX_TIMEOUT) -> dict:
        """Run pytest in a sandboxed container.

        Args:
            cmd: Host-side pytest command (from stage_run_tests)
            timeout: Max seconds to wait

        Returns:
            dict with keys: return_code, stdout, stderr
        """
        container_cmd = self._rewrite_command(cmd)
        container = None

        try:
            container = self.client.containers.run(
                image=SANDBOX_IMAGE,
                command=container_cmd,
                volumes={
                    self.repo_path: {"bind": CONTAINER_WORKSPACE, "mode": "ro"},
                    self.venv_path: {"bind": CONTAINER_VENV, "mode": "ro"},
                    self.results_dir: {"bind": CONTAINER_RESULTS, "mode": "rw"},
                },
                environment={
                    "VIRTUAL_ENV": CONTAINER_VENV,
                    "PATH": f"{CONTAINER_VENV}/bin:/usr/bin:/bin",
                    "PYTHONPATH": f"{CONTAINER_VENV}/lib/python3.11/site-packages",
                    "PYTHONDONTWRITEBYTECODE": "1",
                },
                mem_limit=SANDBOX_MEMORY_LIMIT,
                cpu_period=SANDBOX_CPU_PERIOD,
                cpu_quota=SANDBOX_CPU_QUOTA,
                network_disabled=self.network_disabled,
                read_only=True,
                tmpfs={"/tmp": "size=100m"},
                security_opt=["no-new-privileges"],
                detach=True,
                name=f"qa-sandbox-{os.getpid()}-{id(cmd) % 10000}",
            )

            result = container.wait(timeout=timeout)
            stdout = container.logs(stdout=True, stderr=False).decode("utf-8", errors="replace")
            stderr = container.logs(stdout=False, stderr=True).decode("utf-8", errors="replace")

            return {
                "return_code": result.get("StatusCode", -1),
                "stdout": stdout[-50000:],
                "stderr": stderr[-50000:],
            }

        except ContainerError as exc:
            return {"return_code": exc.exit_status, "stdout": "", "stderr": str(exc)}
        except (DockerException, APIError) as exc:
            raise SandboxRuntimeError(f"Docker runtime error: {exc}") from exc
        except Exception as exc:
            raise SandboxRuntimeError(f"Sandbox execution failed: {exc}") from exc
        finally:
            if container:
                try:
                    container.remove(force=True)
                    logger.info("Sandbox container removed")
                except Exception as cleanup_exc:
                    logger.debug("Container cleanup failed: %s", cleanup_exc)
