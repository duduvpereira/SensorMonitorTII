"""Builds a colored Markdown job summary from pytest + coverage XML reports.

Reads the JUnit report (test-results.xml) and the Cobertura coverage report
(coverage.xml) produced by the CI workflow's test step, and renders a
GitHub-flavored Markdown summary (badge + tables) to $GITHUB_STEP_SUMMARY.
Kept as a standalone script (rather than an inline workflow step) so it is
readable and runnable locally: `python .github/scripts/build_job_summary.py`.
"""

from __future__ import annotations

import json
import os
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

TEST_RESULTS_XML = Path("test-results.xml")
COVERAGE_JSON = Path("coverage.json")


def coverage_emoji(percent: float) -> str:
    """Maps a coverage percentage to a traffic-light emoji."""
    if percent >= 80:
        return "🟢"
    if percent >= 50:
        return "🟡"
    return "🔴"


def build_test_section() -> list[str]:
    """Renders the badge + results table for the JUnit report."""
    root = ET.parse(TEST_RESULTS_XML).getroot()
    suites = root.findall("testsuite") if root.tag == "testsuites" else [root]

    total_tests = total_failures = total_errors = total_skipped = 0
    rows = []
    for suite in suites:
        tests = int(suite.get("tests", 0))
        failures = int(suite.get("failures", 0))
        errors = int(suite.get("errors", 0))
        skipped = int(suite.get("skipped", 0))
        time = float(suite.get("time", 0))
        passed = tests - failures - errors - skipped

        total_tests += tests
        total_failures += failures
        total_errors += errors
        total_skipped += skipped

        name = suite.get("name") or "pytest"
        mark = "✅" if (failures + errors) == 0 else "❌"
        rows.append(f"| {name} | {tests} | {passed} {mark} | {failures + errors} | {skipped} | {time:.2f}s |")

    failed = total_failures + total_errors
    if failed == 0:
        badge = f"https://img.shields.io/badge/tests-{total_tests}%20passed-success"
    else:
        badge = f"https://img.shields.io/badge/tests-{failed}%20failed-critical"

    return [
        "## ✅ Test Results",
        "",
        f"![Tests]({badge})",
        "",
        "| Suite | Total | Passed | Failed | Skipped | Time |",
        "|---|---|---|---|---|---|",
        *rows,
        "",
    ]


def build_coverage_section() -> list[str]:
    """Renders the overall + per-file coverage table from coverage.py's JSON report.

    Uses the JSON report (not the Cobertura XML) because coverage.py's XML
    writer keys files by basename only; with multiple `source` roots (see
    pyproject.toml), two same-named files (e.g. two `__init__.py`) collide
    and overwrite each other in the XML. The JSON report keys files by their
    full relative path, so each file gets its own row.
    """
    data = json.loads(COVERAGE_JSON.read_text(encoding="utf-8"))
    overall = data["totals"]["percent_covered"]

    files = sorted(
        (filename.replace("\\", "/"), info["summary"]["percent_covered"])
        for filename, info in data["files"].items()
    )

    lines = [
        "## 📊 Coverage",
        "",
        f"**Overall: {coverage_emoji(overall)} {overall:.1f}%**",
        "",
        "| File | Coverage |",
        "|---|---|",
    ]
    lines += [f"| `{filename}` | {coverage_emoji(pct)} {pct:.1f}% |" for filename, pct in files]
    lines.append("")
    return lines


def main() -> None:
    summary = build_test_section() + build_coverage_section()
    text = "\n".join(summary) + "\n"

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as f:
            f.write(text)
    else:
        sys.stdout.buffer.write(text.encode("utf-8"))


if __name__ == "__main__":
    main()
