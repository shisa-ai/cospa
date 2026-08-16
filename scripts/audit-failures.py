#!/usr/bin/env python3
"""Audit result cells: classify failures from real error surfaces, detect
capacity-event streaks, and cross-check trace evidence.

Classification is defined in :mod:`harness.failure_classify`: provider/adapter
substring rules read only the manifest error surface, never the embedded
shell command or task/test output, which routinely contains words like
"usage", "forbidden" or "context" as prose. A run of three or more
consecutive infrastructure-class failures in end-time order is reported as a
capacity event (endpoint outage, account cap, image breakage) rather than
model-quality evidence.
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

from harness.failure_classify import classify_failure  # noqa: E402

CAPACITY_STREAK_THRESHOLD = 3
INSTANT_DEATH_TRACE_ENTRIES = 2
# Only infrastructure-class failures form capacity events. Ordinary
# ``incorrect`` and ``budget_exhausted`` streaks are model-capability
# evidence, not outage signal.
CAPACITY_CLASSES = frozenset(
    {
        "usage_limit",
        "auth_forbidden",
        "connection_error",
        "compose_failure",
        "http_error",
        "context_limit",
        "adapter_error_other",
        "verifier_timeout",
        "timeout_other",
    }
)


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
        in_class = classification in CAPACITY_CLASSES
        if in_class and classification == streak_class:
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
            streak_class = classification if in_class else None
            streak_count = 1 if in_class else 0
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
