"""Git operations and test-suite discovery for projects.

Credentials are embedded in the URL and never written to logs.
"""

import ast
import logging
import os
import re
import shutil
import subprocess
from pathlib import Path

from app.extensions import db
from app.models.project import Project
from app.models.test_case import TestCase
from app.models.test_suite import TestSuite, TestType

logger = logging.getLogger(__name__)

# Patterns used during suite discovery
_TEST_FILE_RE = re.compile(r"^test_.*\.py$", re.IGNORECASE)
_SUITE_TYPE_PATTERNS: list[tuple[re.Pattern, TestType]] = [
    (re.compile(r"(?i)\bapi\b"), TestType.API),
    (re.compile(r"(?i)\bui\b"), TestType.UI),
    (re.compile(r"(?i)\bperf"), TestType.PERFORMANCE),
    (re.compile(r"(?i)\bunit\b"), TestType.UNIT),
]


# ------------------------------------------------------------------
# Internal helpers
# ------------------------------------------------------------------


from app.utils.git import build_clone_url as _build_clone_url  # noqa: E402


def _run_git(args: list[str], cwd: str, timeout: int = 300) -> subprocess.CompletedProcess:
    """Execute a git command and return the result.

    Raises ``RuntimeError`` on non-zero exit.
    """
    cmd = ["git"] + args
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=cwd,
    )
    if result.returncode != 0:
        # Do not log the full command (may contain credentials)
        raise RuntimeError(f"git {' '.join(args)} failed (rc={result.returncode}): {result.stderr[:500]}")
    return result


def _classify_suite(path_in_repo: str) -> TestType:
    """Heuristically determine the test type from the file path."""
    for pattern, test_type in _SUITE_TYPE_PATTERNS:
        if pattern.search(path_in_repo):
            return test_type
    return TestType.UNIT


def _parse_test_names(file_path: str) -> list[str]:
    """Parse a Python test file and return all ``test_*`` function names."""
    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as fh:
            source = fh.read()
        tree = ast.parse(source, filename=file_path)
    except (SyntaxError, OSError) as exc:
        logger.warning("Failed to parse %s: %s", file_path, exc)
        return []

    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
            names.append(node.name)
    return names


# ------------------------------------------------------------------
# Public API (called from routes)
# ------------------------------------------------------------------


def clone_repo(project: Project) -> str:
    """Clone the project repository with ``--depth 1 --branch``.

    Returns the local repo path.  Runs **synchronously** (suitable for
    background tasks or can be wrapped via the executor).
    """
    repo_path = project.repo_path

    # Remove stale clone if present
    if os.path.exists(repo_path):
        shutil.rmtree(repo_path, ignore_errors=True)

    os.makedirs(os.path.dirname(repo_path), exist_ok=True)

    credential = project.get_credential()
    clone_url = _build_clone_url(project.git_url, credential)

    _run_git(
        ["clone", "--depth", "1", "--branch", project.git_branch, clone_url, repo_path],
        cwd=os.path.dirname(repo_path),
    )
    return repo_path


def pull_repo(project: Project) -> str:
    """Pull latest changes for the project repository.

    Returns the git output summary.
    """
    repo_path = project.repo_path
    if not os.path.isdir(os.path.join(repo_path, ".git")):
        raise RuntimeError("Repository not cloned. Clone it first.")

    credential = project.get_credential()
    pull_url = _build_clone_url(project.git_url, credential)

    # Update remote URL (in case credential changed)
    _run_git(["remote", "set-url", "origin", pull_url], cwd=repo_path)

    result = _run_git(["pull", "--ff-only", "origin", project.git_branch], cwd=repo_path)
    return result.stdout.strip()


def discover_suites(project: Project) -> list[TestSuite]:
    """Scan the cloned repo for ``test_*.py`` files and create DB records.

    Existing suites and cases for the project are deleted before re-scanning.
    Returns the list of newly created :class:`TestSuite` objects.
    """
    repo_path = Path(project.repo_path)
    if not repo_path.is_dir():
        raise RuntimeError("Repository directory does not exist. Clone it first.")

    # Remove old discovery data
    TestCase.query.filter(
        TestCase.suite_id.in_(
            db.session.query(TestSuite.id).filter(TestSuite.project_id == project.id)
        )
    ).delete(synchronize_session="fetch")
    TestSuite.query.filter_by(project_id=project.id).delete()
    db.session.flush()

    new_suites: list[TestSuite] = []

    for py_file in sorted(repo_path.rglob("test_*.py")):
        # Skip files inside hidden directories (e.g. .venv, .git)
        rel_parts = py_file.relative_to(repo_path).parts
        if any(part.startswith(".") for part in rel_parts):
            continue

        rel_path = str(py_file.relative_to(repo_path))
        suite_name = py_file.stem  # e.g. "test_login"
        suite_type = _classify_suite(rel_path)

        suite = TestSuite(
            project_id=project.id,
            name=suite_name,
            path_in_repo=rel_path,
            test_type=suite_type,
        )
        db.session.add(suite)
        db.session.flush()  # get suite.id

        # Parse test functions
        for func_name in _parse_test_names(str(py_file)):
            case = TestCase(
                suite_id=suite.id,
                name=func_name,
                file_path=rel_path,
            )
            db.session.add(case)

        new_suites.append(suite)

    db.session.commit()
    return new_suites
