"""Celery tasks implementing the three-stage checkpointed chained pipeline.

Pipeline: stage_git_sync -> stage_run_tests -> stage_generate_report

Each stage writes status before AND after execution.
On failure the pipeline stops and no further stages execute.
Concurrency is controlled via a Redis distributed lock.
"""

import logging
import os
import shutil
import subprocess
from datetime import datetime, timezone

from celery import chain
from redis import Redis

from app.extensions import celery, db
from app.models.allure_report import AllureReport
from app.models.execution import Execution, ExecutionStatus
from app.models.project import Project
from app.models.test_suite import TestSuite

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------
# Concurrency guard
# ------------------------------------------------------------------

REDIS_URL = os.getenv("CELERY_BROKER_URL", "redis://redis:6379/0")
_redis = Redis.from_url(REDIS_URL)

# Default max parallel executions; overridden by SystemConfig if present
DEFAULT_MAX_EXEC_SLOTS = 3
EXEC_LOCK_TIMEOUT = 3600  # 1 hour max hold
EXEC_LOCK_BLOCKING_TIMEOUT = 600  # wait up to 10 min for a slot


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


def _acquire_exec_slot() -> bool:
    """Try to acquire an execution slot using a Redis counter + lock."""
    lock = _redis.lock("exec_slots_lock", timeout=10)
    if not lock.acquire(blocking=True, blocking_timeout=5):
        return False
    try:
        current = _redis.get("exec_slots_active")
        current = int(current) if current else 0
        if current >= _get_max_slots():
            return False
        _redis.incr("exec_slots_active")
        return True
    finally:
        try:
            lock.release()
        except Exception:
            pass


def _release_exec_slot() -> None:
    """Release one execution slot."""
    try:
        current = _redis.get("exec_slots_active")
        current = int(current) if current else 0
        if current > 0:
            _redis.decr("exec_slots_active")
    except Exception:
        pass


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _set_status(execution: Execution, status: ExecutionStatus) -> None:
    """Update execution status and commit."""
    execution.status = status
    db.session.commit()
    logger.info("Execution %d -> %s", execution.id, status.value)


def _fail_execution(execution: Execution, error: str, cleanup_venv: str | None = None) -> None:
    """Mark execution as failed, optionally clean up venv, and abort."""
    execution.status = ExecutionStatus.FAILED
    execution.error_detail = error
    execution.finished_at = datetime.now(timezone.utc)
    execution.update_duration()
    db.session.commit()
    logger.error("Execution %d FAILED: %s", execution.id, error[:500])
    _release_exec_slot()
    if cleanup_venv:
        _cleanup_venv(cleanup_venv)


def _timeout_execution(execution: Execution, cleanup_venv: str | None = None) -> None:
    """Mark execution as timed out."""
    execution.status = ExecutionStatus.TIMEOUT
    execution.error_detail = "Execution timed out."
    execution.finished_at = datetime.now(timezone.utc)
    execution.update_duration()
    db.session.commit()
    logger.error("Execution %d TIMEOUT", execution.id)
    _release_exec_slot()
    if cleanup_venv:
        _cleanup_venv(cleanup_venv)


def _cleanup_venv(venv_path: str) -> None:
    """Remove a virtualenv directory, ignoring errors."""
    try:
        if os.path.isdir(venv_path):
            shutil.rmtree(venv_path)
            logger.info("Cleaned up venv: %s", venv_path)
    except OSError as exc:
        logger.warning("Failed to clean up venv %s: %s", venv_path, exc)


def _build_clone_url(git_url: str, credential: str | None) -> str:
    """Embed credential into git URL for HTTPS auth."""
    if not credential or not git_url.startswith("https://"):
        return git_url
    from urllib.parse import urlparse, urlunparse

    parsed = urlparse(git_url)
    netloc = f"{credential}@{parsed.hostname}"
    if parsed.port:
        netloc = f"{netloc}:{parsed.port}"
    return urlunparse(parsed._replace(netloc=netloc))


def _venv_path(execution_id: int) -> str:
    return f"/data/venvs/{execution_id}"


def _results_dir(execution_id: int) -> str:
    return f"/data/execution_results/{execution_id}"


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
    if not _acquire_exec_slot():
        execution = db.session.get(Execution, execution_id)
        if execution:
            _fail_execution(execution, "No execution slots available. Try again later.")
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
        return execution_id

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
        return execution_id
    except subprocess.CalledProcessError as exc:
        _fail_execution(execution, f"Git failed (rc={exc.returncode}): {(exc.stderr or '')[:500]}")
        return execution_id
    except Exception as exc:
        _fail_execution(execution, f"Unexpected git error: {exc}")
        return execution_id

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
        return execution_id
    except subprocess.CalledProcessError as exc:
        _fail_execution(
            execution,
            f"Venv setup failed (rc={exc.returncode}): {(exc.stderr or '')[:500]}",
            cleanup_venv=venv_path,
        )
        return execution_id
    except Exception as exc:
        _fail_execution(execution, f"Venv error: {exc}", cleanup_venv=venv_path)
        return execution_id

    _set_status(execution, ExecutionStatus.CLONED)
    _release_exec_slot()  # release while waiting for next stage (it will re-acquire)
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
    # Re-acquire concurrency slot
    if not _acquire_exec_slot():
        execution = db.session.get(Execution, execution_id)
        if execution:
            _fail_execution(execution, "No execution slots available for test run.")
        return execution_id

    execution = db.session.get(Execution, execution_id)
    if execution is None:
        _release_exec_slot()
        return execution_id

    project = db.session.get(Project, execution.project_id)
    venv_path = _venv_path(execution_id)
    repo_path = project.repo_path

    _set_status(execution, ExecutionStatus.RUNNING)

    pytest_bin = os.path.join(venv_path, "bin", "pytest")
    if not os.path.isfile(pytest_bin):
        _fail_execution(execution, "pytest binary not found in venv.", cleanup_venv=venv_path)
        return execution_id

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
        import shlex
        _ALLOWED_PYTEST_FLAGS = {"-k", "--timeout", "-x", "--tb", "-v", "-q", "--co", "--maxfail", "-m", "-s"}
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

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=1800,  # 30 min max test run
            cwd=repo_path,
            env={**os.environ, "VIRTUAL_ENV": venv_path, "PATH": f"{venv_path}/bin:{os.environ.get('PATH', '')}"},
        )
        execution.exit_code = result.returncode
        execution.stdout = result.stdout[-50000:] if result.stdout else None
        execution.stderr = result.stderr[-50000:] if result.stderr else None
        db.session.commit()

    except subprocess.TimeoutExpired:
        _fail_execution(execution, "Test execution timed out (30 min limit).", cleanup_venv=venv_path)
        return execution_id
    except Exception as exc:
        _fail_execution(execution, f"Test execution error: {exc}", cleanup_venv=venv_path)
        return execution_id

    # Parse JUnit XML results
    from app.executions.services import parse_pytest_output

    try:
        parse_pytest_output(execution.id, junit_path)
    except Exception as exc:
        logger.warning("JUnit parse error for execution %d: %s", execution.id, exc)

    _set_status(execution, ExecutionStatus.EXECUTED)
    _release_exec_slot()
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
    # Re-acquire concurrency slot
    if not _acquire_exec_slot():
        execution = db.session.get(Execution, execution_id)
        if execution:
            _fail_execution(execution, "No execution slots available for report generation.")
        return execution_id

    execution = db.session.get(Execution, execution_id)
    if execution is None:
        _release_exec_slot()
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
        _fail_execution(execution, f"Allure report generation timed out: {exc}")
        _cleanup_venv(venv_path)
        return execution_id
    except subprocess.CalledProcessError as exc:
        _fail_execution(
            execution,
            f"Allure report failed (rc={exc.returncode}): {(exc.stderr or '')[:500]}",
        )
        _cleanup_venv(venv_path)
        return execution_id
    except Exception as exc:
        _fail_execution(execution, f"Report generation error: {exc}")
        _cleanup_venv(venv_path)
        return execution_id

    # Mark completed
    execution.status = ExecutionStatus.COMPLETED
    execution.finished_at = datetime.now(timezone.utc)
    execution.update_duration()
    db.session.commit()
    logger.info("Execution %d COMPLETED", execution.id)

    # Always cleanup venv on completion
    _cleanup_venv(venv_path)
    _release_exec_slot()

    return execution_id
