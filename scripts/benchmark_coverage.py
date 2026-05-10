#!/usr/bin/env python3
"""Benchmark script for measuring test coverage of the QA platform.

Runs pytest with coverage on app/ and produces a deterministic JSON score.
Coverage is the average of line coverage and branch coverage percentages.

Exit 0 on success, non-zero on error.
Last line of stdout is JSON: {"primary": <score>, "sub_scores": {...}}
"""

import json
import os
import subprocess
import sys
import tempfile

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Required env vars for the Flask app to load in testing mode
ENV = os.environ.copy()
ENV.update(
    {
        "FLASK_ENV": "testing",
        "DATABASE_URL": "sqlite:///:memory:",
        "TEST_DATABASE_URL": "sqlite:///:memory:",
        "CELERY_BROKER_URL": "redis://localhost:6379/15",
        "CELERY_RESULT_BACKEND": "redis://localhost:6379/15",
        "SECRET_KEY": "test-secret-key-for-benchmark",
        "FERNET_KEY": "ZmVybmV0LXRlc3Qta2V5LTMyY2hhcnMhISE=",
    }
)


def run_benchmark():
    """Run pytest with coverage and return parsed results."""
    # Write coverage JSON to a temp file for reliable parsing
    cov_json = os.path.join(tempfile.gettempdir(), "benchmark_coverage.json")

    cmd = [
        sys.executable,
        "-m",
        "pytest",
        "tests/",
        "--cov=app",
        "--cov-branch",
        f"--cov-report=json:{cov_json}",
        "--cov-report=term-missing",
        "--no-header",
        "-q",
        "--tb=no",
        "--disable-warnings",
        "-x",  # fail fast for deterministic runs
    ]

    result = subprocess.run(
        cmd,
        cwd=REPO_ROOT,
        env=ENV,
        capture_output=True,
        text=True,
        timeout=300,
    )

    if result.returncode != 0:
        print(f"ERROR: pytest exited with code {result.returncode}", file=sys.stderr)
        if result.stderr:
            print(result.stderr, file=sys.stderr)
        sys.exit(1)

    # Parse coverage JSON
    if not os.path.exists(cov_json):
        print("ERROR: coverage JSON file not found", file=sys.stderr)
        sys.exit(1)

    with open(cov_json, "r") as f:
        cov_data = json.load(f)

    # Extract totals
    totals = cov_data.get("totals", {})
    line_pct = totals.get("percent_covered", 0.0)
    _branch_pct_display = totals.get("percent_covered_display", "0")
    # Branch coverage: compute from branch_totals if available
    # In pytest-cov JSON, totals includes branch stats when --cov-branch is used
    num_branches = totals.get("num_branches", 0)
    covered_branches = totals.get("covered_branches", 0)
    if num_branches > 0:
        branch_coverage_pct = (covered_branches / num_branches) * 100
    else:
        branch_coverage_pct = 0.0

    # Primary score: average of line and branch coverage
    primary_score = round((line_pct + branch_coverage_pct) / 2, 2)

    # Per-module scores
    files = cov_data.get("files", {})
    module_scores = {}
    for filepath, file_data in files.items():
        # Extract module name from path (e.g., app/auth/routes.py -> auth)
        parts = filepath.replace(os.sep, "/").split("/")
        if len(parts) >= 2 and parts[0] == "app":
            module = parts[1]
        else:
            module = "other"

        f_summary = file_data.get("summary", {})
        _f_line_pct = f_summary.get("percent_covered", 0.0)

        f_totals = file_data.get("summary", {})
        # Use the file-level percent_covered directly
        if module not in module_scores:
            module_scores[module] = {"lines_total": 0, "lines_covered": 0}
        # We'll compute weighted average from totals
        module_scores[module]["lines_total"] += f_totals.get(
            "num_statements", 0
        ) + f_totals.get("missing_lines", 0)
        module_scores[module]["lines_covered"] += f_totals.get("covered_lines", 0)

    # Compute per-module percentages
    module_pcts = {}
    for mod, data in module_scores.items():
        if data["lines_total"] > 0:
            module_pcts[mod] = round(
                (data["lines_covered"] / data["lines_total"]) * 100, 2
            )
        else:
            module_pcts[mod] = 0.0

    score = {
        "primary": primary_score,
        "sub_scores": {
            "line_coverage": round(line_pct, 2),
            "branch_coverage": round(branch_coverage_pct, 2),
            "num_tests": totals.get("num_statements", 0),
            **{f"module_{k}": v for k, v in sorted(module_pcts.items())},
        },
    }

    # Cleanup temp file
    try:
        os.unlink(cov_json)
    except OSError:
        pass

    # Print summary to stderr for human readability
    print(f"Line coverage:   {line_pct:.2f}%", file=sys.stderr)
    print(f"Branch coverage: {branch_coverage_pct:.2f}%", file=sys.stderr)
    print(f"Primary score:   {primary_score:.2f}%", file=sys.stderr)
    for mod, pct in sorted(module_pcts.items()):
        print(f"  {mod}: {pct:.2f}%", file=sys.stderr)

    # JSON score as last line of stdout
    print(json.dumps(score))


if __name__ == "__main__":
    run_benchmark()
