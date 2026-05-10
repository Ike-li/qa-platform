"""Tests for parse_pytest_output and prepare_execution in app.executions.services."""

import xml.etree.ElementTree as ET
from unittest.mock import patch, MagicMock

import pytest

from app.executions.services import parse_pytest_output, prepare_execution
from app.models.execution import Execution, ExecutionStatus, TriggerType
from app.models.test_result import TestResultStatus
from app.models.test_suite import TestSuite


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_junit_xml(path, testcases, testsuites=None):
    """Write a valid JUnit XML file at *path*.

    Parameters
    ----------
    path : pathlib.Path
        Destination file.
    testcases : list[dict]
        Each dict has keys: name, classname, time, status, message, text.
    testsuites : list[list[dict]] | None
        If provided, each element is a list of testcases wrapped in its own
        <testsuite>.  Otherwise a single <testsuite> wraps all testcases.
    """
    root = ET.Element("testsuites")

    if testsuites is not None:
        groups = testsuites
    else:
        groups = [testcases]

    for group in groups:
        suite_el = ET.SubElement(root, "testsuite", name="suite")
        for tc in group:
            tc_el = ET.SubElement(
                suite_el,
                "testcase",
                name=tc.get("name", ""),
                classname=tc.get("classname", ""),
                time=str(tc.get("time", "0")),
            )
            status = tc.get("status")
            if status == "failed":
                failure = ET.SubElement(
                    tc_el,
                    "failure",
                    message=tc.get("message", "fail"),
                )
                failure.text = tc.get("text", "traceback")
            elif status == "error":
                error = ET.SubElement(
                    tc_el,
                    "error",
                    message=tc.get("message", "err"),
                )
                error.text = tc.get("text", "traceback")
            elif status == "skipped":
                skip_attrs = {}
                if tc.get("message"):
                    skip_attrs["message"] = tc["message"]
                ET.SubElement(tc_el, "skipped", **skip_attrs)

    tree = ET.ElementTree(root)
    tree.write(str(path), encoding="unicode")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def _execution(app, db, sample_project):
    """Create a PENDING Execution for use in parse tests."""
    execution = Execution(
        project_id=sample_project.id,
        status=ExecutionStatus.PENDING,
        trigger_type=TriggerType.WEB,
    )
    db.session.add(execution)
    db.session.commit()
    return execution


# ===========================================================================
# TestParsePytestOutput
# ===========================================================================


class TestParsePytestOutput:
    def test_file_not_found(self, app, db, _execution):
        results = parse_pytest_output(_execution.id, "/nonexistent/path.xml")
        assert results == []

    def test_invalid_xml(self, app, db, _execution, tmp_path):
        bad_file = tmp_path / "bad.xml"
        bad_file.write_text("<<<not xml>>>")
        results = parse_pytest_output(_execution.id, str(bad_file))
        assert results == []

    def test_passed_test(self, app, db, _execution, tmp_path):
        xml_file = tmp_path / "passed.xml"
        _write_junit_xml(
            xml_file,
            [
                {
                    "name": "test_ok",
                    "classname": "tests.test_foo",
                    "time": "1.23",
                    "status": "passed",
                },
            ],
        )
        results = parse_pytest_output(_execution.id, str(xml_file))
        assert len(results) == 1
        r = results[0]
        assert r.status == TestResultStatus.PASSED
        assert r.name == "test_ok"
        assert r.file_path == "tests/test_foo.py"
        assert abs(r.duration_sec - 1.23) < 0.01
        assert r.error_msg is None
        assert r.stacktrace is None

    def test_failed_test(self, app, db, _execution, tmp_path):
        xml_file = tmp_path / "failed.xml"
        _write_junit_xml(
            xml_file,
            [
                {
                    "name": "test_fail",
                    "classname": "tests.test_bar",
                    "time": "0.5",
                    "status": "failed",
                    "message": "assertion failed",
                    "text": "traceback text",
                },
            ],
        )
        results = parse_pytest_output(_execution.id, str(xml_file))
        assert len(results) == 1
        r = results[0]
        assert r.status == TestResultStatus.FAILED
        assert r.error_msg == "assertion failed"
        assert r.stacktrace == "traceback text"

    def test_error_test(self, app, db, _execution, tmp_path):
        xml_file = tmp_path / "error.xml"
        _write_junit_xml(
            xml_file,
            [
                {
                    "name": "test_err",
                    "classname": "tests.test_baz",
                    "time": "0.1",
                    "status": "error",
                    "message": "runtime error",
                    "text": "Traceback ...",
                },
            ],
        )
        results = parse_pytest_output(_execution.id, str(xml_file))
        assert len(results) == 1
        r = results[0]
        assert r.status == TestResultStatus.ERROR
        assert r.error_msg == "runtime error"
        assert r.stacktrace == "Traceback ..."

    def test_skipped_test_with_message(self, app, db, _execution, tmp_path):
        xml_file = tmp_path / "skipped.xml"
        _write_junit_xml(
            xml_file,
            [
                {
                    "name": "test_skip",
                    "classname": "tests.test_skip",
                    "time": "0",
                    "status": "skipped",
                    "message": "not applicable",
                },
            ],
        )
        results = parse_pytest_output(_execution.id, str(xml_file))
        assert len(results) == 1
        r = results[0]
        assert r.status == TestResultStatus.SKIPPED
        assert r.error_msg == "not applicable"

    def test_skipped_no_message(self, app, db, _execution, tmp_path):
        xml_file = tmp_path / "skipped_nomsg.xml"
        _write_junit_xml(
            xml_file,
            [
                {
                    "name": "test_skip2",
                    "classname": "tests.test_skip",
                    "time": "0",
                    "status": "skipped",
                },
            ],
        )
        results = parse_pytest_output(_execution.id, str(xml_file))
        assert len(results) == 1
        r = results[0]
        assert r.status == TestResultStatus.SKIPPED
        assert r.error_msg == "skipped"

    def test_missing_attributes(self, app, db, _execution, tmp_path):
        """Testcase with no name, classname, or time attributes."""
        xml_file = tmp_path / "empty.xml"
        root = ET.Element("testsuites")
        suite_el = ET.SubElement(root, "testsuite", name="s")
        ET.SubElement(suite_el, "testcase")  # no attributes at all
        tree = ET.ElementTree(root)
        tree.write(str(xml_file), encoding="unicode")

        results = parse_pytest_output(_execution.id, str(xml_file))
        assert len(results) == 1
        r = results[0]
        assert r.name == "unknown"
        assert r.file_path is None
        assert r.duration_sec == 0.0

    def test_invalid_duration(self, app, db, _execution, tmp_path):
        xml_file = tmp_path / "baddur.xml"
        _write_junit_xml(
            xml_file,
            [
                {
                    "name": "test_dur",
                    "classname": "tests.test_dur",
                    "time": "not-a-number",
                    "status": "passed",
                },
            ],
        )
        results = parse_pytest_output(_execution.id, str(xml_file))
        assert len(results) == 1
        assert results[0].duration_sec == 0.0

    def test_error_msg_truncation(self, app, db, _execution, tmp_path):
        xml_file = tmp_path / "trunc.xml"
        long_msg = "A" * 3000
        long_text = "B" * 15000
        _write_junit_xml(
            xml_file,
            [
                {
                    "name": "test_trunc",
                    "classname": "tests.test_trunc",
                    "time": "0.1",
                    "status": "failed",
                    "message": long_msg,
                    "text": long_text,
                },
            ],
        )
        results = parse_pytest_output(_execution.id, str(xml_file))
        assert len(results) == 1
        r = results[0]
        assert len(r.error_msg) == 2000
        assert len(r.stacktrace) == 10000

    def test_multiple_testsuites(self, app, db, _execution, tmp_path):
        xml_file = tmp_path / "multi.xml"
        _write_junit_xml(
            xml_file,
            [],  # testcases arg ignored when testsuites is provided
            testsuites=[
                [
                    {
                        "name": "t1",
                        "classname": "a.b",
                        "time": "0.1",
                        "status": "passed",
                    },
                ],
                [
                    {
                        "name": "t2",
                        "classname": "c.d",
                        "time": "0.2",
                        "status": "passed",
                    },
                ],
            ],
        )
        results = parse_pytest_output(_execution.id, str(xml_file))
        assert len(results) == 2
        names = {r.name for r in results}
        assert names == {"t1", "t2"}

    def test_failure_over_error_priority(self, app, db, _execution, tmp_path):
        """When a testcase has both <failure> and <error>, failure wins."""
        xml_file = tmp_path / "priority.xml"
        root = ET.Element("testsuites")
        suite_el = ET.SubElement(root, "testsuite", name="s")
        tc_el = ET.SubElement(
            suite_el, "testcase", name="test_both", classname="tests.x", time="0.1"
        )
        f = ET.SubElement(tc_el, "failure", message="fail_msg")
        f.text = "fail_tb"
        e = ET.SubElement(tc_el, "error", message="err_msg")
        e.text = "err_tb"
        tree = ET.ElementTree(root)
        tree.write(str(xml_file), encoding="unicode")

        results = parse_pytest_output(_execution.id, str(xml_file))
        assert len(results) == 1
        r = results[0]
        assert r.status == TestResultStatus.FAILED
        assert r.error_msg == "fail_msg"
        assert r.stacktrace == "fail_tb"


# ===========================================================================
# TestPrepareExecution
# ===========================================================================


class TestPrepareExecution:
    def test_prepare_with_authenticated_user(self, app, db, admin_user, sample_project):
        suite = TestSuite(
            project_id=sample_project.id,
            name="Suite A",
            path_in_repo="tests/test_a.py",
        )
        db.session.add(suite)
        db.session.commit()

        mock_user = MagicMock()
        mock_user.is_authenticated = True
        mock_user.id = admin_user.id

        with patch("app.executions.services.current_user", mock_user):
            execution = prepare_execution(sample_project.id, suite_id=suite.id)

        assert execution.project_id == sample_project.id
        assert execution.suite_id == suite.id
        assert execution.triggered_by == admin_user.id
        assert execution.status == ExecutionStatus.PENDING
        assert execution.trigger_type == TriggerType.WEB

    def test_prepare_with_anonymous_user(self, app, db, sample_project):
        mock_user = MagicMock()
        mock_user.is_authenticated = False

        with patch("app.executions.services.current_user", mock_user):
            execution = prepare_execution(sample_project.id)

        assert execution.triggered_by is None

    def test_prepare_invalid_suite(self, app, db, sample_project):
        mock_user = MagicMock()
        mock_user.is_authenticated = False

        with patch("app.executions.services.current_user", mock_user):
            with pytest.raises(ValueError, match="Suite does not belong"):
                prepare_execution(sample_project.id, suite_id=99999)

    def test_prepare_extra_args_stripped(self, app, db, sample_project):
        mock_user = MagicMock()
        mock_user.is_authenticated = False

        with patch("app.executions.services.current_user", mock_user):
            execution = prepare_execution(sample_project.id, extra_args="  -k smoke  ")

        assert execution.extra_args == "-k smoke"

    def test_prepare_no_suite(self, app, db, sample_project):
        mock_user = MagicMock()
        mock_user.is_authenticated = False

        with patch("app.executions.services.current_user", mock_user):
            execution = prepare_execution(sample_project.id)

        assert execution.suite_id is None
