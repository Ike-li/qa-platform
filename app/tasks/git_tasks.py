"""Async git operations as Celery tasks."""

import logging

from app.extensions import celery, db
from app.models.project import Project
from app.projects.services import clone_repo, pull_repo, discover_suites

logger = logging.getLogger(__name__)


@celery.task(name="app.tasks.git_tasks.git_sync_project", bind=True, max_retries=0)
def git_sync_project(self, project_id: int, action: str = "pull"):
    """Clone or pull a project repository asynchronously.

    Args:
        project_id: The project to sync
        action: "clone", "pull", or "pull_and_discover"
    """
    project = db.session.get(Project, project_id)
    if project is None:
        logger.error("Project %d not found for git sync", project_id)
        return {"status": "error", "message": "Project not found"}

    try:
        if action == "clone":
            clone_repo(project)
            suites = discover_suites(project)
            logger.info("Git sync: cloned project %d, found %d suites", project_id, len(suites))
            return {"status": "success", "action": "clone", "project_id": project_id,
                    "suites_found": len(suites)}
        elif action == "pull":
            output = pull_repo(project)
            logger.info("Git sync: pulled project %d", project_id)
            return {"status": "success", "action": "pull", "output": output}
        elif action == "pull_and_discover":
            pull_repo(project)
            suites = discover_suites(project)
            logger.info("Git sync: pulled and discovered project %d, found %d suites",
                        project_id, len(suites))
            return {"status": "success", "action": "pull_and_discover",
                    "suites_found": len(suites)}
        else:
            logger.error("Unknown git sync action: %s", action)
            return {"status": "error", "message": f"Unknown action: {action}"}
    except Exception as exc:
        logger.exception("Git sync failed for project %d", project_id)
        return {"status": "error", "message": str(exc)}
