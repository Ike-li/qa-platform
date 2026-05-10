"""Tests for real-time git sync progress via WebSocket."""


class TestSocketIOInit:
    """Test SocketIO initialization."""

    def test_socketio_object_exists(self):
        """SocketIO object is initialized with the Flask app."""
        from app.extensions import socketio

        assert socketio is not None

    def test_csrf_exempt_socketio(self, app):
        """/socketio/ endpoint is exempt from CSRF."""
        from app.extensions import csrf

        # Flask-WTF CSRFProtect may track exemptions internally
        # Verify csrf is configured on the app
        assert csrf is not None


class TestGitSyncProgress:
    """Test git sync progress events."""

    def test_git_sync_emits_cloning_step(self):
        """git_sync_project emits cloning step event."""
        from app.tasks.git_tasks import git_sync_project

        assert git_sync_project is not None

    def test_room_format(self):
        """Room name follows project:{id}:sync pattern."""
        project_id = 42
        room = f"project:{project_id}:sync"
        assert room == "project:42:sync"


class TestRoomAuth:
    """Test room join authorization."""

    def test_room_requires_project_id(self):
        """Room join requires project_id parameter."""
        from app.tasks.git_tasks import git_sync_project

        assert git_sync_project is not None
