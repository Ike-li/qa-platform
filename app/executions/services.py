"""Execution business logic: preparation and JUnit XML parsing."""

import logging
import xml.etree.ElementTree as ET

from flask_login import current_user

from app.extensions import db
from app.models.execution import Execution, ExecutionStatus, TriggerType
from app.models.project import Project
from app.models.test_result import TestResult, TestResultStatus
from app.models.test_suite import TestSuite

logger = logging.getLogger(__name__)


def prepare_execution(
    project_id: int,
    suite_id: int | None = None,
    extra_args: str | None = None,
    trigger_type: TriggerType = TriggerType.WEB,
) -> Execution:
    """Create an :class:`Execution` row in ``PENDING`` status.

    Parameters
    ----------
    project_id:
        The project to run against.
    suite_id:
        Optional suite id. ``None`` means run all suites.
    extra_args:
        Additional pytest CLI arguments.
    trigger_type:
        How this execution was initiated.

    Returns
    -------
    Execution
        The newly created execution record (already flushed to the DB).
    """
    project = Project.query.get_or_404(project_id)

    if suite_id is not None:
        suite = TestSuite.query.filter_by(id=suite_id, project_id=project_id).first()
        if suite is None:
            raise ValueError("Suite does not belong to the specified project.")
    else:
        suite = None

    execution = Execution(
        project_id=project.id,
        suite_id=suite.id if suite else None,
        triggered_by=current_user.id if current_user.is_authenticated else None,
        trigger_type=trigger_type,
        extra_args=extra_args.strip() if extra_args else None,
        status=ExecutionStatus.PENDING,
    )
    db.session.add(execution)
    db.session.commit()

    logger.info(
        "Execution %d created for project %d, suite %s",
        execution.id,
        project.id,
        suite_id,
    )
    return execution


# ------------------------------------------------------------------
# JUnit XML parser
# ------------------------------------------------------------------

# Map JUnit XML "result" attribute to our status enum
_JUNIT_STATUS_MAP: dict[str, TestResultStatus] = {
    "passed": TestResultStatus.PASSED,
    "PASSED": TestResultStatus.PASSED,
    "failed": TestResultStatus.FAILED,
    "FAILED": TestResultStatus.FAILED,
    "error": TestResultStatus.ERROR,
    "ERROR": TestResultStatus.ERROR,
    "skipped": TestResultStatus.SKIPPED,
    "SKIPPED": TestResultStatus.SKIPPED,
}


def parse_pytest_output(execution_id: int, junit_path: str) -> list[TestResult]:
    """Parse a JUnit XML file produced by ``pytest --junitxml``.

    Creates :class:`TestResult` rows for each ``<testcase>`` element.

    Parameters
    ----------
    execution_id:
        The execution these results belong to.
    junit_path:
        Filesystem path to the JUnit XML report.

    Returns
    -------
    list[TestResult]
        The persisted result objects.
    """
    results: list[TestResult] = []

    try:
        tree = ET.parse(junit_path)
    except (ET.ParseError, FileNotFoundError, OSError) as exc:
        logger.error("Failed to parse JUnit XML at %s: %s", junit_path, exc)
        return results

    root = tree.getroot()

    # pytest may emit multiple <testsuite> elements or a single root <testsuites>
    testcase_elements = root.iter("testcase")

    for tc in testcase_elements:
        name = tc.attrib.get("name", "unknown")
        classname = tc.attrib.get("classname", "")
        file_attr = tc.attrib.get("file", classname.replace(".", "/") + ".py" if classname else None)
        time_attr = tc.attrib.get("time", "0")

        # Determine status from child elements
        if tc.find("failure") is not None:
            status = TestResultStatus.FAILED
        elif tc.find("error") is not None:
            status = TestResultStatus.ERROR
        elif tc.find("skipped") is not None:
            status = TestResultStatus.SKIPPED
        else:
            status = TestResultStatus.PASSED

        # Error details
        error_msg = None
        stacktrace = None
        failure_el = tc.find("failure")
        error_el = tc.find("error")
        detail_el = failure_el if failure_el is not None else error_el
        if detail_el is not None:
            error_msg = (detail_el.attrib.get("message") or "")[:2000]
            stacktrace = (detail_el.text or "")[:10000]

        # Skip reason
        skip_el = tc.find("skipped")
        if skip_el is not None:
            error_msg = (skip_el.attrib.get("message") or "skipped")[:2000]

        try:
            duration = float(time_attr)
        except (ValueError, TypeError):
            duration = 0.0

        result = TestResult(
            execution_id=execution_id,
            name=name,
            file_path=file_attr,
            status=status,
            duration_sec=duration,
            error_msg=error_msg,
            stacktrace=stacktrace,
        )
        db.session.add(result)
        results.append(result)

    db.session.commit()

    logger.info(
        "Parsed %d test results from %s for execution %d",
        len(results),
        junit_path,
        execution_id,
    )
    return results
