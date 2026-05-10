"""Tests for app.tasks.sandbox – SandboxRunner and related exceptions."""

from unittest.mock import MagicMock, patch

import pytest
from docker.errors import ContainerError, DockerException, ImageNotFound


class TestSandboxConfigError:
    """Verify SandboxConfigError is a proper exception."""

    def test_is_exception(self):
        from app.tasks.sandbox import SandboxConfigError

        assert issubclass(SandboxConfigError, Exception)

    def test_message(self):
        from app.tasks.sandbox import SandboxConfigError

        exc = SandboxConfigError("bad config")
        assert str(exc) == "bad config"


class TestSandboxRuntimeError:
    """Verify SandboxRuntimeError is a proper exception."""

    def test_is_exception(self):
        from app.tasks.sandbox import SandboxRuntimeError

        assert issubclass(SandboxRuntimeError, Exception)


class TestSandboxRunnerInit:
    """Tests for SandboxRunner.__init__ and _verify_image."""

    @patch("app.tasks.sandbox.docker.from_env")
    def test_docker_unavailable_raises_runtime(self, mock_from_env):
        """DockerException during init becomes SandboxRuntimeError."""
        from app.tasks.sandbox import SandboxRunner, SandboxRuntimeError

        mock_from_env.side_effect = DockerException("no docker")
        with pytest.raises(SandboxRuntimeError, match="Cannot connect"):
            SandboxRunner("/repo", "/venv", "/results")

    @patch("app.tasks.sandbox.docker.from_env")
    def test_image_not_found_raises_config(self, mock_from_env):
        """ImageNotFound during _verify_image becomes SandboxConfigError."""
        from app.tasks.sandbox import SandboxRunner, SandboxConfigError

        mock_client = MagicMock()
        mock_client.images.get.side_effect = ImageNotFound("no image")
        mock_from_env.return_value = mock_client

        with pytest.raises(SandboxConfigError, match="not found"):
            SandboxRunner("/repo", "/venv", "/results")

    @patch("app.tasks.sandbox.docker.from_env")
    def test_successful_init(self, mock_from_env):
        """Successful init sets client and verifies image."""
        from app.tasks.sandbox import SandboxRunner, SANDBOX_IMAGE

        mock_client = MagicMock()
        mock_from_env.return_value = mock_client

        runner = SandboxRunner("/repo", "/venv", "/results")
        assert runner.repo_path == "/repo"
        assert runner.venv_path == "/venv"
        assert runner.results_dir == "/results"
        mock_client.images.get.assert_called_once_with(SANDBOX_IMAGE)


class TestRewriteCommand:
    """Tests for SandboxRunner._rewrite_command."""

    @patch("app.tasks.sandbox.docker.from_env")
    def _make_runner(self, mock_from_env):
        from app.tasks.sandbox import SandboxRunner

        mock_client = MagicMock()
        mock_from_env.return_value = mock_client
        return SandboxRunner("/host/repo", "/host/venv", "/host/results")

    @patch("app.tasks.sandbox.docker.from_env")
    def test_translates_pytest_path(self, mock_from_env):
        """First arg (pytest binary) is replaced with container python -m pytest."""
        from app.tasks.sandbox import SandboxRunner

        mock_client = MagicMock()
        mock_from_env.return_value = mock_client
        runner = SandboxRunner("/host/repo", "/host/venv", "/host/results")

        cmd = ["/host/venv/bin/pytest", "tests/test_foo.py"]
        result = runner._rewrite_command(cmd)
        assert result[0] == "/opt/venv/bin/python"
        assert result[1] == "-m"
        assert result[2] == "pytest"

    @patch("app.tasks.sandbox.docker.from_env")
    def test_translates_test_path(self, mock_from_env):
        """Repo paths are translated to /workspace prefix."""
        from app.tasks.sandbox import SandboxRunner

        mock_client = MagicMock()
        mock_from_env.return_value = mock_client
        runner = SandboxRunner("/host/repo", "/host/venv", "/host/results")

        cmd = ["/host/venv/bin/pytest", "/host/repo/tests/test_foo.py"]
        result = runner._rewrite_command(cmd)
        assert "/workspace/tests/test_foo.py" in result

    @patch("app.tasks.sandbox.docker.from_env")
    def test_translates_alluredir(self, mock_from_env):
        """--alluredir is redirected to /results/allure."""
        from app.tasks.sandbox import SandboxRunner

        mock_client = MagicMock()
        mock_from_env.return_value = mock_client
        runner = SandboxRunner("/host/repo", "/host/venv", "/host/results")

        cmd = ["/host/venv/bin/pytest", "--alluredir=/host/results/allure"]
        result = runner._rewrite_command(cmd)
        assert "--alluredir=/results/allure" in result

    @patch("app.tasks.sandbox.docker.from_env")
    def test_translates_junitxml(self, mock_from_env):
        """--junitxml is redirected to /results/junit.xml."""
        from app.tasks.sandbox import SandboxRunner

        mock_client = MagicMock()
        mock_from_env.return_value = mock_client
        runner = SandboxRunner("/host/repo", "/host/venv", "/host/results")

        cmd = ["/host/venv/bin/pytest", "--junitxml=/host/results/junit.xml"]
        result = runner._rewrite_command(cmd)
        assert "--junitxml=/results/junit.xml" in result

    @patch("app.tasks.sandbox.docker.from_env")
    def test_passthrough_other_args(self, mock_from_env):
        """Unknown args are passed through unchanged."""
        from app.tasks.sandbox import SandboxRunner

        mock_client = MagicMock()
        mock_from_env.return_value = mock_client
        runner = SandboxRunner("/host/repo", "/host/venv", "/host/results")

        cmd = ["/host/venv/bin/pytest", "-v", "--tb=short"]
        result = runner._rewrite_command(cmd)
        assert "-v" in result
        assert "--tb=short" in result


class TestSandboxRunnerRun:
    """Tests for SandboxRunner.run method."""

    @patch("app.tasks.sandbox.docker.from_env")
    def _make_runner(self, mock_from_env):
        from app.tasks.sandbox import SandboxRunner

        mock_client = MagicMock()
        mock_from_env.return_value = mock_client
        return SandboxRunner("/host/repo", "/host/venv", "/host/results"), mock_client

    def test_successful_run(self):
        """Container runs and returns exit code, stdout, stderr."""

        runner, mock_client = self._make_runner()

        mock_container = MagicMock()
        mock_container.wait.return_value = {"StatusCode": 0}
        mock_container.logs.side_effect = [
            b"test output",
            b"",
        ]
        mock_client.containers.run.return_value = mock_container

        result = runner.run(["pytest", "tests/"])
        assert result["return_code"] == 0
        assert result["stdout"] == "test output"
        assert result["stderr"] == ""

    def test_container_error_returns_exit_status(self):
        """ContainerError is caught and returned as return_code."""

        runner, mock_client = self._make_runner()
        mock_client.containers.run.side_effect = ContainerError(
            container="c1", exit_status=1, command="pytest", image="img", stderr=b"err"
        )

        result = runner.run(["pytest", "tests/"])
        assert result["return_code"] == 1

    def test_docker_exception_raises_runtime_error(self):
        """DockerException becomes SandboxRuntimeError."""
        from app.tasks.sandbox import SandboxRuntimeError

        runner, mock_client = self._make_runner()
        mock_client.containers.run.side_effect = DockerException("broken")

        with pytest.raises(SandboxRuntimeError, match="Docker runtime error"):
            runner.run(["pytest", "tests/"])

    def test_generic_exception_raises_runtime_error(self):
        """Generic exception becomes SandboxRuntimeError."""
        from app.tasks.sandbox import SandboxRuntimeError

        runner, mock_client = self._make_runner()
        mock_client.containers.run.side_effect = RuntimeError("something")

        with pytest.raises(SandboxRuntimeError, match="Sandbox execution failed"):
            runner.run(["pytest", "tests/"])

    def test_container_always_removed(self):
        """Container is removed in finally block even on success."""

        runner, mock_client = self._make_runner()
        mock_container = MagicMock()
        mock_container.wait.return_value = {"StatusCode": 0}
        mock_container.logs.side_effect = [b"ok", b""]
        mock_client.containers.run.return_value = mock_container

        runner.run(["pytest", "tests/"])
        mock_container.remove.assert_called_once_with(force=True)

    def test_container_removed_even_on_error(self):
        """Container is removed even when an exception occurs."""
        from app.tasks.sandbox import SandboxRuntimeError

        runner, mock_client = self._make_runner()
        mock_container = MagicMock()
        mock_client.containers.run.return_value = mock_container
        mock_container.wait.side_effect = DockerException("timeout")

        with pytest.raises(SandboxRuntimeError):
            runner.run(["pytest", "tests/"])
        mock_container.remove.assert_called_once_with(force=True)

    def test_cleanup_error_does_not_propagate(self):
        """Errors during container cleanup are silently logged."""

        runner, mock_client = self._make_runner()
        mock_container = MagicMock()
        mock_container.wait.return_value = {"StatusCode": 0}
        mock_container.logs.side_effect = [b"ok", b""]
        mock_container.remove.side_effect = Exception("cleanup failed")
        mock_client.containers.run.return_value = mock_container

        # Should not raise
        result = runner.run(["pytest", "tests/"])
        assert result["return_code"] == 0

    def test_stdout_truncated(self):
        """Large stdout is truncated to 50000 chars."""

        runner, mock_client = self._make_runner()
        mock_container = MagicMock()
        mock_container.wait.return_value = {"StatusCode": 0}
        big_output = b"x" * 60000
        mock_container.logs.side_effect = [big_output, b""]
        mock_client.containers.run.return_value = mock_container

        result = runner.run(["pytest", "tests/"])
        assert len(result["stdout"]) == 50000
