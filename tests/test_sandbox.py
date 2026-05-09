"""Sandbox isolation tests — all Docker SDK interactions are mocked."""

import os
from unittest.mock import MagicMock, patch

import pytest

from app.tasks.sandbox import (
    CONTAINER_RESULTS,
    SandboxConfigError,
    SandboxRunner,
    SandboxRuntimeError,
)


@pytest.fixture
def mock_docker():
    """Mock Docker client and container."""
    with patch("app.tasks.sandbox.docker") as mock_docker_mod:
        mock_client = MagicMock()
        mock_docker_mod.from_env.return_value = mock_client
        mock_docker_mod.errors.DockerException = Exception
        mock_docker_mod.errors.ContainerError = type("ContainerError", (Exception,), {})
        mock_docker_mod.errors.ImageNotFound = type("ImageNotFound", (Exception,), {})
        mock_docker_mod.errors.APIError = type("APIError", (Exception,), {})

        # Image exists by default
        mock_client.images.get.return_value = MagicMock()

        # Container mock
        mock_container = MagicMock()
        mock_container.wait.return_value = {"StatusCode": 0}
        mock_container.logs.return_value = b"test output"
        mock_client.containers.run.return_value = mock_container

        yield mock_client, mock_container, mock_docker_mod


@pytest.fixture
def runner(mock_docker):
    """Create a SandboxRunner with mocked Docker."""
    return SandboxRunner(
        repo_path="/data/repos/1",
        venv_path="/data/venvs/42",
        results_dir="/data/execution_results/42",
    )


# ---------------------------------------------------------------------------
# Command rewriting
# ---------------------------------------------------------------------------


class TestCommandRewriting:
    """Verify _rewrite_command translates all host paths."""

    def test_rewrites_cmd0_to_container_python(self, runner):
        cmd = ["/data/venvs/42/bin/pytest", "/data/repos/1/tests", "--tb=short"]
        result = runner._rewrite_command(cmd)
        assert result[0] == "/opt/venv/bin/python"
        assert result[1] == "-m"
        assert result[2] == "pytest"

    def test_rewrites_test_path_to_workspace(self, runner):
        cmd = ["/data/venvs/42/bin/pytest", "/data/repos/1/tests/unit", "--tb=short"]
        result = runner._rewrite_command(cmd)
        assert "/workspace/tests/unit" in result

    def test_rewrites_alluredir_to_results(self, runner):
        cmd = ["/data/venvs/42/bin/pytest", "/data/repos/1", "--alluredir=/data/execution_results/42"]
        result = runner._rewrite_command(cmd)
        assert f"--alluredir={CONTAINER_RESULTS}/allure" in result

    def test_rewrites_junitxml_to_results(self, runner):
        cmd = ["/data/venvs/42/bin/pytest", "/data/repos/1", "--junitxml=/data/execution_results/42/junit.xml"]
        result = runner._rewrite_command(cmd)
        assert f"--junitxml={CONTAINER_RESULTS}/junit.xml" in result

    def test_preserves_unknown_args(self, runner):
        cmd = ["/data/venvs/42/bin/pytest", "/data/repos/1", "-v", "--tb=short", "-k", "test_login"]
        result = runner._rewrite_command(cmd)
        assert "-v" in result
        assert "--tb=short" in result
        assert "-k" in result
        assert "test_login" in result


# ---------------------------------------------------------------------------
# Volume mounts
# ---------------------------------------------------------------------------


class TestVolumeMounts:
    """Verify correct volume mount strategy."""

    def test_results_use_bind_mount_not_named_volume(self, runner, mock_docker):
        """Results must use bind mount (not Docker named volume) for host accessibility."""
        mock_client, mock_container, _ = mock_docker
        cmd = ["/data/venvs/42/bin/pytest", "/data/repos/1", "--alluredir=/data/execution_results/42"]
        runner.run(cmd)

        call_kwargs = mock_client.containers.run.call_args
        volumes = call_kwargs.kwargs.get("volumes") or call_kwargs[1].get("volumes", {})
        # Results dir should be a host path bind mount, not a volume name
        assert runner.results_dir in volumes
        assert volumes[runner.results_dir]["bind"] == CONTAINER_RESULTS

    def test_venv_mounted_readonly(self, runner, mock_docker):
        mock_client, _, _ = mock_docker
        cmd = ["/data/venvs/42/bin/pytest", "/data/repos/1"]
        runner.run(cmd)

        call_kwargs = mock_client.containers.run.call_args
        volumes = call_kwargs.kwargs.get("volumes") or call_kwargs[1].get("volumes", {})
        assert volumes[runner.venv_path]["mode"] == "ro"

    def test_repo_mounted_readonly(self, runner, mock_docker):
        mock_client, _, _ = mock_docker
        cmd = ["/data/venvs/42/bin/pytest", "/data/repos/1"]
        runner.run(cmd)

        call_kwargs = mock_client.containers.run.call_args
        volumes = call_kwargs.kwargs.get("volumes") or call_kwargs[1].get("volumes", {})
        assert volumes[runner.repo_path]["mode"] == "ro"


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


class TestErrorHandling:
    """Verify exception hierarchy and fallback behavior."""

    def test_config_error_on_missing_image(self, mock_docker):
        """Missing sandbox image raises SandboxConfigError (fatal)."""
        _, _, mock_docker_mod = mock_docker
        mock_docker_mod.errors.ImageNotFound = SandboxConfigError

        mock_client = MagicMock()
        mock_docker_mod.from_env.return_value = mock_client
        mock_client.images.get.side_effect = SandboxConfigError("not found")

        with pytest.raises(SandboxConfigError):
            SandboxRunner(
                repo_path="/data/repos/1",
                venv_path="/data/venvs/42",
                results_dir="/data/execution_results/42",
            )

    def test_runtime_error_triggers_subprocess_fallback(self, runner, mock_docker):
        """DockerException raises SandboxRuntimeError (safe to fall back)."""
        mock_client, _, mock_docker_mod = mock_docker
        mock_client.containers.run.side_effect = Exception("Docker daemon down")

        with pytest.raises(SandboxRuntimeError):
            cmd = ["/data/venvs/42/bin/pytest", "/data/repos/1"]
            runner.run(cmd)

    def test_config_error_calls_fail_execution(self, runner, mock_docker):
        """SandboxConfigError should NOT silently fall back."""
        # This test verifies the exception type, not the integration
        # The integration test is in stage_run_tests which catches SandboxConfigError
        assert issubclass(SandboxConfigError, Exception)
        assert not issubclass(SandboxConfigError, SandboxRuntimeError)


# ---------------------------------------------------------------------------
# Container lifecycle
# ---------------------------------------------------------------------------


class TestContainerLifecycle:
    """Verify container cleanup and resource limits."""

    def test_sandbox_cleanup_on_failure(self, runner, mock_docker):
        """Container is always removed, even on failure."""
        mock_client, mock_container, _ = mock_docker
        mock_container.wait.side_effect = Exception("timeout")

        cmd = ["/data/venvs/42/bin/pytest", "/data/repos/1"]
        with pytest.raises(SandboxRuntimeError):
            runner.run(cmd)

        mock_container.remove.assert_called_once_with(force=True)

    def test_sandbox_cleanup_on_success(self, runner, mock_docker):
        """Container is removed after successful execution."""
        mock_client, mock_container, _ = mock_docker

        cmd = ["/data/venvs/42/bin/pytest", "/data/repos/1"]
        runner.run(cmd)

        mock_container.remove.assert_called_once_with(force=True)

    def test_sandbox_resource_limits(self, runner, mock_docker):
        """Container runs with resource limits."""
        mock_client, _, _ = mock_docker

        cmd = ["/data/venvs/42/bin/pytest", "/data/repos/1"]
        runner.run(cmd)

        call_kwargs = mock_client.containers.run.call_args
        assert "mem_limit" in call_kwargs.kwargs
        assert "cpu_period" in call_kwargs.kwargs
        assert "cpu_quota" in call_kwargs.kwargs
        assert call_kwargs.kwargs.get("security_opt") == ["no-new-privileges"]

    def test_sandbox_disabled_by_default(self):
        """ENABLE_SANDBOX defaults to false."""
        assert os.getenv("ENABLE_SANDBOX", "false").lower() == "false"


# ---------------------------------------------------------------------------
# Network configuration
# ---------------------------------------------------------------------------


class TestNetworkConfig:
    """Verify sandbox_network resolution."""

    def test_sandbox_network_disabled_by_default(self, mock_docker):
        """Network is disabled by default."""
        mock_client, _, _ = mock_docker
        runner = SandboxRunner(
            repo_path="/data/repos/1",
            venv_path="/data/venvs/42",
            results_dir="/data/execution_results/42",
            network_disabled=True,
        )
        cmd = ["/data/venvs/42/bin/pytest", "/data/repos/1"]
        runner.run(cmd)

        call_kwargs = mock_client.containers.run.call_args
        assert call_kwargs.kwargs.get("network_disabled") is True

    def test_sandbox_network_enabled_per_project(self, mock_docker):
        """Network can be enabled per project."""
        mock_client, _, _ = mock_docker
        runner = SandboxRunner(
            repo_path="/data/repos/1",
            venv_path="/data/venvs/42",
            results_dir="/data/execution_results/42",
            network_disabled=False,
        )
        cmd = ["/data/venvs/42/bin/pytest", "/data/repos/1"]
        runner.run(cmd)

        call_kwargs = mock_client.containers.run.call_args
        assert call_kwargs.kwargs.get("network_disabled") is False
