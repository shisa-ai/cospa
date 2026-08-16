#!/usr/bin/env python3
"""Audit result cells: classify failures from real error surfaces, detect
capacity-event streaks, and cross-check trace evidence.

Classification reads the manifest ``error`` field or the terminal
``stdout:``/``stderr:`` segment of ``grader_output`` — never the embedded
shell command or task text, which routinely contains words like "usage" or
"context" as prose. A run of three or more consecutive same-class failures in
end-time order is reported as a capacity event (endpoint outage, account cap,
image breakage) rather than model-quality evidence.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

CAPACITY_STREAK_THRESHOLD = 3
INSTANT_DEATH_TRACE_ENTRIES = 2


def _error_surface(verdict: dict, manifest: dict) -> str:
    """Return the most specific available error text."""
    error = manifest.get("error")
    if isinstance(error, str) and error.strip():
        return error
    grader = str(verdict.get("grader_output") or "")
    if "stdout:" in grader:
        return grader.rsplit("stdout:", 1)[-1]
    if "stderr:" in grader:
        return grader.rsplit("stderr:", 1)[-1]
    return grader


def classify_failure(verdict: dict, manifest: dict) -> str:
    """Classify one failed trial from its real error surface."""
    grader = str(verdict.get("grader_output") or "")
    if verdict.get("failure_class") == "budget_exhausted" or (
        "AgentTimeoutError" in grader
    ):
        return "budget_exhausted"
    if verdict.get("verifier_failed") or "VerifierTimeoutError" in grader:
        return "verifier_timeout"
    if "Docker compose command failed" in grader:
        return "compose_failure"

    surface = _error_surface(verdict, manifest).lower()
    if "usage limit" in surface or "rate limit" in surface:
        return "usage_limit"
    if "403" in surface or "forbidden" in surface:
        return "auth_forbidden"
    if (
        "maximum context" in surface
        or "context length" in surface
        or "context window" in surface
    ):
        return "context_limit"
    if "connection error" in surface or "connection failed" in surface:
        return "connection_error"
    if "http 5" in surface or "bad gateway" in surface or "502" in surface:
        return "http_error"
    if "timed out" in surface or "timeout" in surface:
        return "timeout_other"
    if verdict.get("adapter_failed"):
        return "adapter_error_other"
    return "incorrect"


def _trace_entries(trial_dir: Path) -> int | None:
    trace = trial_dir / "out" / "pi_session.jsonl"
    if not trace.is_file():
        return None
    try:
        return sum(1 for _ in trace.open())
    except OSError:
        return None


def audit_cell(cell_dir: Path) -> dict[str, Any]:
    """Audit one suite cell directory (task/trial-N layout)."""
    cell_dir = Path(cell_dir)
    records: list[dict[str, Any]] = []
    for task_dir in sorted(cell_dir.iterdir()):
        if not task_dir.is_dir() or task_dir.name.startswith("."):
            continue
        for trial_dir in sorted(
            (
                entry
                for entry in task_dir.iterdir()
                if entry.is_dir() and entry.name.startswith("trial-")
            ),
            key=lambda entry: entry.name,
        ):
            try:
                manifest = json.loads(
                    (trial_dir / "manifest.json").read_text()
                )
                verdict = json.loads((trial_dir / "verdict.json").read_text())
            except (OSError, json.JSONDecodeError):
                continue
            records.append(
                {
                    "task": task_dir.name,
                    "trial": trial_dir.name,
                    "passed": bool(verdict.get("passed")),
                    "end": str(manifest.get("run_end_time") or ""),
                    "manifest_error": manifest.get("error"),
                    "verdict": verdict,
                    "manifest": manifest,
                    "trace_entries": _trace_entries(trial_dir),
                }
            )

    records.sort(key=lambda r: (r["end"], r["task"], r["trial"]))
    failures: Counter[str] = Counter()
    failed_tasks = []
    instant_deaths = 0
    for record in records:
        if record["passed"]:
            continue
        classification = classify_failure(
            record["verdict"], record["manifest"]
        )
        failures[classification] += 1
        failed_tasks.append(
            {
                "task": record["task"],
                "trial": record["trial"],
                "classification": classification,
                "trace_entries": record["trace_entries"],
                "end": record["end"] or None,
            }
        )
        if (
            record["trace_entries"] is not None
            and record["trace_entries"] <= INSTANT_DEATH_TRACE_ENTRIES
        ):
            instant_deaths += 1

    capacity_events = []
    streak_class = None
    streak_count = 0
    streak_first = None
    streak_last = None
    for record in records:
        if record["passed"]:
            classification = None
        else:
            classification = classify_failure(
                record["verdict"], record["manifest"]
            )
        if classification is not None and classification == streak_class:
            streak_count += 1
            streak_last = record["end"] or None
        else:
            if (
                streak_class is not None
                and streak_count >= CAPACITY_STREAK_THRESHOLD
            ):
                capacity_events.append(
                    {
                        "classification": streak_class,
                        "streak": streak_count,
                        "first": streak_first,
                        "last": streak_last,
                    }
                )
            streak_class = classification
            streak_count = 1 if classification is not None else 0
            streak_first = record["end"] or None
            streak_last = streak_first
    if streak_class is not None and streak_count >= CAPACITY_STREAK_THRESHOLD:
        capacity_events.append(
            {
                "classification": streak_class,
                "streak": streak_count,
                "first": streak_first,
                "last": streak_last,
            }
        )

    return {
        "cell": str(cell_dir),
        "trials": len(records),
        "passed": sum(1 for r in records if r["passed"]),
        "failures": dict(failures),
        "failed_tasks": failed_tasks,
        "instant_death_failures": instant_deaths,
        "capacity_events": capacity_events,
    }


def audit_results(results_dir: Path) -> dict[str, Any]:
    """Audit every model/adapter/suite cell under a results root."""
    results_dir = Path(results_dir)
    cells = {}
    for suite_dir in sorted(results_dir.glob("*/*/*")):
        if not suite_dir.is_dir():
            continue
        model, adapter, suite = (
            suite_dir.parts[-3],
            suite_dir.parts[-2],
            suite_dir.parts[-1],
        )
        cells[f"{model}/{adapter}/{suite}"] = audit_cell(suite_dir)
    return {
        "results_dir": str(results_dir),
        "cells": cells,
        "capacity_events_total": sum(
            len(cell["capacity_events"]) for cell in cells.values()
        ),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--results-dir",
        action="append",
        required=True,
        type=Path,
    )
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    reports = [audit_results(root) for root in args.results_dir]
    rendered = json.dumps(reports, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered)
    for report in reports:
        for name, cell in report["cells"].items():
            status = (
                "CAPACITY EVENT"
                if cell["capacity_events"]
                else "ok"
            )
            print(
                f"{name}: {cell['passed']}/{cell['trials']} passed, "
                f"failures={cell['failures']} {status}"
            )
            for event in cell["capacity_events"]:
                print(
                    f"  !! {event['streak']} consecutive "
                    f"{event['classification']} "
                    f"({event['first']} .. {event['last']})"
                )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
