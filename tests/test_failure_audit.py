"""Failure-audit tests: classify failures from real error surfaces."""

import json
import runpy
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

SCRIPT = PROJECT_ROOT / "scripts" / "audit-failures.py"


def _auditor():
    return runpy.run_path(str(SCRIPT))


def test_incorrect_streaks_are_not_capacity_events(tmp_path):
    audit_cell = _auditor()["audit_cell"]

    cell = tmp_path / "cell"
    for i in range(5):
        d = cell / f"t{i}" / "trial-1"
        d.mkdir(parents=True)
        (d / "manifest.json").write_text(
            json.dumps({"error": None, "run_end_time": f"2026-08-16T10:0{i}:00+00:00"})
        )
        (d / "verdict.json").write_text(
            json.dumps({"passed": False, "failure_class": "incorrect"})
        )

    audit = audit_cell(cell)

    assert audit["failures"] == {"incorrect": 5}
    assert audit["capacity_events"] == []


def test_audit_cell_flags_consecutive_failure_streaks_as_capacity_events(tmp_path):
    audit_cell = _auditor()["audit_cell"]

    cell = tmp_path / "cell"
    # Four consecutive usage-limit failures in time order, then a pass,
    # then a scattered ordinary incorrect.
    sequence = [
        ("t1", "usage", "2026-08-16T09:26:00+00:00", False),
        ("t2", "usage", "2026-08-16T09:28:00+00:00", False),
        ("t3", "usage", "2026-08-16T09:30:00+00:00", False),
        ("t4", "usage", "2026-08-16T09:32:00+00:00", False),
        ("t5", None, "2026-08-16T09:34:00+00:00", True),
        ("t6", "plain", "2026-08-16T09:36:00+00:00", False),
    ]
    for task, kind, when, passed in sequence:
        d = cell / task / "trial-1"
        d.mkdir(parents=True)
        error = (
            "Codex error: The usage limit has been reached"
            if kind == "usage"
            else None
        )
        (d / "manifest.json").write_text(
            json.dumps({"error": error, "run_end_time": when})
        )
        verdict = {"passed": passed}
        if not passed and kind == "plain":
            verdict["failure_class"] = "incorrect"
        (d / "verdict.json").write_text(json.dumps(verdict))

    audit = audit_cell(cell)

    assert audit["capacity_events"] == [
        {
            "classification": "usage_limit",
            "streak": 4,
            "first": "2026-08-16T09:26:00+00:00",
            "last": "2026-08-16T09:32:00+00:00",
        }
    ]
    # A single scattered incorrect is not a capacity event.
    assert audit["failures"].get("incorrect", 0) == 1


def test_audit_cell_reports_taxonomy_and_trace_evidence(tmp_path):
    audit_cell = _auditor()["audit_cell"]

    cell = tmp_path / "cell"
    # A passing trial with a real trace.
    ok_dir = cell / "task-a" / "trial-1"
    ok_dir.mkdir(parents=True)
    (ok_dir / "manifest.json").write_text(json.dumps({"error": None}))
    (ok_dir / "verdict.json").write_text(json.dumps({"passed": True}))
    (ok_dir / "out").mkdir()
    (ok_dir / "out" / "pi_session.jsonl").write_text("{}\n{}\n{}\n")

    # A usage-limit failure with a short trace (died instantly).
    bad_dir = cell / "task-b" / "trial-1"
    bad_dir.mkdir(parents=True)
    (bad_dir / "manifest.json").write_text(
        json.dumps({"error": "Codex error: The usage limit has been reached"})
    )
    (bad_dir / "verdict.json").write_text(
        json.dumps({"passed": False, "grader_output": "x"})
    )
    (bad_dir / "out").mkdir()
    (bad_dir / "out" / "pi_session.jsonl").write_text("{}\n")

    audit = audit_cell(cell)

    assert audit["trials"] == 2
    assert audit["passed"] == 1
    assert audit["failures"] == {"usage_limit": 1}
    failed = audit["failed_tasks"][0]
    assert failed["task"] == "task-b"
    assert failed["classification"] == "usage_limit"
    assert failed["trace_entries"] == 1
    assert audit["instant_death_failures"] == 1  # trace <= 2 entries
