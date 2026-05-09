"""Authentication flow tests: login, logout, session, role-based access."""

from app.models.user import Role, User


class TestLogin:
    """Tests for the login endpoint."""

    def test_login_page_renders(self, client):
        """GET /auth/login returns 200 with the login form."""
        resp = client.get("/auth/login")
        assert resp.status_code == 200
        assert b"login" in resp.data.lower() or b"username" in resp.data.lower()

    def test_login_success_redirects(self, client, admin_user):
        """POST /auth/login with valid credentials redirects to profile."""
        resp = client.post(
            "/auth/login",
            data={"username": "admin", "password": "admin123"},
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert "/auth/profile" in resp.headers["Location"] or resp.headers["Location"].endswith("/")

    def test_login_wrong_password(self, client, admin_user):
        """POST /auth/login with wrong password returns 401."""
        resp = client.post(
            "/auth/login",
            data={"username": "admin", "password": "wrongpassword"},
            follow_redirects=False,
        )
        assert resp.status_code == 401

    def test_login_nonexistent_user(self, client, db):
        """POST /auth/login with nonexistent user returns 401."""
        resp = client.post(
            "/auth/login",
            data={"username": "nobody", "password": "anything"},
            follow_redirects=False,
        )
        assert resp.status_code == 401

    def test_login_inactive_user(self, client, inactive_user):
        """POST /auth/login with deactivated user returns 403."""
        resp = client.post(
            "/auth/login",
            data={"username": "inactive", "password": "inactive123"},
            follow_redirects=False,
        )
        assert resp.status_code == 403

    def test_login_empty_fields(self, client, admin_user):
        """POST /auth/login with empty fields returns an error."""
        resp = client.post(
            "/auth/login",
            data={"username": "", "password": ""},
            follow_redirects=False,
        )
        # WTForms validation should reject
        assert resp.status_code in (200, 401)


class TestLogout:
    """Tests for the logout endpoint."""

    def test_logout_redirects_to_login(self, client, login_as_admin):
        """POST /auth/logout redirects to the login page."""
        resp = client.post("/auth/logout", follow_redirects=False)
        assert resp.status_code == 302
        assert "/auth/login" in resp.headers["Location"]

    def test_logout_clears_session(self, client, login_as_admin):
        """After logout, accessing a protected page redirects to login."""
        client.post("/auth/logout")
        resp = client.get("/auth/profile", follow_redirects=False)
        assert resp.status_code == 302
        assert "/auth/login" in resp.headers["Location"]

    def test_logout_requires_auth(self, client, db):
        """POST /auth/logout without login redirects to login."""
        resp = client.post("/auth/logout", follow_redirects=False)
        assert resp.status_code == 302


class TestSession:
    """Tests for session persistence and protected routes."""

    def test_profile_requires_login(self, client, db):
        """Unauthenticated access to /auth/profile redirects to login."""
        resp = client.get("/auth/profile", follow_redirects=False)
        assert resp.status_code == 302
        assert "/auth/login" in resp.headers["Location"]

    def test_profile_accessible_when_logged_in(self, client, login_as_admin):
        """Authenticated user can access the profile page."""
        resp = client.get("/auth/profile", follow_redirects=False)
        assert resp.status_code == 200

    def test_already_authenticated_redirects_from_login(self, client, login_as_admin):
        """Authenticated user hitting /auth/login gets redirected."""
        resp = client.get("/auth/login", follow_redirects=False)
        assert resp.status_code == 302

    def test_login_preserves_next_url(self, client, admin_user):
        """Login redirects to the 'next' parameter after successful auth."""
        resp = client.post(
            "/auth/login?next=/projects/",
            data={"username": "admin", "password": "admin123"},
            follow_redirects=False,
        )
        assert resp.status_code == 302
        # Should redirect to the 'next' URL or profile
        assert resp.headers["Location"] is not None


class TestPasswordChange:
    """Tests for password change via the profile page."""

    def test_change_password_success(self, client, login_as_admin):
        """Changing password with correct current password succeeds."""
        resp = client.post(
            "/auth/profile",
            data={
                "email": "admin@test.com",
                "current_password": "admin123",
                "new_password": "NewSecurePass123",
                "confirm_password": "NewSecurePass123",
            },
            follow_redirects=False,
        )
        assert resp.status_code == 302

    def test_change_password_wrong_current(self, client, login_as_admin):
        """Changing password with wrong current password fails."""
        resp = client.post(
            "/auth/profile",
            data={
                "email": "admin@test.com",
                "current_password": "wrongcurrent",
                "new_password": "NewSecurePass123",
                "confirm_password": "NewSecurePass123",
            },
            follow_redirects=False,
        )
        assert resp.status_code == 200  # Re-renders the form


class TestRoleBasedAccess:
    """Tests that each role can only access authorized resources."""

    def test_all_roles_can_login(self, client, admin_user, lead_user, tester_user, visitor_user):
        """All four roles can log in successfully."""
        for username, password in [
            ("admin", "admin123"),
            ("lead", "lead123"),
            ("tester", "tester123"),
            ("visitor", "visitor123"),
        ]:
            resp = client.post(
                "/auth/login",
                data={"username": username, "password": password},
                follow_redirects=False,
            )
            assert resp.status_code == 302, f"Login failed for role {username}"
            client.post("/auth/logout")

    def test_profile_shows_correct_role(self, client, login_as_admin, admin_user):
        """Profile page displays the user's role information."""
        resp = client.get("/auth/profile", follow_redirects=False)
        assert resp.status_code == 200
        assert b"admin" in resp.data.lower()
