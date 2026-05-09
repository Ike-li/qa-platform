"""Async git operations as Celery tasks."""

import logging
import os
import subprocess

from flask_socketio import SocketIO

from app.extensions import celery, db
from app.models.project import Project
from app.projects.services import clone_repo, pull_repo, discover_suites

logger = logging.getLogger(__name__)

# SocketIO instance for Celery workers to emit events to the web process
_worker_socketio = SocketIO(
    async_mode="threading",
    message_queue=os.getenv("CELERY_BROKER_URL", "redis://redis:6379/0"),
)


def emit_fn(event: str, data: dict, room: str | None = None):
    """Emit a SocketIO event via the message queue."""
    _worker_socketio.emit(event, data, room=room)


def _run_git_stream(args: list[str], cwd: str, timeout: int = 300,
                    emit_fn=None, room: str | None = None) -> subprocess.Popen:
    """Execute a git command and stream stdout lines via emit_fn.

    Returns the completed Popen object. Raises RuntimeError on non-zero exit.
    """
    cmd = ["git"] + args
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        cwd=cwd,
    )
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            stripped = line.rstrip("\n")
            if emit_fn and room:
                emit_fn("git_output", {"line": stripped}, room=room)
        proc.wait(timeout=timeout)
    except Exception:
        proc.kill()
        raise

    if proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed (rc={proc.returncode})")
    return proc


@celery.task(name="app.tasks.git_tasks.git_sync_project", bind=True, max_retries=0)
def git_sync_project(self, project_id: int, action: str = "pull"):
    """Clone or pull a project repository asynchronously.

    Emits SocketIO step progress events to room ``project:{id}:sync``.
    """
    project = db.session.get(Project, project_id)
    if project is None:
        logger.error("Project %d not found for git sync", project_id)
        return {"status": "error", "message": "Project not found"}

    room = f"project:{project_id}:sync"

    try:
        if action == "clone":
            emit_fn("sync_step", {"step": "cloning", "status": "in_progress"}, room=room)
            clone_repo(project)
            emit_fn("sync_step", {"step": "installing_deps", "status": "in_progress"}, room=room)
            emit_fn("sync_step", {"step": "discovering_tests", "status": "in_progress"}, room=room)
            suites = discover_suites(project)
            logger.info("Git sync: cloned project %d, found %d suites", project_id, len(suites))
            emit_fn("sync_step", {"step": "complete", "status": "done", "suites_found": len(suites)}, room=room)
            return {"status": "success", "action": "clone", "project_id": project_id,
                    "suites_found": len(suites)}
        elif action == "pull":
            emit_fn("sync_step", {"step": "pulling", "status": "in_progress"}, room=room)
            output = pull_repo(project)
            logger.info("Git sync: pulled project %d", project_id)
            emit_fn("sync_step", {"step": "complete", "status": "done"}, room=room)
            return {"status": "success", "action": "pull", "output": output}
        elif action == "pull_and_discover":
            emit_fn("sync_step", {"step": "pulling", "status": "in_progress"}, room=room)
            pull_repo(project)
            emit_fn("sync_step", {"step": "discovering_tests", "status": "in_progress"}, room=room)
            suites = discover_suites(project)
            logger.info("Git sync: pulled and discovered project %d, found %d suites",
                        project_id, len(suites))
            emit_fn("sync_step", {"step": "complete", "status": "done", "suites_found": len(suites)}, room=room)
            return {"status": "success", "action": "pull_and_discover",
                    "suites_found": len(suites)}
        else:
            logger.error("Unknown git sync action: %s", action)
            return {"status": "error", "message": f"Unknown action: {action}"}
    except Exception as exc:
        logger.exception("Git sync failed for project %d", project_id)
        emit_fn("sync_step", {"step": "error", "message": str(exc)}, room=room)
        return {"status": "error", "message": str(exc)}
