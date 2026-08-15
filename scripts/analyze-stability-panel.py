#!/usr/bin/env python3
"""Validate and summarize independent trials for the Pareto stability panel."""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from harness.path_utils import encode_model_path, encode_task_path
from harness.runner import _is_retryable_infra_failure


DEFAULT_MANIFEST = ROOT / "configs" / "pareto_stability32_v1.json"


def summarize_suite(
    task_outcomes: dict[str, list[bool]],
    *,
    expected_k: int,
) -> dict[str, Any]:
    """Return task-macro stability metrics for complete equal-k outcomes.

    A task flips when its outcomes include at least one pass and at least one
    failure. Pairwise disagreement is the fraction of within-task unordered
    trial pairs with different outcomes.
    """
    if expected_k < 2:
        raise ValueError("expected_k must be at least 2 for stability analysis")
    if not task_outcomes:
        raise ValueError("at least one task outcome is required")

    task_rows = []
    total_passes = 0
    flipped_tasks = 0
    discordant_pairs = 0
    pairs_per_task = math.comb(expected_k, 2)
    for task_id, outcomes in sorted(task_outcomes.items()):
        if len(outcomes) != expected_k:
            raise ValueError(
                f"{task_id}: expected {expected_k} outcomes, found {len(outcomes)}"
            )
        if any(not isinstance(outcome, bool) for outcome in outcomes):
            raise ValueError(f"{task_id}: outcomes must be booleans")
        passes = sum(outcomes)
        failures = expected_k - passes
        flipped = 0 < passes < expected_k
        total_passes += passes
        flipped_tasks += int(flipped)
        discordant_pairs += passes * failures
        task_rows.append(
            {
                "task_id": task_id,
                "passes": passes,
                "attempts": expected_k,
                "pass_probability": passes / expected_k,
                "flipped": flipped,
            }
        )

    task_count = len(task_rows)
    attempts = task_count * expected_k
    return {
        "tasks_count": task_count,
        "attempts": attempts,
        "passed_attempts": total_passes,
        "mean_pass_probability": statistics.fmean(
            row["pass_probability"] for row in task_rows
        ),
        "outcome_flip_tasks": flipped_tasks,
        "outcome_flip_rate": flipped_tasks / task_count,
        "pairwise_disagreement_rate": (
            discordant_pairs / (task_count * pairs_per_task)
        ),
        "unanimous_pass_tasks": sum(
            row["passes"] == expected_k for row in task_rows
        ),
        "unanimous_fail_tasks": sum(row["passes"] == 0 for row in task_rows),
        "tasks": task_rows,
    }


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object in {path}")
    return value


def _issue(
    kind: str,
    suite: str,
    task_id: str,
    trial: int,
    detail: str,
) -> dict[str, Any]:
    return {
        "kind": kind,
        "suite": suite,
        "task_id": task_id,
        "trial": trial,
        "detail": detail,
    }


def analyze_results(manifest_path: Path, results_dir: Path) -> dict[str, Any]:
    """Validate the exact panel artifacts and calculate metrics if complete."""
    manifest_path = Path(manifest_path)
    results_dir = Path(results_dir)
    panel = _read_json(manifest_path)
    execution = panel["execution"]
    expected_k = int(panel["protocol"]["independent_trials_per_task"])
    model = str(execution["model"])
    adapter = str(execution["adapter"])
    thinking = str(execution["thinking"])
    cell_root = results_dir / encode_model_path(model) / adapter

    issues: list[dict[str, Any]] = []
    suites: dict[str, dict[str, Any]] = {}
    all_outcomes: dict[str, list[bool]] = {}
    expected_attempts = 0
    authoritative_attempts = 0

    for suite, suite_panel in panel["suites"].items():
        task_ids = list(suite_panel["task_ids"])
        if len(task_ids) != len(set(task_ids)):
            raise ValueError(f"duplicate task IDs in panel suite {suite}")
        expected_attempts += len(task_ids) * expected_k
        outcomes_by_task: dict[str, list[bool]] = {task_id: [] for task_id in task_ids}
        suite_authoritative = 0

        for task_id in task_ids:
            for trial_number in range(1, expected_k + 1):
                trial_dir = (
                    cell_root
                    / suite
                    / encode_task_path(task_id)
                    / f"trial-{trial_number}"
                )
                artifact_paths = [
                    trial_dir / "manifest.json",
                    trial_dir / "verdict.json",
                ]
                missing = [path.name for path in artifact_paths if not path.is_file()]
                if missing:
                    issues.append(
                        _issue(
                            "missing_artifact",
                            suite,
                            task_id,
                            trial_number,
                            f"missing {', '.join(missing)} in {trial_dir}",
                        )
                    )
                    continue
                try:
                    trial_manifest = _read_json(artifact_paths[0])
                    verdict = _read_json(artifact_paths[1])
                except (OSError, json.JSONDecodeError, ValueError) as exc:
                    issues.append(
                        _issue(
                            "malformed_artifact",
                            suite,
                            task_id,
                            trial_number,
                            str(exc),
                        )
                    )
                    continue

                observed = {
                    "model": trial_manifest.get("model", {}).get("id"),
                    "task_id": trial_manifest.get("suite", {}).get("task_id"),
                    "trial": trial_manifest.get("trial"),
                    "thinking": trial_manifest.get("sampling", {}).get("thinking"),
                }
                expected = {
                    "model": model,
                    "task_id": task_id,
                    "trial": trial_number,
                    "thinking": thinking,
                }
                if observed != expected:
                    issues.append(
                        _issue(
                            "artifact_identity_mismatch",
                            suite,
                            task_id,
                            trial_number,
                            f"expected {expected!r}; observed {observed!r}",
                        )
                    )
                    continue
                if _is_retryable_infra_failure(trial_manifest, verdict):
                    issues.append(
                        _issue(
                            "non_authoritative_verdict",
                            suite,
                            task_id,
                            trial_number,
                            str(
                                verdict.get("failure_class")
                                or trial_manifest.get("error")
                                or "retryable infrastructure failure"
                            ),
                        )
                    )
                    continue
                if not isinstance(verdict.get("passed"), bool):
                    issues.append(
                        _issue(
                            "malformed_verdict",
                            suite,
                            task_id,
                            trial_number,
                            "verdict.passed must be boolean",
                        )
                    )
                    continue

                outcome = verdict["passed"]
                outcomes_by_task[task_id].append(outcome)
                panel_task_id = f"{suite}:{task_id}"
                all_outcomes.setdefault(panel_task_id, []).append(outcome)
                authoritative_attempts += 1
                suite_authoritative += 1

        suite_complete = all(
            len(outcomes) == expected_k for outcomes in outcomes_by_task.values()
        )
        suites[suite] = {
            "complete": suite_complete,
            "expected_tasks": len(task_ids),
            "expected_attempts": len(task_ids) * expected_k,
            "authoritative_attempts": suite_authoritative,
            "metrics": (
                summarize_suite(outcomes_by_task, expected_k=expected_k)
                if suite_complete
                else None
            ),
        }

    complete = not issues and authoritative_attempts == expected_attempts
    return {
        "panel": panel.get("name"),
        "manifest": str(manifest_path),
        "results_dir": str(results_dir),
        "model": model,
        "adapter": adapter,
        "thinking": thinking,
        "independent_trials_per_task": expected_k,
        "metric_definitions": {
            "mean_pass_probability": "task-macro mean of passes / authoritative attempts",
            "outcome_flip_rate": "fraction of tasks containing both pass and fail outcomes",
            "pairwise_disagreement_rate": "fraction of within-task unordered trial pairs with different outcomes",
            "best_of_k_reported_as_pass_at_1": False,
        },
        "complete": complete,
        "expected_attempts": expected_attempts,
        "authoritative_attempts": authoritative_attempts,
        "issues": issues,
        "suites": suites,
        "panel_stability_diagnostic": (
            {
                "not_a_capability_score": True,
                **summarize_suite(all_outcomes, expected_k=expected_k),
            }
            if complete
            else None
        ),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--results-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    analysis = analyze_results(args.manifest, args.results_dir)
    rendered = json.dumps(analysis, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered)
    print(rendered, end="")
    return 0 if analysis["complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
