"""Tests for app.tasks.notification_tasks – send_notification Celery task."""

from unittest.mock import MagicMock, patch

import pytest


def _make_execution(
    project_id=1,
    status_value="completed",
    test_results=None,
    allure_report=None,
    duration_sec=10.0,
    trigger_type_value="web",
    git_branch="main",
):
    """Build a mock Execution with the attributes the task reads."""
    exec_ = MagicMock()
    exec_.id = 100
    exec_.project_id = project_id
    exec_.status.value = status_value
    exec_.test_results = test_results or []
    exec_.allure_report = allure_report
    exec_.duration_sec = duration_sec
    exec_.trigger_type.value = trigger_type_value
    exec_.project = MagicMock()
    exec_.project.id = project_id
    exec_.project.name = "TestProject"
    exec_.project.git_branch = git_branch
    return exec_


def _make_result(status_value):
    r = MagicMock()
    r.status.value = status_value
    return r


class TestSendNotification:
    """Tests for the send_notification Celery task."""

    def test_execution_not_found(self):
        """Skips when execution does not exist."""
        from app.tasks.notification_tasks import send_notification

        with patch("app.tasks.notification_tasks.db") as mock_db:
            mock_db.session.get.return_value = None
            send_notification.run(execution_id=999)

    def test_no_active_configs(self):
        """Skips when no active notification configs exist."""
        from app.tasks.notification_tasks import send_notification

        exec_ = _make_execution()
        with patch("app.tasks.notification_tasks.db") as mock_db:
            mock_db.session.get.return_value = exec_
            with patch("app.models.notification.NotificationConfig") as mock_cfg:
                mock_cfg.query.filter_by.return_value.all.return_value = []
                send_notification.run(execution_id=100)

    @patch("app.notifications.services.send_email")
    def test_email_sent(self, mock_send_email):
        """Email notification dispatched to configured recipients."""
        from app.tasks.notification_tasks import send_notification
        from app.models.notification import NotificationChannel

        exec_ = _make_execution(test_results=[_make_result("passed")])

        config = MagicMock()
        config.channel = NotificationChannel.EMAIL
        config.email_recipients = "a@test.com,b@test.com"
        config.webhook_url = None
        config.trigger_events = []
        config.is_active = True
        config.id = 1

        with patch("app.tasks.notification_tasks.db") as mock_db:
            mock_db.session.get.return_value = exec_
            with patch("app.models.notification.NotificationConfig") as mock_cfg_cls:
                mock_cfg_cls.query.filter_by.return_value.all.return_value = [config]
                with patch("app.models.notification.NotificationLog") as mock_log_cls:
                    mock_log_cls.query.filter_by.return_value.first.return_value = None
                    send_notification.run(execution_id=100)
        mock_send_email.assert_called_once()

    @patch("app.notifications.services.send_dingtalk")
    def test_dingtalk_sent(self, mock_send_dingtalk):
        """DingTalk notification dispatched via webhook."""
        from app.tasks.notification_tasks import send_notification
        from app.models.notification import NotificationChannel

        exec_ = _make_execution(test_results=[_make_result("passed")])

        config = MagicMock()
        config.channel = NotificationChannel.DINGTALK
        config.webhook_url = "https://oapi.dingtalk.com/robot/send"
        config.email_recipients = None
        config.trigger_events = []
        config.is_active = True
        config.id = 2

        with patch("app.tasks.notification_tasks.db") as mock_db:
            mock_db.session.get.return_value = exec_
            with patch("app.models.notification.NotificationConfig") as mock_cfg_cls:
                mock_cfg_cls.query.filter_by.return_value.all.return_value = [config]
                with patch("app.models.notification.NotificationLog") as mock_log_cls:
                    mock_log_cls.query.filter_by.return_value.first.return_value = None
                    send_notification.run(execution_id=100)
        mock_send_dingtalk.assert_called_once()

    @patch("app.notifications.services.send_wechat")
    def test_wechat_sent(self, mock_send_wechat):
        """WeChat notification dispatched via webhook."""
        from app.tasks.notification_tasks import send_notification
        from app.models.notification import NotificationChannel

        exec_ = _make_execution(test_results=[_make_result("passed")])

        config = MagicMock()
        config.channel = NotificationChannel.WECHAT
        config.webhook_url = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send"
        config.email_recipients = None
        config.trigger_events = []
        config.is_active = True
        config.id = 3

        with patch("app.tasks.notification_tasks.db") as mock_db:
            mock_db.session.get.return_value = exec_
            with patch("app.models.notification.NotificationConfig") as mock_cfg_cls:
                mock_cfg_cls.query.filter_by.return_value.all.return_value = [config]
                with patch("app.models.notification.NotificationLog") as mock_log_cls:
                    mock_log_cls.query.filter_by.return_value.first.return_value = None
                    send_notification.run(execution_id=100)
        mock_send_wechat.assert_called_once()

    def test_skip_already_sent(self):
        """Skips sending if a NotificationLog with status 'sent' already exists."""
        from app.tasks.notification_tasks import send_notification
        from app.models.notification import NotificationChannel

        exec_ = _make_execution(test_results=[_make_result("passed")])

        config = MagicMock()
        config.channel = NotificationChannel.EMAIL
        config.email_recipients = "a@test.com"
        config.trigger_events = []
        config.is_active = True
        config.id = 1

        existing_log = MagicMock()

        with patch("app.tasks.notification_tasks.db") as mock_db:
            mock_db.session.get.return_value = exec_
            with patch("app.models.notification.NotificationConfig") as mock_cfg_cls:
                mock_cfg_cls.query.filter_by.return_value.all.return_value = [config]
                with patch("app.models.notification.NotificationLog") as mock_log_cls:
                    mock_log_cls.query.filter_by.return_value.first.return_value = (
                        existing_log
                    )
                    with patch("app.notifications.services.send_email") as mock_email:
                        send_notification.run(execution_id=100)
                        mock_email.assert_not_called()

    def test_email_no_recipients_marks_failed(self):
        """Email config with no recipients marks log as failed."""
        from app.tasks.notification_tasks import send_notification
        from app.models.notification import NotificationChannel

        exec_ = _make_execution(test_results=[_make_result("passed")])

        config = MagicMock()
        config.channel = NotificationChannel.EMAIL
        config.email_recipients = ""
        config.trigger_events = []
        config.is_active = True
        config.id = 1

        with patch("app.tasks.notification_tasks.db") as mock_db:
            mock_db.session.get.return_value = exec_
            with patch("app.models.notification.NotificationConfig") as mock_cfg_cls:
                mock_cfg_cls.query.filter_by.return_value.all.return_value = [config]
                with patch("app.models.notification.NotificationLog") as mock_log_cls:
                    mock_log_cls.query.filter_by.return_value.first.return_value = None
                    log_instance = MagicMock()
                    mock_log_cls.return_value = log_instance
                    send_notification.run(execution_id=100)
                    assert log_instance.status == "failed"
                    assert "No recipients" in log_instance.error_msg

    def test_dingtalk_no_webhook_marks_failed(self):
        """DingTalk config with no webhook_url marks log as failed."""
        from app.tasks.notification_tasks import send_notification
        from app.models.notification import NotificationChannel

        exec_ = _make_execution(test_results=[_make_result("passed")])

        config = MagicMock()
        config.channel = NotificationChannel.DINGTALK
        config.webhook_url = None
        config.trigger_events = []
        config.is_active = True
        config.id = 1

        with patch("app.tasks.notification_tasks.db") as mock_db:
            mock_db.session.get.return_value = exec_
            with patch("app.models.notification.NotificationConfig") as mock_cfg_cls:
                mock_cfg_cls.query.filter_by.return_value.all.return_value = [config]
                with patch("app.models.notification.NotificationLog") as mock_log_cls:
                    mock_log_cls.query.filter_by.return_value.first.return_value = None
                    log_instance = MagicMock()
                    mock_log_cls.return_value = log_instance
                    send_notification.run(execution_id=100)
                    assert log_instance.status == "failed"
                    assert "No webhook" in log_instance.error_msg

    @patch("app.notifications.services.send_email", side_effect=OSError("network"))
    def test_network_error_retries(self, mock_send_email):
        """OSError from send_email triggers self.retry."""
        from celery.exceptions import Retry

        from app.tasks.notification_tasks import send_notification
        from app.models.notification import NotificationChannel

        exec_ = _make_execution(test_results=[_make_result("passed")])

        config = MagicMock()
        config.channel = NotificationChannel.EMAIL
        config.email_recipients = "a@test.com"
        config.trigger_events = []
        config.is_active = True
        config.id = 1

        with patch("app.tasks.notification_tasks.db") as mock_db:
            mock_db.session.get.return_value = exec_
            with patch("app.models.notification.NotificationConfig") as mock_cfg_cls:
                mock_cfg_cls.query.filter_by.return_value.all.return_value = [config]
                with patch("app.models.notification.NotificationLog") as mock_log_cls:
                    mock_log_cls.query.filter_by.return_value.first.return_value = None
                    # Replace retry to raise Retry (Celery's actual behavior)
                    original_retry = send_notification.retry
                    send_notification.retry = MagicMock(side_effect=Retry())
                    try:
                        with pytest.raises(Retry):
                            send_notification.run(execution_id=100)
                        send_notification.retry.assert_called_once()
                    finally:
                        send_notification.retry = original_retry

    def test_trigger_events_filter(self):
        """Notification skipped when event type not in config.trigger_events."""
        from app.tasks.notification_tasks import send_notification
        from app.models.notification import NotificationChannel

        exec_ = _make_execution(
            status_value="completed",
            test_results=[_make_result("passed")],
        )

        config = MagicMock()
        config.channel = NotificationChannel.EMAIL
        config.email_recipients = "a@test.com"
        config.trigger_events = ["execution_fail"]  # only fail events
        config.is_active = True
        config.id = 1

        with patch("app.tasks.notification_tasks.db") as mock_db:
            mock_db.session.get.return_value = exec_
            with patch("app.models.notification.NotificationConfig") as mock_cfg_cls:
                mock_cfg_cls.query.filter_by.return_value.all.return_value = [config]
                with patch("app.notifications.services.send_email") as mock_email:
                    send_notification.run(execution_id=100)
                    mock_email.assert_not_called()

    def test_allure_link_included(self):
        """Allure report link is included in notification body when set."""
        from app.tasks.notification_tasks import send_notification
        from app.models.notification import NotificationChannel

        allure_mock = MagicMock()
        allure_mock.report_url = "http://allure.local/report/123"
        exec_ = _make_execution(
            test_results=[_make_result("passed")],
            allure_report=allure_mock,
        )

        config = MagicMock()
        config.channel = NotificationChannel.EMAIL
        config.email_recipients = "a@test.com"
        config.trigger_events = []
        config.is_active = True
        config.id = 1

        with patch("app.tasks.notification_tasks.db") as mock_db:
            mock_db.session.get.return_value = exec_
            with patch("app.models.notification.NotificationConfig") as mock_cfg_cls:
                mock_cfg_cls.query.filter_by.return_value.all.return_value = [config]
                with patch("app.models.notification.NotificationLog") as mock_log_cls:
                    mock_log_cls.query.filter_by.return_value.first.return_value = None
                    with patch("app.notifications.services.send_email") as mock_email:
                        send_notification.run(execution_id=100)
                        call_args = mock_email.call_args
                        body = call_args[0][2]
                        assert "Allure" in body
                        assert "http://allure.local/report/123" in body

    def test_wechat_no_webhook_marks_failed(self):
        """WeChat config with no webhook_url marks log as failed."""
        from app.tasks.notification_tasks import send_notification
        from app.models.notification import NotificationChannel

        exec_ = _make_execution(test_results=[_make_result("passed")])

        config = MagicMock()
        config.channel = NotificationChannel.WECHAT
        config.webhook_url = None
        config.trigger_events = []
        config.is_active = True
        config.id = 1

        with patch("app.tasks.notification_tasks.db") as mock_db:
            mock_db.session.get.return_value = exec_
            with patch("app.models.notification.NotificationConfig") as mock_cfg_cls:
                mock_cfg_cls.query.filter_by.return_value.all.return_value = [config]
                with patch("app.models.notification.NotificationLog") as mock_log_cls:
                    mock_log_cls.query.filter_by.return_value.first.return_value = None
                    log_instance = MagicMock()
                    mock_log_cls.return_value = log_instance
                    send_notification.run(execution_id=100)
                    assert log_instance.status == "failed"
                    assert "No webhook" in log_instance.error_msg

    @patch(
        "app.notifications.services.send_email", side_effect=ValueError("bad config")
    )
    def test_non_retryable_error_continues(self, mock_send_email):
        """ValueError (non-retryable) logs failure and continues without retry."""
        from app.tasks.notification_tasks import send_notification
        from app.models.notification import NotificationChannel

        exec_ = _make_execution(test_results=[_make_result("passed")])

        config = MagicMock()
        config.channel = NotificationChannel.EMAIL
        config.email_recipients = "a@test.com"
        config.trigger_events = []
        config.is_active = True
        config.id = 1

        with patch("app.tasks.notification_tasks.db") as mock_db:
            mock_db.session.get.return_value = exec_
            with patch("app.models.notification.NotificationConfig") as mock_cfg_cls:
                mock_cfg_cls.query.filter_by.return_value.all.return_value = [config]
                with patch("app.models.notification.NotificationLog") as mock_log_cls:
                    mock_log_cls.query.filter_by.return_value.first.return_value = None
                    log_instance = MagicMock()
                    mock_log_cls.return_value = log_instance
                    send_notification.run(execution_id=100)
                    # Should NOT retry -- just continue
                    mock_send_email.assert_called_once()
                    assert log_instance.status == "failed"
                    assert "bad config" in log_instance.error_msg

    def test_successful_sends_log_status_sent(self):
        """Successful notification sets log.status='sent' and log.sent_at."""
        from app.tasks.notification_tasks import send_notification
        from app.models.notification import NotificationChannel

        exec_ = _make_execution(test_results=[_make_result("passed")])

        config = MagicMock()
        config.channel = NotificationChannel.EMAIL
        config.email_recipients = "a@test.com"
        config.trigger_events = []
        config.is_active = True
        config.id = 1

        with patch("app.tasks.notification_tasks.db") as mock_db:
            mock_db.session.get.return_value = exec_
            with patch("app.models.notification.NotificationConfig") as mock_cfg_cls:
                mock_cfg_cls.query.filter_by.return_value.all.return_value = [config]
                with patch("app.models.notification.NotificationLog") as mock_log_cls:
                    mock_log_cls.query.filter_by.return_value.first.return_value = None
                    log_instance = MagicMock()
                    mock_log_cls.return_value = log_instance
                    with patch("app.notifications.services.send_email"):
                        send_notification.run(execution_id=100)
                    assert log_instance.status == "sent"
                    assert log_instance.sent_at is not None
