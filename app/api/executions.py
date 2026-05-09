"""API endpoint for triggering test executions."""

import logging

from flask import g, jsonify, request

from app.api import api_bp, rate_limit
from app.api.auth import token_required
from app.extensions import db
from app.models.execution import Execution, ExecutionStatus, TriggerType
from app.models.project import Project
from app.models.test_suite import TestSuite

logger = logging.getLogger(__name__)


@api_bp.route("/executions", methods=["POST"])
@token_required
@rate_limit
def create_execution():
    """Trigger a new test execution.

    JSON body::

        {
            "project_id": 1,
            "suite_id": 2,         // optional
            "extra_args": "-k foo"  // optional
        }
    """
    # RBAC permission check
    from app.models.user import User
    user = db.session.get(User, g.api_user_id)
    if user is None or not user.has_permission("execution.trigger"):
        return jsonify({"error": "权限不足，需要 execution.trigger 权限。"}), 403

    data = request.get_json(silent=True) or {}

    project_id = data.get("project_id")
    if not project_id:
        return jsonify({"error": "缺少必填参数 project_id。"}), 400

    project = Project.query.get(project_id)
    if project is None:
        return jsonify({"error": "项目未找到。"}), 404

    suite_id = data.get("suite_id")
    if suite_id is not None:
        suite = TestSuite.query.filter_by(id=suite_id, project_id=project_id).first()
        if suite is None:
            return jsonify({"error": "测试套件未找到或不属于该项目。"}), 404

    extra_args = data.get("extra_args")

    try:
        execution = Execution(
            project_id=project.id,
            suite_id=suite_id,
            triggered_by=g.api_user_id,
            trigger_type=TriggerType.API,
            extra_args=extra_args.strip() if extra_args else None,
            status=ExecutionStatus.PENDING,
        )
        db.session.add(execution)
        db.session.commit()

        from app.tasks.execution_tasks import run_execution_pipeline

        result = run_execution_pipeline.delay(execution.id)
        execution.celery_task_id = result.id
        db.session.commit()

        logger.info(
            "API triggered execution %d for project %d by token %d",
            execution.id, project_id, g.api_token.id,
        )

        return jsonify({
            "execution_id": execution.id,
            "status": execution.status.value,
            "project_id": project.id,
            "suite_id": suite_id,
            "celery_task_id": result.id,
        }), 201

    except Exception as exc:
        db.session.rollback()
        logger.exception("API execution creation failed")
        return jsonify({"error": str(exc)}), 500
