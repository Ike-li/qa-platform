"""Celery tasks implementing the three-stage checkpointed chained pipeline.

Pipeline: stage_git_sync -> stage_run_tests -> stage_generate_report

Each stage writes status before AND after execution.
On failure the pipeline stops and no further stages execute.
Concurrency is controlled via a Redis distributed lock.
"""

import logging
import os
import shlex
import shutil
import subprocess
from datetime import datetime, timezone

from celery import chain
from celery.signals import worker_process_init
from flask import current_app
from redis import Redis

from app.extensions import celery, db
from app.models.allure_report import AllureReport
from app.models.execution import Execution, ExecutionStatus
from app.models.project import Project
from app.models.test_suite import TestSuite

logger = logging.getLogger(__name__)

_ALLOWED_PYTEST_FLAGS = {"-k", "--timeout", "-x", "--tb", "-v", "-q", "--co", "--maxfail", "-m", "-s"}


class PipelineAbort(Exception):
    """Raised inside a pipeline stage to halt the chain immediately."""


# ------------------------------------------------------------------
# Concurrency guard
# ------------------------------------------------------------------

REDIS_URL = os.getenv("CELERY_BROKER_URL", "redis://redis:6379/0")
_redis = Redis.from_url(REDIS_URL)

# Default max parallel executions; overridden by SystemConfig if present
DEFAULT_MAX_EXEC_SLOTS = 3
EXEC_SLOT_SET = "exec_slots"
EXEC_SLOT_TTL_PREFIX = "exec_slot_ttl:"
EXEC_SLOT_TTL = 7200  # 2 hours — max reasonable execution time


def _get_max_slots() -> int:
    """Read max parallel execution slots from SystemConfig or use default."""
    try:
        from app.models.system_config import SystemConfig

        val = SystemConfig.get("max_exec_slots")
        if val is not None:
            return int(val)
    except Exception:
        pass
    return DEFAULT_MAX_EXEC_SLOTS


def _acquire_exec_slot(execution_id: int) -> bool:
    """Acquire a slot atomically using WATCH/MULTI/EXEC on the Redis Set.

    The TTL key auto-expires if the worker crashes.
    """
    try:
        pipe = _redis.pipeline()
        pipe.watch(EXEC_SLOT_SET)
        active = _redis.scard(EXEC_SLOT_SET)
        if active >= _get_max_slots():
            pipe.reset()
            return False
        pipe.multi()
        pipe.sadd(EXEC_SLOT_SET, str(execution_id))
        pipe.set(f"{EXEC_SLOT_TTL_PREFIX}{execution_id}", "1", ex=EXEC_SLOT_TTL)
        pipe.execute()
        logger.info("Slot acquired for execution %d (active: %d)", execution_id, active + 1)
        return True
    except Exception as exc:
        logger.error("Redis slot acquire failed for execution %d: %s", execution_id, exc)
        return False


def _release_exec_slot(execution_id: int) -> None:
    """Release the slot for a specific execution."""
    try:
        _redis.srem(EXEC_SLOT_SET, str(execution_id))
        _redis.delete(f"{EXEC_SLOT_TTL_PREFIX}{execution_id}")
        logger.info("Slot released for execution %d", execution_id)
    except Exception as exc:
        logger.warning("Failed to release slot for execution %d: %s", execution_id, exc)


def _recover_stale_slots() -> None:
    """Remove set members whose TTL key has expired (crashed workers).

    Called at worker startup via worker_process_init signal.
    """
    try:
        members = _redis.smembers(EXEC_SLOT_SET)
        recovered = 0
        for member in members:
            eid = member.decode() if isinstance(member, bytes) else member
            if not _redis.exists(f"{EXEC_SLOT_TTL_PREFIX}{eid}"):
                _redis.srem(EXEC_SLOT_SET, member)
                recovered += 1
        if recovered:
            logger.info("Recovered %d stale execution slots on startup", recovered)
    except Exception as exc:
        logger.warning("Failed to recover stale slots: %s", exc)


@worker_process_init.connect
def _on_worker_init(**kwargs):
    """Clean up orphaned slots when a Celery worker process starts."""
    _recover_stale_slots()


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _set_status(execution: Execution, status: ExecutionStatus) -> None:
    """Update execution status and commit."""
    execution.status = status
    db.session.commit()
    logger.info("Execution %d -> %s", execution.id, status.value)


def _terminate_execution(execution: Execution, status: ExecutionStatus, error: str, cleanup_venv: str | None = None) -> None:
    """Terminate an execution with the given status and abort the pipeline."""
    execution.status = status
    execution.error_detail = error
    execution.finished_at = datetime.now(timezone.utc)
    execution.update_duration()
    db.session.commit()
    logger.error("Execution %d %s: %s", execution.id, status.value.upper(), error[:500])
    _release_exec_slot(execution.id)
    if cleanup_venv:
        _cleanup_venv(cleanup_venv)
    raise PipelineAbort(error)


def _fail_execution(execution: Execution, error: str, cleanup_venv: str | None = None) -> None:
    """Mark execution as failed and abort the pipeline."""
    _terminate_execution(execution, ExecutionStatus.FAILED, error, cleanup_venv)


def _timeout_execution(execution: Execution, cleanup_venv: str | None = None) -> None:
    """Mark execution as timed out and abort the pipeline."""
    _terminate_execution(execution, ExecutionStatus.TIMEOUT, "Execution timed out.", cleanup_venv)


def _cleanup_venv(venv_path: str) -> None:
    """Remove a virtualenv directory, ignoring errors."""
    try:
        if os.path.isdir(venv_path):
            shutil.rmtree(venv_path)
            logger.info("Cleaned up venv: %s", venv_path)
    except OSError as exc:
        logger.warning("Failed to clean up venv %s: %s", venv_path, exc)


from app.utils.git import build_clone_url as _build_clone_url


def _venv_path(execution_id: int) -> str:
    return os.path.join(current_app.config["EXECUTION_VENV_DIR"], str(execution_id))


def _results_dir(execution_id: int) -> str:
    return os.path.join(current_app.config["EXECUTION_RESULTS_DIR"], str(execution_id))


# ------------------------------------------------------------------
# Pipeline entry point
# ------------------------------------------------------------------

@celery.task(name="app.tasks.execution_tasks.run_execution_pipeline", bind=True)
def run_execution_pipeline(self, execution_id: int):
    """Dispatch the three-stage chained pipeline.

    Uses Celery's ``chain()`` so each stage receives the previous
    stage's return value (all return execution_id).
    """
    # Acquire a concurrency slot (blocking)
    try:
        if not _acquire_exec_slot(execution_id):
            execution = db.session.get(Execution, execution_id)
            if execution:
                _fail_execution(execution, "No execution slots available. Try again later.")
    except PipelineAbort:
        logger.warning("Pipeline aborted for execution %d (no slots)", execution_id)
        return execution_id

    pipeline = chain(
        stage_git_sync.s(execution_id),
        stage_run_tests.s(),
        stage_generate_report.s(),
    )
    pipeline.apply_async()
    return execution_id


# ------------------------------------------------------------------
# Stage 1: Git Sync
# ------------------------------------------------------------------

@celery.task(
    name="app.tasks.execution_tasks.stage_git_sync",
    bind=True,
    acks_late=True,
    max_retries=0,
)
def stage_git_sync(self, execution_id: int) -> int:
    """Clone/pull repo, set up venv, install deps.

    Status transitions: PENDING -> RUNNING -> CLONED (or FAILED).
    """
    execution = db.session.get(Execution, execution_id)
    if execution is None:
        logger.error("Execution %d not found", execution_id)
        return execution_id

    project = db.session.get(Project, execution.project_id)
    if project is None:
        _fail_execution(execution, "Project not found.")

    # Mark running
    execution.started_at = datetime.now(timezone.utc)
    _set_status(execution, ExecutionStatus.RUNNING)

    repo_path = project.repo_path

    try:
        # --- Git clone or pull ---
        credential = project.get_credential()
        clone_url = _build_clone_url(project.git_url, credential)

        if os.path.isdir(os.path.join(repo_path, ".git")):
            # Existing repo: update remote URL and pull
            subprocess.run(
                ["git", "remote", "set-url", "origin", clone_url],
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=30,
                check=True,
            )
            subprocess.run(
                ["git", "pull", "--ff-only", "origin", project.git_branch],
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=300,
                check=True,
            )
        else:
            os.makedirs(os.path.dirname(repo_path), exist_ok=True)
            subprocess.run(
                [
                    "git", "clone", "--depth", "1",
                    "--branch", project.git_branch,
                    clone_url, repo_path,
                ],
                cwd=os.path.dirname(repo_path),
                capture_output=True,
                text=True,
                timeout=300,
                check=True,
            )

        # Capture commit SHA
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=15,
            check=True,
        )
        execution.git_commit_sha = result.stdout.strip()
        db.session.commit()

    except subprocess.TimeoutExpired as exc:
        _fail_execution(execution, f"Git operation timed out: {exc}")
    except subprocess.CalledProcessError as exc:
        _fail_execution(execution, f"Git failed (rc={exc.returncode}): {(exc.stderr or '')[:500]}")
    except Exception as exc:
        _fail_execution(execution, f"Unexpected git error: {exc}")

    # --- Create virtualenv ---
    venv_path = _venv_path(execution_id)
    try:
        # Remove stale venv
        _cleanup_venv(venv_path)

        subprocess.run(
            ["python", "-m", "venv", venv_path],
            capture_output=True,
            text=True,
            timeout=120,
            check=True,
        )

        # Install deps if requirements.txt exists
        requirements = os.path.join(repo_path, "requirements.txt")
        if os.path.isfile(requirements):
            pip_bin = os.path.join(venv_path, "bin", "pip")
            subprocess.run(
                [pip_bin, "install", "--upgrade", "pip"],
                capture_output=True,
                text=True,
                timeout=60,
                check=True,
            )
            subprocess.run(
                [pip_bin, "install", "-r", requirements],
                capture_output=True,
                text=True,
                timeout=600,
                check=True,
            )

    except subprocess.TimeoutExpired as exc:
        _fail_execution(execution, f"Venv setup timed out: {exc}", cleanup_venv=venv_path)
    except subprocess.CalledProcessError as exc:
        _fail_execution(
            execution,
            f"Venv setup failed (rc={exc.returncode}): {(exc.stderr or '')[:500]}",
            cleanup_venv=venv_path,
        )
    except Exception as exc:
        _fail_execution(execution, f"Venv error: {exc}", cleanup_venv=venv_path)

    _set_status(execution, ExecutionStatus.CLONED)
    _release_exec_slot(execution_id)  # release while waiting for next stage (it will re-acquire)
    return execution_id


# ------------------------------------------------------------------
# Stage 2: Run Tests
# ------------------------------------------------------------------

@celery.task(
    name="app.tasks.execution_tasks.stage_run_tests",
    bind=True,
    acks_late=True,
    max_retries=0,
)
def stage_run_tests(self, execution_id: int) -> int:
    """Run pytest inside the venv with allure and JUnit output.

    Status transitions: CLONED -> RUNNING -> EXECUTED (or FAILED).
    """
    # Guard: abort if execution is already in a terminal state
    execution = db.session.get(Execution, execution_id)
    if execution and execution.is_terminal:
        logger.warning("Execution %d already in terminal state %s, skipping stage_run_tests",
                       execution_id, execution.status.value)
        return execution_id

    # Re-acquire concurrency slot
    try:
        if not _acquire_exec_slot(execution_id):
            execution = db.session.get(Execution, execution_id)
            if execution:
                _fail_execution(execution, "No execution slots available for test run.")
    except PipelineAbort:
        return execution_id

    execution = db.session.get(Execution, execution_id)
    if execution is None:
        _release_exec_slot(execution_id)
        return execution_id

    project = db.session.get(Project, execution.project_id)
    venv_path = _venv_path(execution_id)
    repo_path = project.repo_path

    _set_status(execution, ExecutionStatus.RUNNING)

    pytest_bin = os.path.join(venv_path, "bin", "pytest")
    if not os.path.isfile(pytest_bin):
        _fail_execution(execution, "pytest binary not found in venv.", cleanup_venv=venv_path)

    # Determine test path
    if execution.suite_id:
        suite = db.session.get(TestSuite, execution.suite_id)
        test_path = os.path.join(repo_path, suite.path_in_repo) if suite else repo_path
    else:
        test_path = repo_path

    # Output dirs
    results_dir = _results_dir(execution_id)
    os.makedirs(results_dir, exist_ok=True)
    junit_path = os.path.join(results_dir, "junit.xml")

    # Build command
    cmd = [
        pytest_bin,
        test_path,
        f"--alluredir={results_dir}",
        f"--junitxml={junit_path}",
        "-v",
        "--tb=short",
    ]
    if execution.extra_args:
        tokens = shlex.split(execution.extra_args)
        i = 0
        while i < len(tokens):
            flag = tokens[i]
            if flag not in _ALLOWED_PYTEST_FLAGS:
                raise ValueError(f"Disallowed pytest argument: {flag}")
            cmd.append(flag)
            # Flags that take a value
            if flag in ("-k", "--timeout", "--tb", "-m", "--maxfail") and i + 1 < len(tokens):
                cmd.append(tokens[i + 1])
                i += 2
            else:
                i += 1

    use_sandbox = os.getenv("ENABLE_SANDBOX", "false").lower() == "true"

    if use_sandbox:
        try:
            from app.tasks.sandbox import SandboxRunner, SandboxConfigError, SandboxRuntimeError
            # Resolve network: project override > system default
            if project.sandbox_network is not None:
                network_disabled = not project.sandbox_network
            else:
                from app.models.system_config import SystemConfig
                sys_default = SystemConfig.get("execution.sandbox_network_default", "false")
                network_disabled = sys_default.lower() != "true"

            runner = SandboxRunner(
                repo_path=repo_path,
                venv_path=venv_path,
                results_dir=results_dir,
                network_disabled=network_disabled,
            )
            result = runner.run(cmd)
        except SandboxConfigError as exc:
            _fail_execution(execution, f"Sandbox configuration error: {exc}", cleanup_venv=venv_path)
        except SandboxRuntimeError as exc:
            logger.warning("Sandbox failed (%s), falling back to subprocess", exc)
            use_sandbox = False  # fall through to subprocess below

    if not use_sandbox:
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=1800,  # 30 min max test run
                cwd=repo_path,
                env={**os.environ, "VIRTUAL_ENV": venv_path, "PATH": f"{venv_path}/bin:{os.environ.get('PATH', '')}"},
            )
            result = {"return_code": result.returncode, "stdout": result.stdout or "", "stderr": result.stderr or ""}
        except subprocess.TimeoutExpired:
            _fail_execution(execution, "Test execution timed out (30 min limit).", cleanup_venv=venv_path)
        except Exception as exc:
            _fail_execution(execution, f"Test execution error: {exc}", cleanup_venv=venv_path)

    execution.exit_code = result["return_code"]
    execution.stdout = result["stdout"][-50000:] if result["stdout"] else None
    execution.stderr = result["stderr"][-50000:] if result["stderr"] else None
    db.session.commit()

    # Parse JUnit XML results
    from app.executions.services import parse_pytest_output

    try:
        parse_pytest_output(execution.id, junit_path)
    except Exception as exc:
        logger.warning("JUnit parse error for execution %d: %s", execution.id, exc)

    _set_status(execution, ExecutionStatus.EXECUTED)
    _release_exec_slot(execution_id)
    return execution_id


# ------------------------------------------------------------------
# Stage 3: Generate Report
# ------------------------------------------------------------------

@celery.task(
    name="app.tasks.execution_tasks.stage_generate_report",
    bind=True,
    acks_late=True,
    max_retries=0,
)
def stage_generate_report(self, execution_id: int) -> int:
    """Generate Allure HTML report.

    Status transitions: EXECUTED -> RUNNING -> COMPLETED (or FAILED).
    Always cleans up the venv at the end.
    """
    # Guard: abort if execution is already in a terminal state
    execution = db.session.get(Execution, execution_id)
    if execution and execution.is_terminal:
        logger.warning("Execution %d already in terminal state %s, skipping stage_generate_report",
                       execution_id, execution.status.value)
        return execution_id

    # Re-acquire concurrency slot
    try:
        if not _acquire_exec_slot(execution_id):
            execution = db.session.get(Execution, execution_id)
            if execution:
                _fail_execution(execution, "No execution slots available for report generation.")
    except PipelineAbort:
        return execution_id

    execution = db.session.get(Execution, execution_id)
    if execution is None:
        _release_exec_slot(execution_id)
        return execution_id

    venv_path = _venv_path(execution_id)
    results_dir = _results_dir(execution_id)
    report_dir = f"/app/allure-reports/{execution_id}"

    _set_status(execution, ExecutionStatus.RUNNING)

    try:
        # Clean previous report
        if os.path.isdir(report_dir):
            shutil.rmtree(report_dir)

        result = subprocess.run(
            ["allure", "generate", results_dir, "-o", report_dir, "--clean"],
            capture_output=True,
            text=True,
            timeout=300,
            check=True,
        )

        # Calculate report size
        total_size = 0
        for dirpath, _dirnames, filenames in os.walk(report_dir):
            for f in filenames:
                fp = os.path.join(dirpath, f)
                if os.path.isfile(fp):
                    total_size += os.path.getsize(fp)
        size_mb = round(total_size / (1024 * 1024), 2)

        # Create AllureReport record
        report = AllureReport(
            execution_id=execution.id,
            report_path=report_dir,
            report_url=f"/reports/{execution.id}/",
            file_size_mb=size_mb,
        )
        db.session.add(report)

    except subprocess.TimeoutExpired as exc:
        _fail_execution(execution, f"Allure report generation timed out: {exc}", cleanup_venv=venv_path)
    except subprocess.CalledProcessError as exc:
        _fail_execution(
            execution,
            f"Allure report failed (rc={exc.returncode}): {(exc.stderr or '')[:500]}",
            cleanup_venv=venv_path,
        )
    except Exception as exc:
        _fail_execution(execution, f"Report generation error: {exc}", cleanup_venv=venv_path)

    # Mark completed
    execution.status = ExecutionStatus.COMPLETED
    execution.finished_at = datetime.now(timezone.utc)
    execution.update_duration()
    db.session.commit()
    logger.info("Execution %d COMPLETED", execution.id)

    # Always cleanup venv on completion
    _cleanup_venv(venv_path)
    _release_exec_slot(execution_id)

    return execution_id
