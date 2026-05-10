"""Tests for app.tasks.scheduler – DatabaseScheduler Celery Beat scheduler."""

import time
from unittest.mock import MagicMock, patch


class TestDatabaseScheduler:
    """Tests for the DatabaseScheduler class."""

    def _make_scheduler(self, **kwargs):
        """Create a DatabaseScheduler with mocked Celery app."""
        from app.tasks.scheduler import DatabaseScheduler

        mock_app = MagicMock()
        mock_app.conf.beat_schedule = {}
        mock_app.conf.scheduler = "app.tasks.scheduler:DatabaseScheduler"
        sched = DatabaseScheduler(app=mock_app, **kwargs)
        return sched

    def test_setup_schedule_initializes_empty(self):
        """setup_schedule resets internal state."""
        sched = self._make_scheduler()
        sched._schedule = {"old": "data"}
        sched._last_refresh = 999.0

        with patch.object(sched, "_load_from_db"):
            sched.setup_schedule()

        assert sched._schedule == {}
        assert sched._last_refresh == 0.0

    def test_schedule_refreshes_after_interval(self):
        """schedule property refreshes from DB when interval elapsed."""
        sched = self._make_scheduler()
        sched._refresh_interval = 5
        sched._schedule = {"existing": "entry"}
        sched._last_refresh = time.time() - 10  # well past interval

        with patch.object(sched, "_load_from_db") as mock_load:
            sched._schedule = {"new": "entry"}  # simulate load
            _ = sched.schedule
            mock_load.assert_called_once()

    def test_schedule_cached_within_interval(self):
        """schedule property uses cache when interval not elapsed."""
        sched = self._make_scheduler()
        sched._refresh_interval = 60
        sched._schedule = {"cached": "entry"}
        sched._last_refresh = time.time()  # just refreshed

        with patch.object(sched, "_load_from_db") as mock_load:
            result = sched.schedule
            mock_load.assert_not_called()
            assert result == {"cached": "entry"}

    def test_load_from_db_no_flask_context(self):
        """_load_from_db gracefully handles missing Flask app context.

        Mocks current_app._get_current_object to raise RuntimeError,
        simulating the absence of a Flask app context.
        """
        sched = self._make_scheduler()
        sched._schedule = {"old": "data"}

        import flask as flask_mod
        import app.tasks.scheduler as sched_mod

        original_ca = flask_mod.current_app
        try:
            mock_proxy = MagicMock()
            mock_proxy._get_current_object.side_effect = RuntimeError(
                "Working outside of application context."
            )
            flask_mod.current_app = mock_proxy
            sched_mod.current_app = mock_proxy

            with patch("app.tasks.scheduler.time.time", return_value=1000.0):
                sched._load_from_db()
        finally:
            flask_mod.current_app = original_ca
            sched_mod.current_app = original_ca

        # Schedule unchanged since no Flask context is available
        assert sched._schedule == {"old": "data"}

    def test_load_from_db_active_schedules(self):
        """_load_from_db loads active CronSchedule entries into schedule dict."""
        sched = self._make_scheduler()

        mock_app = MagicMock()
        mock_context = MagicMock()
        mock_context.__enter__ = MagicMock(return_value=mock_app)
        mock_context.__exit__ = MagicMock(return_value=False)
        mock_app.app_context.return_value = mock_context

        s1 = MagicMock()
        s1.id = 10
        s1.celery_schedule = MagicMock()
        s2 = MagicMock()
        s2.id = 20
        s2.celery_schedule = MagicMock()

        mock_cron_cls = MagicMock()
        mock_cron_cls.query.filter_by.return_value.all.return_value = [s1, s2]

        import flask as flask_mod
        import app.tasks.scheduler as sched_mod

        original_ca = flask_mod.current_app
        try:
            # Replace current_app on the flask module so the local import
            # inside _load_from_db picks up our mock
            mock_proxy = MagicMock()
            mock_proxy._get_current_object.return_value = mock_app
            flask_mod.current_app = mock_proxy
            # Also replace on the scheduler module (in case it was already imported)
            sched_mod.current_app = mock_proxy

            with patch("app.tasks.scheduler.time.time", return_value=1000.0):
                with patch("app.models.cron_schedule.CronSchedule", mock_cron_cls):
                    sched._load_from_db()
        finally:
            flask_mod.current_app = original_ca
            sched_mod.current_app = original_ca

        assert "cron_schedule_10" in sched._schedule
        assert "cron_schedule_20" in sched._schedule
        assert sched._last_refresh == 1000.0

    def test_load_from_db_skips_invalid_cron(self):
        """_load_from_db skips entries with invalid cron expressions."""
        sched = self._make_scheduler()

        mock_app = MagicMock()
        mock_context = MagicMock()
        mock_context.__enter__ = MagicMock(return_value=mock_app)
        mock_context.__exit__ = MagicMock(return_value=False)
        mock_app.app_context.return_value = mock_context

        s1 = MagicMock()
        s1.id = 10
        s1.celery_schedule = MagicMock()
        s2 = MagicMock()
        s2.id = 20
        s2.cron_expr = "invalid"
        # Make celery_schedule raise ValueError on access
        type(s2).celery_schedule = property(
            lambda self: (_ for _ in ()).throw(ValueError("bad cron"))
        )

        mock_cron_cls = MagicMock()
        mock_cron_cls.query.filter_by.return_value.all.return_value = [s1, s2]

        import flask as flask_mod
        import app.tasks.scheduler as sched_mod

        original_ca = flask_mod.current_app
        try:
            mock_proxy = MagicMock()
            mock_proxy._get_current_object.return_value = mock_app
            flask_mod.current_app = mock_proxy
            sched_mod.current_app = mock_proxy

            with patch("app.tasks.scheduler.time.time", return_value=1000.0):
                with patch("app.models.cron_schedule.CronSchedule", mock_cron_cls):
                    sched._load_from_db()
        finally:
            flask_mod.current_app = original_ca
            sched_mod.current_app = original_ca

        assert "cron_schedule_10" in sched._schedule
        assert "cron_schedule_20" not in sched._schedule

    def test_load_from_db_exception_keeps_cached(self):
        """DB error keeps existing cached schedule unchanged."""
        sched = self._make_scheduler()
        sched._schedule = {"cached": "entry"}

        mock_app = MagicMock()
        mock_context = MagicMock()
        mock_context.__enter__ = MagicMock(return_value=mock_app)
        mock_context.__exit__ = MagicMock(return_value=False)
        mock_app.app_context.return_value = mock_context

        # Make CronSchedule.query raise to trigger the outer except block
        mock_cron_cls = MagicMock()
        type(mock_cron_cls).query = property(
            lambda self: (_ for _ in ()).throw(RuntimeError("db down"))
        )

        import flask as flask_mod
        import app.tasks.scheduler as sched_mod

        original_ca = flask_mod.current_app
        try:
            mock_proxy = MagicMock()
            mock_proxy._get_current_object.return_value = mock_app
            flask_mod.current_app = mock_proxy
            sched_mod.current_app = mock_proxy

            with patch("app.tasks.scheduler.time.time", return_value=1000.0):
                with patch("app.models.cron_schedule.CronSchedule", mock_cron_cls):
                    sched._load_from_db()
        finally:
            flask_mod.current_app = original_ca
            sched_mod.current_app = original_ca

        assert sched._schedule == {"cached": "entry"}
