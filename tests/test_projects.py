"""Project CRUD tests with mocked Git operations."""

from unittest.mock import patch

from app.models.project import Project


class TestProjectList:
    """Tests for GET /projects/."""

    def test_list_requires_auth(self, client, db):
        """Unauthenticated users are redirected to login."""
        resp = client.get("/projects/", follow_redirects=False)
        assert resp.status_code == 302
        assert "/auth/login" in resp.headers["Location"]

    def test_list_empty(self, client, login_as_admin):
        """Empty project list returns 200."""
        resp = client.get("/projects/")
        assert resp.status_code == 200

    def test_list_shows_projects(self, client, login_as_admin, sample_project):
        """List page includes the sample project."""
        resp = client.get("/projects/")
        assert resp.status_code == 200
        assert b"Test Project" in resp.data

    def test_list_search(self, client, login_as_admin, sample_project):
        """Search filter narrows results."""
        resp = client.get("/projects/?q=Test")
        assert resp.status_code == 200
        assert b"Test Project" in resp.data

        resp = client.get("/projects/?q=nonexistent")
        assert resp.status_code == 200
        assert b"Test Project" not in resp.data


class TestProjectDetail:
    """Tests for GET /projects/<id>."""

    def test_detail_requires_auth(self, client, sample_project, db):
        """Unauthenticated users are redirected to login."""
        resp = client.get(f"/projects/{sample_project.id}", follow_redirects=False)
        assert resp.status_code == 302

    def test_detail_renders(self, client, login_as_admin, sample_project):
        """Authenticated user can view project detail."""
        resp = client.get(f"/projects/{sample_project.id}")
        assert resp.status_code == 200
        assert b"Test Project" in resp.data

    def test_detail_404(self, client, login_as_admin):
        """Nonexistent project returns 404."""
        resp = client.get("/projects/99999")
        assert resp.status_code == 404


class TestProjectCreate:
    """Tests for GET/POST /projects/create."""

    def test_create_requires_permission(self, client, login_as_visitor):
        """Visitors cannot create projects (403)."""
        resp = client.get("/projects/create", follow_redirects=False)
        assert resp.status_code == 403

    def test_create_form_renders_for_admin(self, client, login_as_admin):
        """Admin can access the create form."""
        resp = client.get("/projects/create")
        assert resp.status_code == 200

    def test_create_form_renders_for_lead(self, client, login_as_lead):
        """Project lead can access the create form."""
        resp = client.get("/projects/create")
        assert resp.status_code == 200

    def test_create_project_success(self, client, login_as_admin, db):
        """Admin can create a project."""
        resp = client.post(
            "/projects/create",
            data={
                "name": "New Project",
                "git_url": "https://github.com/example/new-repo.git",
                "git_branch": "main",
                "description": "A new test project",
            },
            follow_redirects=False,
        )
        assert resp.status_code == 302

        project = Project.query.filter_by(name="New Project").first()
        assert project is not None
        assert project.git_url == "https://github.com/example/new-repo.git"
        assert project.git_branch == "main"

    def test_create_project_missing_name(self, client, login_as_admin):
        """Creating project without name fails validation."""
        resp = client.post(
            "/projects/create",
            data={
                "name": "",
                "git_url": "https://github.com/example/new-repo.git",
                "git_branch": "main",
            },
            follow_redirects=False,
        )
        # Form validation should reject; stays on page
        assert resp.status_code == 200


class TestProjectEdit:
    """Tests for GET/POST /projects/<id>/edit."""

    def test_edit_owner_can_access(self, client, login_as_admin, sample_project):
        """Project owner can access the edit form."""
        resp = client.get(f"/projects/{sample_project.id}/edit")
        assert resp.status_code == 200

    def test_edit_save_changes(self, client, login_as_admin, sample_project, db):
        """Owner can edit and save project changes."""
        resp = client.post(
            f"/projects/{sample_project.id}/edit",
            data={
                "name": "Updated Project",
                "git_url": "https://github.com/example/updated-repo.git",
                "git_branch": "develop",
                "description": "Updated description",
            },
            follow_redirects=False,
        )
        assert resp.status_code == 302

        project = db.session.get(Project, sample_project.id)
        assert project.name == "Updated Project"
        assert project.git_branch == "develop"

    def test_edit_non_owner_visitor_forbidden(self, client, login_as_visitor, sample_project):
        """Visitors who are not owners get 403."""
        resp = client.get(f"/projects/{sample_project.id}/edit", follow_redirects=False)
        assert resp.status_code == 403


class TestProjectDelete:
    """Tests for POST /projects/<id>/delete."""

    def test_delete_requires_super_admin(self, client, login_as_lead, sample_project):
        """Project leads cannot delete projects."""
        resp = client.post(
            f"/projects/{sample_project.id}/delete",
            follow_redirects=False,
        )
        assert resp.status_code == 403

    def test_delete_as_admin(self, client, login_as_admin, sample_project, db):
        """Super admin can delete a project."""
        project_id = sample_project.id
        resp = client.post(
            f"/projects/{project_id}/delete",
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert db.session.get(Project, project_id) is None


class TestProjectGitOps:
    """Tests for clone/pull/discover endpoints (mocked Git)."""

    @patch("app.tasks.git_tasks.git_sync_project.delay")
    def test_clone_project(self, mock_delay, client, login_as_admin, sample_project):
        """Clone endpoint dispatches async Celery task."""
        resp = client.post(
            f"/projects/{sample_project.id}/clone",
            follow_redirects=False,
        )
        assert resp.status_code == 302
        mock_delay.assert_called_once_with(sample_project.id, action="clone")

    @patch("app.tasks.git_tasks.git_sync_project.delay")
    def test_pull_project(self, mock_delay, client, login_as_admin, sample_project):
        """Pull endpoint dispatches async Celery task."""
        resp = client.post(
            f"/projects/{sample_project.id}/pull",
            follow_redirects=False,
        )
        assert resp.status_code == 302
        mock_delay.assert_called_once_with(sample_project.id, action="pull")

    @patch("app.projects.routes.discover_suites", return_value=[])
    def test_discover_project(self, mock_discover, client, login_as_admin, sample_project):
        """Discover endpoint delegates to service."""
        resp = client.post(
            f"/projects/{sample_project.id}/discover",
            follow_redirects=False,
        )
        assert resp.status_code == 302
        mock_discover.assert_called_once()

    def test_clone_requires_owner_or_admin(self, client, login_as_visitor, sample_project):
        """Visitors cannot clone a project."""
        resp = client.post(
            f"/projects/{sample_project.id}/clone",
            follow_redirects=False,
        )
        assert resp.status_code == 403
