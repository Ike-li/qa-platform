"""Comprehensive tests for notification route handlers.

Covers: list, create (all channels), edit, delete, test send, and edge cases.
"""

from unittest.mock import patch

import pytest

from app.models.notification import (
    NotificationChannel,
    NotificationConfig,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def email_config(db, sample_project):
    """An email notification config."""
    config = NotificationConfig(
        project_id=sample_project.id,
        channel=NotificationChannel.EMAIL,
        email_recipients="a@test.com,b@test.com",
        is_active=True,
        trigger_events=["execution.completed"],
    )
    db.session.add(config)
    db.session.commit()
    return config


@pytest.fixture()
def dingtalk_config(db, sample_project):
    """A DingTalk notification config."""
    config = NotificationConfig(
        project_id=sample_project.id,
        channel=NotificationChannel.DINGTALK,
        webhook_url="https://oapi.dingtalk.com/robot/send?access_token=tok",
        is_active=True,
        trigger_events=["execution.failed"],
    )
    db.session.add(config)
    db.session.commit()
    return config


@pytest.fixture()
def wechat_config(db, sample_project):
    """A WeChat notification config."""
    config = NotificationConfig(
        project_id=sample_project.id,
        channel=NotificationChannel.WECHAT,
        webhook_url="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=abc",
        is_active=False,
        trigger_events=["execution.completed", "execution.failed"],
    )
    db.session.add(config)
    db.session.commit()
    return config


# ---------------------------------------------------------------------------
# List route
# ---------------------------------------------------------------------------


class TestListConfigs:
    """GET /notifications/ route."""

    def test_list_requires_login(self, client, sample_project):
        resp = client.get("/notifications/", follow_redirects=False)
        assert resp.status_code == 302
        assert "/auth/login" in resp.headers["Location"]

    def test_list_forbidden_for_visitor(self, client, login_as_visitor, sample_project):
        resp = client.get("/notifications/", follow_redirects=False)
        assert resp.status_code == 403

    def test_list_forbidden_for_tester(self, client, login_as_tester, sample_project):
        resp = client.get("/notifications/", follow_redirects=False)
        assert resp.status_code == 403

    def test_list_ok_for_admin(self, client, login_as_admin, sample_project):
        resp = client.get("/notifications/")
        assert resp.status_code == 200

    def test_list_forbidden_for_lead(self, client, login_as_lead, sample_project):
        resp = client.get("/notifications/", follow_redirects=False)
        assert resp.status_code == 403

    def test_list_shows_configs(self, client, login_as_admin, email_config):
        resp = client.get("/notifications/")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Create route
# ---------------------------------------------------------------------------


class TestCreateConfig:
    """GET/POST /notifications/create/<project_id>."""

    def test_create_get_renders_form(self, client, login_as_admin, sample_project):
        resp = client.get(f"/notifications/create/{sample_project.id}")
        assert resp.status_code == 200

    def test_create_post_email(self, client, login_as_admin, sample_project, db):
        resp = client.post(
            f"/notifications/create/{sample_project.id}",
            data={
                "channel": "email",
                "email_recipients": "test@example.com",
                "is_active": "on",
                "trigger_events": ["execution.completed"],
            },
            follow_redirects=False,
        )
        assert resp.status_code == 302
        cfg = NotificationConfig.query.filter_by(
            project_id=sample_project.id,
            channel=NotificationChannel.EMAIL,
        ).first()
        assert cfg is not None
        assert cfg.email_recipients == "test@example.com"
        assert cfg.is_active is True

    def test_create_post_dingtalk(self, client, login_as_admin, sample_project, db):
        resp = client.post(
            f"/notifications/create/{sample_project.id}",
            data={
                "channel": "dingtalk",
                "webhook_url": "https://oapi.dingtalk.com/robot/send?access_token=t",
                "is_active": "on",
                "trigger_events": ["execution.failed"],
            },
            follow_redirects=False,
        )
        assert resp.status_code == 302
        cfg = NotificationConfig.query.filter_by(
            project_id=sample_project.id,
            channel=NotificationChannel.DINGTALK,
        ).first()
        assert cfg is not None

    def test_create_post_wechat(self, client, login_as_admin, sample_project, db):
        resp = client.post(
            f"/notifications/create/{sample_project.id}",
            data={
                "channel": "wechat",
                "webhook_url": "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=k",
                "is_active": "on",
                "trigger_events": ["execution.completed"],
            },
            follow_redirects=False,
        )
        assert resp.status_code == 302
        cfg = NotificationConfig.query.filter_by(
            project_id=sample_project.id,
            channel=NotificationChannel.WECHAT,
        ).first()
        assert cfg is not None
        assert (
            cfg.webhook_url == "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=k"
        )

    def test_create_post_missing_channel_redirects(
        self, client, login_as_admin, sample_project
    ):
        resp = client.post(
            f"/notifications/create/{sample_project.id}",
            data={"email_recipients": "x@y.com"},
            follow_redirects=False,
        )
        assert resp.status_code == 302

    def test_create_post_invalid_channel_redirects(
        self, client, login_as_admin, sample_project
    ):
        resp = client.post(
            f"/notifications/create/{sample_project.id}",
            data={"channel": "invalid_channel"},
            follow_redirects=False,
        )
        assert resp.status_code == 302

    def test_create_project_not_found(self, client, login_as_admin, db):
        resp = client.post(
            "/notifications/create/99999",
            data={"channel": "email", "email_recipients": "a@b.com"},
            follow_redirects=False,
        )
        assert resp.status_code == 404

    def test_create_inactive_config(self, client, login_as_admin, sample_project, db):
        resp = client.post(
            f"/notifications/create/{sample_project.id}",
            data={
                "channel": "email",
                "email_recipients": "inactive@test.com",
            },
            follow_redirects=False,
        )
        assert resp.status_code == 302
        cfg = NotificationConfig.query.filter_by(
            project_id=sample_project.id,
            channel=NotificationChannel.EMAIL,
        ).first()
        assert cfg.is_active is False


# ---------------------------------------------------------------------------
# Edit route
# ---------------------------------------------------------------------------


class TestEditConfig:
    """GET/POST /notifications/edit/<config_id>."""

    def test_edit_get_renders_form(self, client, login_as_admin, email_config):
        resp = client.get(f"/notifications/edit/{email_config.id}")
        assert resp.status_code == 200

    def test_edit_update_recipients(self, client, login_as_admin, email_config, db):
        resp = client.post(
            f"/notifications/edit/{email_config.id}",
            data={
                "email_recipients": "new@test.com",
                "is_active": "on",
                "trigger_events": ["execution.failed"],
            },
            follow_redirects=False,
        )
        assert resp.status_code == 302
        cfg = db.session.get(NotificationConfig, email_config.id)
        assert cfg.email_recipients == "new@test.com"
        assert cfg.trigger_events == ["execution.failed"]

    def test_edit_update_webhook(self, client, login_as_admin, dingtalk_config, db):
        new_url = "https://oapi.dingtalk.com/robot/send?access_token=newtok"
        resp = client.post(
            f"/notifications/edit/{dingtalk_config.id}",
            data={
                "webhook_url": new_url,
                "is_active": "on",
                "trigger_events": ["execution.completed"],
            },
            follow_redirects=False,
        )
        assert resp.status_code == 302
        cfg = db.session.get(NotificationConfig, dingtalk_config.id)
        assert cfg.webhook_url == new_url

    def test_edit_toggle_active(self, client, login_as_admin, dingtalk_config, db):
        resp = client.post(
            f"/notifications/edit/{dingtalk_config.id}",
            data={
                "webhook_url": dingtalk_config.webhook_url,
            },
            follow_redirects=False,
        )
        assert resp.status_code == 302
        cfg = db.session.get(NotificationConfig, dingtalk_config.id)
        assert cfg.is_active is False

    def test_edit_nonexistent_404(self, client, login_as_admin):
        resp = client.get("/notifications/edit/99999")
        assert resp.status_code == 404

    def test_edit_forbidden_for_tester(self, client, login_as_tester, email_config):
        resp = client.get(
            f"/notifications/edit/{email_config.id}", follow_redirects=False
        )
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Delete route
# ---------------------------------------------------------------------------


class TestDeleteConfig:
    """POST /notifications/delete/<config_id>."""

    def test_delete_removes_config(self, client, login_as_admin, email_config, db):
        cid = email_config.id
        resp = client.post(f"/notifications/delete/{cid}", follow_redirects=False)
        assert resp.status_code == 302
        assert db.session.get(NotificationConfig, cid) is None

    def test_delete_nonexistent_404(self, client, login_as_admin):
        resp = client.post("/notifications/delete/99999", follow_redirects=False)
        assert resp.status_code == 404

    def test_delete_forbidden_for_visitor(self, client, login_as_visitor, email_config):
        resp = client.post(
            f"/notifications/delete/{email_config.id}", follow_redirects=False
        )
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Test notification send route
# ---------------------------------------------------------------------------


class TestTestNotification:
    """POST /notifications/test/<config_id>."""

    @patch("app.notifications.routes.send_email")
    def test_test_email_sends(self, mock_send, client, login_as_admin, email_config):
        mock_send.return_value = None
        resp = client.post(
            f"/notifications/test/{email_config.id}", follow_redirects=False
        )
        assert resp.status_code == 302
        mock_send.assert_called_once()

    @patch("app.notifications.routes.send_dingtalk")
    def test_test_dingtalk_sends(
        self, mock_send, client, login_as_admin, dingtalk_config
    ):
        mock_send.return_value = None
        resp = client.post(
            f"/notifications/test/{dingtalk_config.id}", follow_redirects=False
        )
        assert resp.status_code == 302
        mock_send.assert_called_once()

    @patch("app.notifications.routes.send_wechat")
    def test_test_wechat_sends(self, mock_send, client, login_as_admin, wechat_config):
        mock_send.return_value = None
        resp = client.post(
            f"/notifications/test/{wechat_config.id}", follow_redirects=False
        )
        assert resp.status_code == 302
        mock_send.assert_called_once()

    @patch("app.notifications.routes.send_email")
    def test_test_email_no_recipients_warns(
        self, mock_send, client, login_as_admin, sample_project, db
    ):
        config = NotificationConfig(
            project_id=sample_project.id,
            channel=NotificationChannel.EMAIL,
            email_recipients=None,
            is_active=True,
            trigger_events=[],
        )
        db.session.add(config)
        db.session.commit()
        resp = client.post(f"/notifications/test/{config.id}", follow_redirects=False)
        assert resp.status_code == 302
        mock_send.assert_not_called()

    @patch("app.notifications.routes.send_dingtalk")
    def test_test_dingtalk_no_webhook_warns(
        self, mock_send, client, login_as_admin, sample_project, db
    ):
        config = NotificationConfig(
            project_id=sample_project.id,
            channel=NotificationChannel.DINGTALK,
            webhook_url=None,
            is_active=True,
            trigger_events=[],
        )
        db.session.add(config)
        db.session.commit()
        resp = client.post(f"/notifications/test/{config.id}", follow_redirects=False)
        assert resp.status_code == 302
        mock_send.assert_not_called()

    @patch("app.notifications.routes.send_wechat")
    def test_test_wechat_no_webhook_warns(
        self, mock_send, client, login_as_admin, sample_project, db
    ):
        config = NotificationConfig(
            project_id=sample_project.id,
            channel=NotificationChannel.WECHAT,
            webhook_url=None,
            is_active=True,
            trigger_events=[],
        )
        db.session.add(config)
        db.session.commit()
        resp = client.post(f"/notifications/test/{config.id}", follow_redirects=False)
        assert resp.status_code == 302
        mock_send.assert_not_called()

    @patch("app.notifications.routes.send_email", side_effect=Exception("SMTP down"))
    def test_test_email_failure_flash(
        self, mock_send, client, login_as_admin, email_config
    ):
        resp = client.post(
            f"/notifications/test/{email_config.id}", follow_redirects=False
        )
        assert resp.status_code == 302
        mock_send.assert_called_once()

    def test_test_nonexistent_404(self, client, login_as_admin):
        resp = client.post("/notifications/test/99999", follow_redirects=False)
        assert resp.status_code == 404

    def test_test_forbidden_for_visitor(self, client, login_as_visitor, email_config):
        resp = client.post(
            f"/notifications/test/{email_config.id}", follow_redirects=False
        )
        assert resp.status_code == 403
