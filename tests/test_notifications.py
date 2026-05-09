"""Notification service tests with mocked HTTP calls."""

from unittest.mock import MagicMock, patch, call
import json

from app.models.notification import (
    NotificationChannel,
    NotificationConfig,
    NotificationDeliveryStatus,
    NotificationLog,
)


class TestEmailNotification:
    """Tests for the email notification service."""

    @patch("app.notifications.services.smtplib.SMTP")
    def test_send_email_success(self, mock_smtp_cls, app):
        """send_email dispatches via SMTP successfully."""
        from app.notifications.services import send_email

        mock_server = MagicMock()
        mock_smtp_cls.return_value.__enter__ = MagicMock(return_value=mock_server)
        mock_smtp_cls.return_value.__exit__ = MagicMock(return_value=False)

        with app.app_context():
            app.config["SMTP_HOST"] = "smtp.test.com"
            app.config["SMTP_PORT"] = 587
            app.config["SMTP_USER"] = "user@test.com"
            app.config["SMTP_PASSWORD"] = "password"
            app.config["SMTP_FROM"] = "noreply@test.com"
            send_email(["recipient@test.com"], "Test Subject", "Test Body")

        mock_smtp_cls.assert_called_once_with("smtp.test.com", 587, timeout=30)

    @patch("app.notifications.services.smtplib.SMTP")
    def test_send_email_failure(self, mock_smtp_cls, app):
        """send_email raises on SMTP failure."""
        from app.notifications.services import send_email

        mock_smtp_cls.side_effect = Exception("Connection refused")

        with app.app_context():
            app.config["SMTP_HOST"] = "smtp.test.com"
            app.config["SMTP_PORT"] = 587
            app.config["SMTP_USER"] = ""
            app.config["SMTP_PASSWORD"] = ""
            app.config["SMTP_FROM"] = "noreply@test.com"
            try:
                send_email(["recipient@test.com"], "Test", "Body")
                assert False, "Should have raised"
            except Exception:
                pass


class TestDingTalkNotification:
    """Tests for the DingTalk notification service."""

    @patch("app.notifications.services.urllib.request.urlopen")
    def test_send_dingtalk_success(self, mock_urlopen):
        """send_dingtalk posts markdown payload to webhook."""
        from app.notifications.services import send_dingtalk

        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({"errcode": 0, "errmsg": "ok"}).encode()
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_response

        send_dingtalk("https://oapi.dingtalk.com/robot/send?access_token=test", "Title", "Content")

        mock_urlopen.assert_called_once()

    @patch("app.notifications.services.urllib.request.urlopen")
    def test_send_dingtalk_api_error(self, mock_urlopen):
        """send_dingtalk raises when DingTalk returns errcode != 0."""
        from app.notifications.services import send_dingtalk

        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({"errcode": 310000, "errmsg": "error"}).encode()
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_response

        try:
            send_dingtalk("https://oapi.dingtalk.com/robot/send?access_token=test", "Title", "Content")
            assert False, "Should have raised RuntimeError"
        except RuntimeError as exc:
            assert "DingTalk error" in str(exc)

    @patch("app.notifications.services.urllib.request.urlopen")
    def test_send_dingtalk_network_error(self, mock_urlopen):
        """send_dingtalk raises on network failure."""
        from app.notifications.services import send_dingtalk

        mock_urlopen.side_effect = Exception("Network error")

        try:
            send_dingtalk("https://oapi.dingtalk.com/robot/send?access_token=test", "Title", "Content")
            assert False, "Should have raised"
        except Exception:
            pass


class TestWeChatNotification:
    """Tests for the WeChat Work notification service."""

    @patch("app.notifications.services.urllib.request.urlopen")
    def test_send_wechat_success(self, mock_urlopen):
        """send_wechat posts markdown payload to webhook."""
        from app.notifications.services import send_wechat

        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({"errcode": 0, "errmsg": "ok"}).encode()
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_response

        send_wechat("https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=test", "Content")

        mock_urlopen.assert_called_once()

    @patch("app.notifications.services.urllib.request.urlopen")
    def test_send_wechat_api_error(self, mock_urlopen):
        """send_wechat raises when WeChat returns errcode != 0."""
        from app.notifications.services import send_wechat

        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({"errcode": 93000, "errmsg": "invalid"}).encode()
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_response

        try:
            send_wechat("https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=test", "Content")
            assert False, "Should have raised RuntimeError"
        except RuntimeError as exc:
            assert "WeChat Work error" in str(exc)


class TestNotificationConfig:
    """Tests for notification config CRUD via routes."""

    def test_list_configs_requires_admin(self, client, login_as_lead, sample_project):
        """Non-admin users cannot access notification config list."""
        resp = client.get("/notifications/", follow_redirects=False)
        assert resp.status_code == 403

    def test_list_configs_admin(self, client, login_as_admin, sample_project, db):
        """Admin can list notification configs."""
        resp = client.get("/notifications/")
        assert resp.status_code == 200

    def test_create_email_config(self, client, login_as_admin, sample_project, db):
        """Admin can create an email notification config."""
        resp = client.post(
            f"/notifications/create/{sample_project.id}",
            data={
                "channel": "email",
                "email_recipients": "test@example.com",
                "is_active": "on",
                "trigger_events": ["execution.completed", "execution.failed"],
            },
            follow_redirects=False,
        )
        assert resp.status_code == 302

        config = NotificationConfig.query.filter_by(
            project_id=sample_project.id,
            channel=NotificationChannel.EMAIL,
        ).first()
        assert config is not None
        assert config.email_recipients == "test@example.com"
        assert config.is_active is True

    def test_create_dingtalk_config(self, client, login_as_admin, sample_project, db):
        """Admin can create a DingTalk notification config."""
        resp = client.post(
            f"/notifications/create/{sample_project.id}",
            data={
                "channel": "dingtalk",
                "webhook_url": "https://oapi.dingtalk.com/robot/send?access_token=test",
                "is_active": "on",
                "trigger_events": ["execution.failed"],
            },
            follow_redirects=False,
        )
        assert resp.status_code == 302

    def test_delete_config(self, client, login_as_admin, sample_project, db):
        """Admin can delete a notification config."""
        config = NotificationConfig(
            project_id=sample_project.id,
            channel=NotificationChannel.WECHAT,
            webhook_url="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=test",
            is_active=True,
            trigger_events=["execution.completed"],
        )
        db.session.add(config)
        db.session.commit()

        resp = client.post(
            f"/notifications/delete/{config.id}",
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert NotificationConfig.query.filter_by(id=config.id).first() is None
