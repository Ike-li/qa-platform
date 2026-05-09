"""Celery task for sending notifications after test execution."""

import logging
from datetime import datetime, timezone

from app.extensions import db

logger = logging.getLogger(__name__)


from app.extensions import celery


@celery.task(name="app.tasks.notification_tasks.send_notification", bind=True, max_retries=3, default_retry_delay=60)
def send_notification(self, execution_id: int) -> None:
    """Send notifications for a completed execution to all active channels.

    Loads the execution, checks NotificationConfig for the project,
    sends to all active channels, and logs to NotificationLog.
    Retried up to 3 times on transient failures.
    Retried up to 3 times on failure by Celery.
    """
    from app.models.execution import Execution
    from app.models.notification import NotificationChannel, NotificationConfig, NotificationLog
    from app.notifications.services import send_dingtalk, send_email, send_wechat

    execution = db.session.get(Execution, execution_id)
    if not execution:
        logger.warning("Execution %d not found, skipping notification", execution_id)
        return

    project = execution.project
    configs = NotificationConfig.query.filter_by(
        project_id=project.id, is_active=True
    ).all()

    if not configs:
        logger.debug("No active notification configs for project %d", project.id)
        return

    # Build notification content
    pass_count = sum(1 for r in execution.test_results if r.status.value == "passed")
    fail_count = sum(1 for r in execution.test_results if r.status.value in ("failed", "error"))
    total = len(execution.test_results)
    pass_rate = f"{pass_count / total * 100:.1f}%" if total > 0 else "N/A"

    allure_link = ""
    if execution.allure_report:
        allure_link = f"\n[查看 Allure 报告]({execution.allure_report.report_url})"

    subject = f"[QA Platform] {project.name} - 测试执行完成"
    markdown_body = (
        f"## {project.name}\n\n"
        f"- **状态**: {execution.status.value}\n"
        f"- **分支**: {execution.project.git_branch}\n"
        f"- **通过率**: {pass_rate} ({pass_count}/{total})\n"
        f"- **失败数**: {fail_count}\n"
        f"- **耗时**: {execution.duration_sec or 0}秒\n"
        f"- **触发方式**: {execution.trigger_type.value}\n"
        f"{allure_link}"
    )

    for config in configs:
        # Check if this event type is configured
        trigger_events = config.trigger_events or []
        event_type = "execution_done" if execution.status.value == "completed" else "execution_fail"
        if trigger_events and event_type not in trigger_events:
            continue

        # Check for duplicate (idempotency)
        existing = NotificationLog.query.filter_by(
            execution_id=execution_id, channel=config.channel, status="sent"
        ).first()
        if existing:
            logger.debug(
                "Notification already sent for execution %d channel %s, skipping",
                execution_id, config.channel.value,
            )
            continue

        log = NotificationLog(
            execution_id=execution_id,
            config_id=config.id,
            channel=config.channel,
        )

        try:
            if config.channel == NotificationChannel.EMAIL:
                recipients = [e.strip() for e in (config.email_recipients or "").split(",") if e.strip()]
                if recipients:
                    send_email(recipients, subject, markdown_body)
                else:
                    log.status = "failed"
                    log.error_msg = "No recipients configured"
                    db.session.add(log)
                    continue

            elif config.channel == NotificationChannel.DINGTALK:
                if config.webhook_url:
                    send_dingtalk(config.webhook_url, subject, markdown_body)
                else:
                    log.status = "failed"
                    log.error_msg = "No webhook URL configured"
                    db.session.add(log)
                    continue

            elif config.channel == NotificationChannel.WECHAT:
                if config.webhook_url:
                    send_wechat(config.webhook_url, markdown_body)
                else:
                    log.status = "failed"
                    log.error_msg = "No webhook URL configured"
                    db.session.add(log)
                    continue

            log.status = "sent"
            log.sent_at = datetime.now(timezone.utc)

        except Exception as exc:
            logger.exception(
                "Notification failed for execution %d channel %s",
                execution_id, config.channel.value,
            )
            log.status = "failed"
            log.error_msg = str(exc)[:500]
            db.session.add(log)
            db.session.commit()
            # Retry on transient network errors (timeout, connection reset, etc.)
            if isinstance(exc, (OSError, TimeoutError, ConnectionError)):
                raise self.retry(exc=exc, countdown=60 * (self.request.retries + 1))
            # Non-retryable errors (config issues, auth failures) are logged but not retried
            continue

        db.session.add(log)

    db.session.commit()
    logger.info("Notifications processed for execution %d", execution_id)
