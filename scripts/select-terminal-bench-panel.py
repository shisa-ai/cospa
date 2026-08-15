#!/usr/bin/env python3
"""Freeze an outcome-blind Terminal-Bench Core Pareto20 panel."""

from __future__ import annotations

import hashlib
import itertools
import json
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SOURCE_MANIFEST_PATH = ROOT / "configs" / "terminal_bench_core_0.1.1.json"
PILOT_PATH = ROOT / "configs" / "ornith_runtime_pilot_v1.json"
OUTPUT_PATH = ROOT / "configs" / "terminal_bench_core_pareto20_v1.json"
PILOT_OUTPUT_PATH = ROOT / "configs" / "terminal_bench_core_pilot8_v1.json"
PILOT_QUALIFICATION_PATH = (
    ROOT / "configs" / "terminal_bench_core_pilot8_qualification_v1.json"
)
TASKS_PATH = ROOT / "vendor" / "terminal-bench" / "tasks"
SEED = "cospa-terminal-bench-pareto20-v1"
CATEGORY_TARGETS = {
    "software-engineering": 4,
    "system-administration": 4,
    "security": 3,
    "debugging": 2,
    "file-operations": 2,
    "data-science": 2,
    "model-training": 1,
    "games": 1,
    "scientific-computing": 1,
}
DIFFICULTY_TARGETS = {"easy": 5, "medium": 9, "hard": 6}
RUNTIME_BUCKET_TARGETS = {"short": 15, "medium": 3, "long": 2}
DIFFICULTIES = tuple(DIFFICULTY_TARGETS)
RUNTIME_BUCKETS = tuple(RUNTIME_BUCKET_TARGETS)


def stable_key(task_id: str) -> str:
    return hashlib.sha256(f"{SEED}\0{task_id}".encode()).hexdigest()


def runtime_bucket(timeout_seconds: float) -> str:
    if timeout_seconds <= 360:
        return "short"
    if timeout_seconds <= 900:
        return "medium"
    return "long"


def variant_family(task_id: str) -> str:
    for suffix in (".base_with_hint", ".easy", ".hard"):
        if task_id.endswith(suffix):
            return task_id.removesuffix(suffix)
    return task_id


def load_task_metadata(task_path: Path) -> dict[str, Any]:
    """Read the scalar selection fields and simple tag list without PyYAML."""
    metadata: dict[str, Any] = {"tags": []}
    in_tags = False
    for line in task_path.read_text().splitlines():
        stripped = line.strip()
        if in_tags and stripped.startswith("- "):
            metadata["tags"].append(stripped[2:].strip().strip("'\""))
            continue
        in_tags = stripped == "tags:"
        if in_tags or not stripped or stripped.startswith("#") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        if key in {
            "category",
            "difficulty",
            "max_agent_timeout_sec",
            "max_test_timeout_sec",
        }:
            metadata[key] = value.strip().strip("'\"")
    return metadata


def load_rows() -> list[dict[str, Any]]:
    source = json.loads(SOURCE_MANIFEST_PATH.read_text())
    rows = []
    for task_id in source["task_ids"]:
        task_path = TASKS_PATH / task_id / "task.yaml"
        metadata = load_task_metadata(task_path)
        timeout_seconds = float(metadata["max_agent_timeout_sec"])
        rows.append(
            {
                "task_id": task_id,
                "category": str(metadata["category"]),
                "difficulty": str(metadata["difficulty"]),
                "max_agent_timeout_sec": timeout_seconds,
                "max_test_timeout_sec": float(metadata["max_test_timeout_sec"]),
                "runtime_bucket": runtime_bucket(timeout_seconds),
                "variant_family": variant_family(task_id),
                "tags": list(metadata.get("tags") or []),
            }
        )
    return rows


def _counts(rows: tuple[dict[str, Any], ...]) -> tuple[int, ...]:
    return tuple(
        sum(row["difficulty"] == key for row in rows)
        for key in DIFFICULTIES
    ) + tuple(
        sum(row["runtime_bucket"] == key for row in rows)
        for key in RUNTIME_BUCKETS
    )


def select_task_ids(rows: list[dict[str, Any]]) -> set[str]:
    pilot = json.loads(PILOT_PATH.read_text())["suites"][
        "terminal_bench_core_0_1_1"
    ]
    fixed_ids = {task["id"] for task in pilot["tasks"]}
    fixed = [row for row in rows if row["task_id"] in fixed_ids]
    if len(fixed) != len(fixed_ids):
        raise ValueError("Terminal-Bench pilot IDs do not match the Core source")

    difficulty_need = Counter(DIFFICULTY_TARGETS)
    runtime_need = Counter(RUNTIME_BUCKET_TARGETS)
    for row in fixed:
        difficulty_need[row["difficulty"]] -= 1
        runtime_need[row["runtime_bucket"]] -= 1
    target_state = tuple(difficulty_need[key] for key in DIFFICULTIES) + tuple(
        runtime_need[key] for key in RUNTIME_BUCKETS
    )

    # State is global difficulty/runtime additions. Category counts are exact at
    # each stage, and the stable hash tuple provides an outcome-independent
    # deterministic tie-break among all feasible panels.
    states: dict[tuple[int, ...], tuple[tuple[str, ...], frozenset[str]]] = {
        (0,) * len(target_state): ((), frozenset())
    }
    for category, target in CATEGORY_TARGETS.items():
        have = sum(row["category"] == category for row in fixed)
        need = target - have
        if need < 0:
            raise ValueError(f"Pilot exceeds {category} target")
        pool = [
            row
            for row in rows
            if row["category"] == category and row["task_id"] not in fixed_ids
        ]
        options = []
        for combination in itertools.combinations(pool, need):
            families = frozenset(row["variant_family"] for row in combination)
            if len(families) != len(combination):
                continue
            options.append(
                (
                    _counts(combination),
                    tuple(row["task_id"] for row in combination),
                    families,
                )
            )

        next_states: dict[
            tuple[int, ...], tuple[tuple[str, ...], frozenset[str]]
        ] = {}
        for state, (task_ids, families) in states.items():
            for counts, option_ids, option_families in options:
                if families.intersection(option_families):
                    continue
                next_state = tuple(a + b for a, b in zip(state, counts))
                if any(
                    value > target_state[index]
                    for index, value in enumerate(next_state)
                ):
                    continue
                selected = task_ids + option_ids
                score = tuple(sorted(stable_key(task_id) for task_id in selected))
                current = next_states.get(next_state)
                if current is None:
                    next_states[next_state] = (
                        selected,
                        families | option_families,
                    )
                    continue
                current_score = tuple(
                    sorted(stable_key(task_id) for task_id in current[0])
                )
                if score < current_score:
                    next_states[next_state] = (
                        selected,
                        families | option_families,
                    )
        states = next_states

    if target_state not in states:
        raise ValueError("No feasible Terminal-Bench Pareto20 panel")
    selected_ids = fixed_ids | set(states[target_state][0])
    if len(selected_ids) != 20:
        raise AssertionError(f"Expected 20 tasks, got {len(selected_ids)}")
    return selected_ids


def qualification_metadata(status: str) -> dict[str, Any]:
    qualification = json.loads(PILOT_QUALIFICATION_PATH.read_text())
    summary = qualification["summary"]
    return {
        "status": status,
        "baseline_model": qualification["policy"]["model"],
        "baseline_adapter": qualification["policy"]["adapter"],
        "baseline_thinking": qualification["policy"]["thinking"],
        "baseline_concurrency": qualification["policy"]["client_concurrency"],
        "pilot8_result": f"{summary['resolved']}/{summary['tasks']}",
        "incorrect": summary["incorrect"],
        "budget_exhausted": summary["budget_exhausted"],
        "infrastructure_failures": summary["infrastructure_failures"],
        "campaign_elapsed_seconds": summary["campaign_elapsed_seconds"],
        "runtime_is_clean_baseline": False,
        "evidence": str(PILOT_QUALIFICATION_PATH.relative_to(ROOT)),
    }


def build_manifest() -> dict[str, Any]:
    raw_source = SOURCE_MANIFEST_PATH.read_bytes()
    source = json.loads(raw_source)
    pilot = json.loads(PILOT_PATH.read_text())["suites"][
        "terminal_bench_core_0_1_1"
    ]
    pilot_strata = {task["id"]: task["stratum"] for task in pilot["tasks"]}
    rows = load_rows()
    selected_ids = select_task_ids(rows)
    tasks = []
    for row in sorted(rows, key=lambda item: item["task_id"]):
        if row["task_id"] not in selected_ids:
            continue
        task = dict(row)
        task["pilot8"] = row["task_id"] in pilot_strata
        task["stratum"] = pilot_strata.get(
            row["task_id"],
            f"{row['category']} / {row['runtime_bucket']}",
        )
        tasks.append(task)

    return {
        "name": "terminal-bench-core-pareto20",
        "version": "2026-08-15",
        "terminal_bench_version": source["terminal_bench_version"],
        "github_url": source["github_url"],
        "dataset_path": source["dataset_path"],
        "branch": source["branch"],
        "commit_hash": source["commit_hash"],
        "source_manifest": str(SOURCE_MANIFEST_PATH.relative_to(ROOT)),
        "source_manifest_sha256": hashlib.sha256(raw_source).hexdigest(),
        "selection": {
            "outcome_blind": True,
            "uses_target_model_outcomes": False,
            "seed": SEED,
            "panel_size": 20,
            "includes_runtime_pilot8": True,
            "category_targets": CATEGORY_TARGETS,
            "difficulty_targets": DIFFICULTY_TARGETS,
            "runtime_bucket_targets": RUNTIME_BUCKET_TARGETS,
            "runtime_bucket_definition_seconds": {
                "short": "<=360",
                "medium": "361-900",
                "long": ">900",
            },
            "at_most_one_task_per_variant_family": True,
        },
        "qualification": qualification_metadata("ready_baseline"),
        "task_ids": [task["task_id"] for task in tasks],
        "tasks": tasks,
    }


def build_pilot_manifest() -> dict[str, Any]:
    source = json.loads(SOURCE_MANIFEST_PATH.read_text())
    pilot = json.loads(PILOT_PATH.read_text())["suites"][
        "terminal_bench_core_0_1_1"
    ]
    pilot_strata = {task["id"]: task["stratum"] for task in pilot["tasks"]}
    tasks = []
    for row in sorted(load_rows(), key=lambda item: item["task_id"]):
        if row["task_id"] not in pilot_strata:
            continue
        task = dict(row)
        task["stratum"] = pilot_strata[row["task_id"]]
        tasks.append(task)
    return {
        "name": "terminal-bench-core-pilot8",
        "version": "2026-08-15",
        "terminal_bench_version": source["terminal_bench_version"],
        "github_url": source["github_url"],
        "dataset_path": source["dataset_path"],
        "branch": source["branch"],
        "commit_hash": source["commit_hash"],
        "source_manifest": str(SOURCE_MANIFEST_PATH.relative_to(ROOT)),
        "selection": {
            "outcome_blind": True,
            "source": "configs/ornith_runtime_pilot_v1.json",
            "pilot_size": 8,
        },
        "qualification": qualification_metadata("smoke_complete"),
        "task_ids": [task["task_id"] for task in tasks],
        "tasks": tasks,
    }


def main() -> int:
    manifest = build_manifest()
    pilot_manifest = build_pilot_manifest()
    OUTPUT_PATH.write_text(json.dumps(manifest, indent=2) + "\n")
    PILOT_OUTPUT_PATH.write_text(json.dumps(pilot_manifest, indent=2) + "\n")
    print(f"wrote {len(manifest['tasks'])} tasks to {OUTPUT_PATH.relative_to(ROOT)}")
    print(
        f"wrote {len(pilot_manifest['tasks'])} tasks to "
        f"{PILOT_OUTPUT_PATH.relative_to(ROOT)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
