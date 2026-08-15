#!/usr/bin/env python3
"""Freeze the outcome-blind 32-task Pareto stability sentinel."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_PATH = ROOT / "configs" / "pareto_stability32_v1.json"
SEED = "cospa-pareto-stability32-v1"

SOURCE_PATHS = {
    "bigcodebench_hard_agentic_pareto60": (
        ROOT / "configs" / "bigcodebench_hard_agentic_pareto60.json"
    ),
    "multi_swe_bench_flash_hermetic25": (
        ROOT / "configs" / "multi_swe_bench_flash_hermetic25.json"
    ),
    "terminal_bench_core_pareto20": (
        ROOT / "configs" / "terminal_bench_core_pareto20_v1.json"
    ),
    "swe_polybench_verified_balanced64": (
        ROOT / "configs" / "swe_polybench_verified_balanced64_v1.json"
    ),
    "featurebench_lite_pareto12": (
        ROOT / "configs" / "featurebench_lite_pareto12_v1.json"
    ),
}
MULTI_SOURCE_PATH = ROOT / "configs" / "ornith_runtime_pilot_v1.json"


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _rank(suite: str, task_id: str) -> str:
    return hashlib.sha256(f"{SEED}:{suite}:{task_id}".encode()).hexdigest()


def _ranked(suite: str, tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(tasks, key=lambda task: (_rank(suite, task["task_id"]), task["task_id"]))


def _panel(
    suite: str,
    source_path: Path,
    policy: str,
    tasks: list[dict[str, Any]],
) -> dict[str, Any]:
    selected = [
        {**task, "selection_hash": _rank(suite, task["task_id"])} for task in tasks
    ]
    return {
        "allocation": len(selected),
        "source_manifest": str(source_path.relative_to(ROOT)),
        "source_manifest_sha256": _sha256_file(source_path),
        "selection_policy": policy,
        "task_ids": [task["task_id"] for task in selected],
        "tasks": selected,
    }


def _select_bcb() -> dict[str, Any]:
    suite = "bigcodebench_hard_agentic_pareto60"
    path = SOURCE_PATHS[suite]
    source = json.loads(path.read_text())
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for task in source["tasks"]:
        groups[(task["library_count_bucket"], task["prompt_size_tertile"])].append(
            task
        )
    selected = []
    for stratum in sorted(groups):
        task = _ranked(suite, groups[stratum])[0]
        selected.append(
            {
                "task_id": task["task_id"],
                "library_count_bucket": task["library_count_bucket"],
                "prompt_size_tertile": task["prompt_size_tertile"],
            }
        )
    if len(selected) != 8:
        raise ValueError(f"Expected eight non-empty BCB strata, found {len(selected)}")
    return _panel(
        suite,
        path,
        "Take the minimum seeded SHA-256 rank in every non-empty library-count by prompt-size stratum.",
        selected,
    )


def _select_multi() -> dict[str, Any]:
    suite = "multi_swe_bench_flash_hermetic25"
    path = SOURCE_PATHS[suite]
    source = json.loads(path.read_text())
    retained = {task["task_id"] for task in source["tasks"]}
    pilot = json.loads(MULTI_SOURCE_PATH.read_text())["suites"][
        "multi_swe_bench_flash"
    ]["tasks"]
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for task in pilot:
        if task["id"] in retained:
            groups[task["language"]].append(
                {
                    "task_id": task["id"],
                    "language": task["language"],
                    "repository": task["repository"],
                }
            )
    selected = [_ranked(suite, groups[language])[0] for language in sorted(groups)]
    if len(selected) != 7:
        raise ValueError(f"Expected seven Multi-SWE languages, found {len(selected)}")
    return _panel(
        suite,
        path,
        "Take the minimum seeded SHA-256 rank independently in each retained language.",
        selected,
    )


def _select_terminal() -> dict[str, Any]:
    suite = "terminal_bench_core_pareto20"
    path = SOURCE_PATHS[suite]
    source = json.loads(path.read_text())
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for task in source["tasks"]:
        groups[task["difficulty"]].append(task)
    quotas = {"easy": 2, "medium": 2, "hard": 1}
    selected = []
    used_categories: set[str] = set()
    for difficulty in ("easy", "medium", "hard"):
        candidates = _ranked(suite, groups[difficulty])
        for _ in range(quotas[difficulty]):
            candidate = next(
                (
                    task
                    for task in candidates
                    if task["category"] not in used_categories
                ),
                candidates[0],
            )
            candidates.remove(candidate)
            used_categories.add(candidate["category"])
            selected.append(
                {
                    "task_id": candidate["task_id"],
                    "category": candidate["category"],
                    "difficulty": candidate["difficulty"],
                    "runtime_bucket": candidate["runtime_bucket"],
                }
            )
    if len(used_categories) != 5:
        raise ValueError("Terminal stability selection did not preserve five categories")
    return _panel(
        suite,
        path,
        "Allocate 2 easy, 2 medium, and 1 hard task by seeded SHA-256 while requiring five distinct categories.",
        selected,
    )


def _select_polybench() -> dict[str, Any]:
    suite = "swe_polybench_verified_balanced64"
    path = SOURCE_PATHS[suite]
    source = json.loads(path.read_text())
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for task in source["tasks"]:
        groups[task["language"]].append(task)
    selected = []
    for language in sorted(groups):
        candidates = _ranked(suite, groups[language])
        first = candidates[0]
        second = next(
            (
                task
                for task in candidates[1:]
                if task["task_type"] != first["task_type"]
                and task["repository"] != first["repository"]
            ),
            None,
        )
        if second is None:
            second = next(
                task
                for task in candidates[1:]
                if task["task_type"] != first["task_type"]
            )
        for task in (first, second):
            selected.append(
                {
                    "task_id": task["task_id"],
                    "language": task["language"],
                    "repository": task["repository"],
                    "task_type": task["task_type"],
                    "patch_size_tertile": task["patch_size_tertile"],
                }
            )
    return _panel(
        suite,
        path,
        "Take two seeded tasks per language with distinct task types and, when available, distinct repositories.",
        selected,
    )


def _select_featurebench() -> dict[str, Any]:
    suite = "featurebench_lite_pareto12"
    path = SOURCE_PATHS[suite]
    source = json.loads(path.read_text())
    selected = []
    repositories: set[str] = set()
    for task in _ranked(suite, source["tasks"]):
        if task["repository"] in repositories:
            continue
        repositories.add(task["repository"])
        selected.append(
            {
                "task_id": task["task_id"],
                "repository": task["repository"],
                "level": task["level"],
            }
        )
        if len(selected) == 4:
            break
    return _panel(
        suite,
        path,
        "Take the first four seeded SHA-256 ranks with distinct repositories.",
        selected,
    )


def build_manifest() -> dict[str, Any]:
    suites = {
        "bigcodebench_hard_agentic_pareto60": _select_bcb(),
        "multi_swe_bench_flash_hermetic25": _select_multi(),
        "terminal_bench_core_pareto20": _select_terminal(),
        "swe_polybench_verified_balanced64": _select_polybench(),
        "featurebench_lite_pareto12": _select_featurebench(),
    }
    if sum(panel["allocation"] for panel in suites.values()) != 32:
        raise ValueError("Pareto stability sentinel must contain exactly 32 tasks")
    return {
        "name": "pareto-stability32-v1",
        "version": "2026-08-16",
        "selection": {
            "seed": SEED,
            "uses_target_model_outcomes": False,
            "uses_baseline_outcomes": False,
            "policy": (
                "Select only from mechanically qualified fixed panels using "
                "seeded SHA-256 ranks and predeclared suite/stratum allocations."
            ),
            "task_count": 32,
        },
        "execution": {
            "model": "local/deepseek-v4-flash-0731",
            "adapter": "pi_vanilla",
            "thinking": "high",
            "concurrency": 8,
        },
        "protocol": {
            "independent_trials_per_task": 3,
            "report_best_of_k": False,
            "primary_stability_metrics": [
                "mean_pass_probability",
                "outcome_flip_rate",
            ],
            "suite_scores_remain_separate": True,
        },
        "suites": suites,
    }


def main() -> int:
    manifest = build_manifest()
    OUTPUT_PATH.write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"wrote 32 tasks to {OUTPUT_PATH.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
