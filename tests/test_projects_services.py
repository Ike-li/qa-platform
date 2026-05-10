"""Tests for project services: clone_repo, pull_repo, discover_suites, _run_git, _classify_suite."""

from subprocess import CompletedProcess
from unittest.mock import patch

import pytest

from app.models.test_suite import TestType


# ---------------------------------------------------------------------------
# _run_git tests
# ---------------------------------------------------------------------------


class TestRunGit:
    """Tests for the internal _run_git helper."""

    @patch("app.projects.services.subprocess.run")
    def test_run_git_success(self, mock_run, app):
        from app.projects.services import _run_git

        mock_run.return_value = CompletedProcess(
            args=["git", "status"], returncode=0, stdout="ok", stderr=""
        )
        result = _run_git(["status"], cwd="/tmp")
        assert result.returncode == 0
        assert result.stdout == "ok"
        mock_run.assert_called_once_with(
            ["git", "status"],
            capture_output=True,
            text=True,
            timeout=300,
            cwd="/tmp",
        )

    @patch("app.projects.services.subprocess.run")
    def test_run_git_failure_raises(self, mock_run, app):
        from app.projects.services import _run_git

        mock_run.return_value = CompletedProcess(
            args=["git", "clone"],
            returncode=128,
            stdout="",
            stderr="fatal: repository not found",
        )
        with pytest.raises(RuntimeError, match="git clone failed"):
            _run_git(["clone"], cwd="/tmp")

    @patch("app.projects.services.subprocess.run")
    def test_run_git_custom_timeout(self, mock_run, app):
        from app.projects.services import _run_git

        mock_run.return_value = CompletedProcess(
            args=["git", "pull"], returncode=0, stdout="ok", stderr=""
        )
        _run_git(["pull"], cwd="/tmp", timeout=60)
        mock_run.assert_called_once_with(
            ["git", "pull"],
            capture_output=True,
            text=True,
            timeout=60,
            cwd="/tmp",
        )

    @patch("app.projects.services.subprocess.run")
    def test_run_git_error_includes_stderr(self, mock_run, app):
        from app.projects.services import _run_git

        mock_run.return_value = CompletedProcess(
            args=["git", "push"],
            returncode=1,
            stdout="",
            stderr="permission denied",
        )
        with pytest.raises(RuntimeError, match="permission denied"):
            _run_git(["push"], cwd="/tmp")


# ---------------------------------------------------------------------------
# _classify_suite tests
# ---------------------------------------------------------------------------


class TestClassifySuite:
    """Tests for path-based suite classification."""

    def test_classify_api(self, app):
        from app.projects.services import _classify_suite

        assert _classify_suite("tests/api/test_users.py") == TestType.API

    def test_classify_ui(self, app):
        from app.projects.services import _classify_suite

        assert _classify_suite("tests/ui/test_login.py") == TestType.UI

    def test_classify_performance(self, app):
        from app.projects.services import _classify_suite

        assert _classify_suite("tests/perf/test_load.py") == TestType.PERFORMANCE

    def test_classify_unit(self, app):
        from app.projects.services import _classify_suite

        assert _classify_suite("tests/unit/test_utils.py") == TestType.UNIT

    def test_classify_fallback_unit(self, app):
        from app.projects.services import _classify_suite

        assert _classify_suite("tests/test_misc.py") == TestType.UNIT

    def test_classify_api_case_insensitive(self, app):
        from app.projects.services import _classify_suite

        assert _classify_suite("tests/API/test_api_v2.py") == TestType.API

    def test_classify_ui_in_subpath(self, app):
        from app.projects.services import _classify_suite

        assert _classify_suite("tests/integration/ui/test_dashboard.py") == TestType.UI

    def test_classify_performance_prefix(self, app):
        from app.projects.services import _classify_suite

        assert (
            _classify_suite("tests/perf_regression/test_memory.py")
            == TestType.PERFORMANCE
        )

    def test_classify_unit_explicit(self, app):
        from app.projects.services import _classify_suite

        assert _classify_suite("tests/unit/test_auth.py") == TestType.UNIT


# ---------------------------------------------------------------------------
# clone_repo tests
# ---------------------------------------------------------------------------


class TestCloneRepo:
    """Tests for clone_repo with mocked subprocess."""

    @patch("app.projects.services.os.makedirs")
    @patch("app.projects.services.shutil.rmtree")
    @patch("app.projects.services._run_git")
    def test_clone_calls_git_clone(
        self, mock_run_git, mock_rmtree, mock_makedirs, app, db, sample_project
    ):
        from app.projects.services import clone_repo

        mock_run_git.return_value = CompletedProcess(
            args=[], returncode=0, stdout="", stderr=""
        )
        result = clone_repo(sample_project)

        assert result == sample_project.repo_path
        mock_run_git.assert_called_once()
        call_args = mock_run_git.call_args
        cmd = call_args[0][0]
        assert cmd[:2] == ["clone", "--depth"]
        assert "--branch" in cmd
        assert "main" in cmd

    @patch("app.projects.services.os.makedirs")
    @patch("app.projects.services.shutil.rmtree")
    @patch("app.projects.services.os.path.exists", return_value=True)
    @patch("app.projects.services._run_git")
    def test_clone_removes_stale_dir(
        self,
        mock_run_git,
        mock_exists,
        mock_rmtree,
        mock_makedirs,
        app,
        db,
        sample_project,
    ):
        from app.projects.services import clone_repo

        mock_run_git.return_value = CompletedProcess(
            args=[], returncode=0, stdout="", stderr=""
        )
        clone_repo(sample_project)
        mock_rmtree.assert_called_once()

    @patch("app.projects.services.os.makedirs")
    @patch("app.projects.services.shutil.rmtree")
    @patch("app.projects.services._run_git")
    def test_clone_creates_parent_dir(
        self, mock_run_git, mock_rmtree, mock_makedirs, app, db, sample_project
    ):
        from app.projects.services import clone_repo

        mock_run_git.return_value = CompletedProcess(
            args=[], returncode=0, stdout="", stderr=""
        )
        clone_repo(sample_project)
        mock_makedirs.assert_called_once()

    @patch("app.projects.services.os.makedirs")
    @patch("app.projects.services.shutil.rmtree")
    @patch("app.projects.services._run_git", side_effect=RuntimeError("clone failed"))
    def test_clone_failure_propagates(
        self, mock_run_git, mock_rmtree, mock_makedirs, app, db, sample_project
    ):
        from app.projects.services import clone_repo

        with pytest.raises(RuntimeError, match="clone failed"):
            clone_repo(sample_project)

    @patch("app.projects.services.os.makedirs")
    @patch("app.projects.services.shutil.rmtree")
    @patch("app.projects.services._run_git")
    def test_clone_with_credential(
        self, mock_run_git, mock_rmtree, mock_makedirs, app, db, sample_project
    ):
        from app.projects.services import clone_repo
        from cryptography.fernet import Fernet

        valid_key = Fernet.generate_key().decode()
        app.config["FERNET_KEY"] = valid_key
        sample_project.set_credential("mytoken123")
        db.session.commit()
        mock_run_git.return_value = CompletedProcess(
            args=[], returncode=0, stdout="", stderr=""
        )
        clone_repo(sample_project)
        call_args = mock_run_git.call_args[0][0]
        assert "mytoken123" in call_args[5]


# ---------------------------------------------------------------------------
# pull_repo tests
# ---------------------------------------------------------------------------


class TestPullRepo:
    """Tests for pull_repo with mocked subprocess."""

    @patch("app.projects.services._run_git")
    def test_pull_success(self, mock_run_git, app, db, sample_project):
        from app.projects.services import pull_repo

        mock_run_git.return_value = CompletedProcess(
            args=[], returncode=0, stdout="Already up to date.\n", stderr=""
        )
        with patch("app.projects.services.os.path.isdir", return_value=True):
            result = pull_repo(sample_project)
        assert "Already up to date" in result
        assert mock_run_git.call_count == 2  # set-url + pull

    @patch("app.projects.services._run_git")
    def test_pull_no_git_dir_raises(self, mock_run_git, app, db, sample_project):
        from app.projects.services import pull_repo

        with pytest.raises(RuntimeError, match="not cloned"):
            pull_repo(sample_project)

    @patch("app.projects.services._run_git")
    def test_pull_failure_propagates(self, mock_run_git, app, db, sample_project):
        from app.projects.services import pull_repo

        mock_run_git.side_effect = [None, RuntimeError("pull failed")]
        with patch("app.projects.services.os.path.isdir", return_value=True):
            with pytest.raises(RuntimeError, match="pull failed"):
                pull_repo(sample_project)


# ---------------------------------------------------------------------------
# discover_suites tests
# ---------------------------------------------------------------------------


class TestDiscoverSuites:
    """Tests for discover_suites with real temp files."""

    def _make_project(self, db, admin_user, tmp_path):
        from app.models.project import Project

        project = Project(
            name="Discover Project",
            git_url="https://github.com/example/disc.git",
            git_branch="main",
            owner_id=admin_user.id,
        )
        db.session.add(project)
        db.session.commit()
        return project

    def test_discover_finds_test_files(self, app, db, admin_user, tmp_path):
        from app.projects.services import discover_suites

        project = self._make_project(db, admin_user, tmp_path)
        # Simulate repo_path by patching it
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "test_login.py").write_text(
            "def test_login(): pass\ndef test_logout(): pass\n"
        )
        (repo / "test_api.py").write_text("def test_get(): pass\n")

        with patch.object(
            type(project),
            "repo_path",
            new_callable=lambda: property(lambda self: str(repo)),
        ):
            suites = discover_suites(project)

        assert len(suites) == 2
        names = {s.name for s in suites}
        assert "test_login" in names
        assert "test_api" in names

    def test_discover_parses_test_functions(self, app, db, admin_user, tmp_path):
        from app.projects.services import discover_suites
        from app.models.test_case import TestCase

        project = self._make_project(db, admin_user, tmp_path)
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "test_math.py").write_text(
            "def test_add(): pass\ndef test_sub(): pass\ndef helper(): pass\n"
        )

        with patch.object(
            type(project),
            "repo_path",
            new_callable=lambda: property(lambda self: str(repo)),
        ):
            suites = discover_suites(project)

        assert len(suites) == 1
        cases = TestCase.query.filter_by(suite_id=suites[0].id).all()
        case_names = {c.name for c in cases}
        assert case_names == {"test_add", "test_sub"}

    def test_discover_skips_hidden_dirs(self, app, db, admin_user, tmp_path):
        from app.projects.services import discover_suites

        project = self._make_project(db, admin_user, tmp_path)
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "test_top.py").write_text("def test_a(): pass\n")
        hidden = repo / ".venv"
        hidden.mkdir()
        (hidden / "test_venv.py").write_text("def test_x(): pass\n")

        with patch.object(
            type(project),
            "repo_path",
            new_callable=lambda: property(lambda self: str(repo)),
        ):
            suites = discover_suites(project)

        assert len(suites) == 1
        assert suites[0].name == "test_top"

    def test_discover_no_test_files(self, app, db, admin_user, tmp_path):
        from app.projects.services import discover_suites

        project = self._make_project(db, admin_user, tmp_path)
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "readme.md").write_text("# Hello\n")

        with patch.object(
            type(project),
            "repo_path",
            new_callable=lambda: property(lambda self: str(repo)),
        ):
            suites = discover_suites(project)

        assert suites == []

    def test_discover_nonexistent_dir_raises(self, app, db, admin_user, tmp_path):
        from app.projects.services import discover_suites

        project = self._make_project(db, admin_user, tmp_path)

        with patch.object(
            type(project),
            "repo_path",
            new_callable=lambda: property(lambda self: "/nonexistent/path"),
        ):
            with pytest.raises(RuntimeError, match="does not exist"):
                discover_suites(project)

    def test_discover_clears_old_suites(self, app, db, admin_user, tmp_path):
        from app.projects.services import discover_suites
        from app.models.test_suite import TestSuite

        project = self._make_project(db, admin_user, tmp_path)
        old_suite = TestSuite(
            project_id=project.id,
            name="old_suite",
            path_in_repo="old_suite.py",
            test_type=TestType.UNIT,
        )
        db.session.add(old_suite)
        db.session.commit()

        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "test_new.py").write_text("def test_new(): pass\n")

        with patch.object(
            type(project),
            "repo_path",
            new_callable=lambda: property(lambda self: str(repo)),
        ):
            discover_suites(project)

        all_suites = TestSuite.query.filter_by(project_id=project.id).all()
        assert len(all_suites) == 1
        assert all_suites[0].name == "test_new"

    def test_discover_classifies_api_suite(self, app, db, admin_user, tmp_path):
        from app.projects.services import discover_suites

        project = self._make_project(db, admin_user, tmp_path)
        repo = tmp_path / "repo"
        api_dir = repo / "api"
        api_dir.mkdir(parents=True)
        (api_dir / "test_users_api.py").write_text("def test_list(): pass\n")

        with patch.object(
            type(project),
            "repo_path",
            new_callable=lambda: property(lambda self: str(repo)),
        ):
            suites = discover_suites(project)

        assert len(suites) == 1
        assert suites[0].test_type == TestType.API

    def test_discover_classifies_ui_suite(self, app, db, admin_user, tmp_path):
        from app.projects.services import discover_suites

        project = self._make_project(db, admin_user, tmp_path)
        repo = tmp_path / "repo"
        ui_dir = repo / "ui"
        ui_dir.mkdir(parents=True)
        (ui_dir / "test_dashboard.py").write_text("def test_render(): pass\n")

        with patch.object(
            type(project),
            "repo_path",
            new_callable=lambda: property(lambda self: str(repo)),
        ):
            suites = discover_suites(project)

        assert suites[0].test_type == TestType.UI

    def test_discover_nested_test_files(self, app, db, admin_user, tmp_path):
        from app.projects.services import discover_suites

        project = self._make_project(db, admin_user, tmp_path)
        repo = tmp_path / "repo"
        nested = repo / "tests" / "integration"
        nested.mkdir(parents=True)
        (nested / "test_end_to_end.py").write_text("def test_flow(): pass\n")

        with patch.object(
            type(project),
            "repo_path",
            new_callable=lambda: property(lambda self: str(repo)),
        ):
            suites = discover_suites(project)

        assert len(suites) == 1
        assert "tests/integration" in suites[0].path_in_repo
