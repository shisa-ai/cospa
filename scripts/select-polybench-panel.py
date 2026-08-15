#!/usr/bin/env python3
"""Freeze outcome-blind nested SWE-PolyBench balanced candidate panels."""

from __future__ import annotations

import csv
import hashlib
import itertools
import json
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PILOT_PATH = ROOT / "configs" / "ornith_runtime_pilot_v1.json"
OUTPUT_PATH = ROOT / "configs" / "swe_polybench_balanced_candidate96_v1.json"
JAVA_EXTENSION_PATH = (
    ROOT / "configs" / "swe_polybench_balanced_java_extension32_v1.json"
)
JAVA_STRATA_EXTENSION_PATH = (
    ROOT
    / "configs"
    / "swe_polybench_balanced_java_strata_extension7_v1.json"
)
LANGUAGES = ("Java", "JavaScript", "Python", "TypeScript")
TASK_TYPES = ("Bug Fix", "Feature", "Refactoring")
SEED = "cospa-polybench-balanced-v1"
TARGET64 = {
    "Java": {"Bug Fix": 10, "Feature": 4, "Refactoring": 2},
    "JavaScript": {"Bug Fix": 11, "Feature": 4, "Refactoring": 1},
    "Python": {"Bug Fix": 12, "Feature": 3, "Refactoring": 1},
    "TypeScript": {"Bug Fix": 12, "Feature": 3, "Refactoring": 1},
}
TARGET96 = {
    "Java": {"Bug Fix": 15, "Feature": 6, "Refactoring": 3},
    "JavaScript": {"Bug Fix": 17, "Feature": 5, "Refactoring": 2},
    "Python": {"Bug Fix": 18, "Feature": 5, "Refactoring": 1},
    "TypeScript": {"Bug Fix": 18, "Feature": 5, "Refactoring": 1},
}
CAP64 = {"Java": 4, "JavaScript": 5, "Python": 5, "TypeScript": 6}
CAP96 = {"Java": 6, "JavaScript": 8, "Python": 8, "TypeScript": 10}


def patch_changes(patch: str) -> int:
    return sum(
        line.startswith(("+", "-")) and not line.startswith(("+++", "---"))
        for line in patch.splitlines()
    )


def load_rows(dataset_path: Path) -> list[dict[str, Any]]:
    csv.field_size_limit(max(csv.field_size_limit(), dataset_path.stat().st_size))
    with dataset_path.open(newline="") as handle:
        rows: list[dict[str, Any]] = list(csv.DictReader(handle))
    for row in rows:
        row["patch_changes"] = patch_changes(row["patch"])
    for language in LANGUAGES:
        ordered = sorted(
            (row for row in rows if row["language"] == language),
            key=lambda row: (row["patch_changes"], row["instance_id"]),
        )
        for index, row in enumerate(ordered):
            row["patch_size_tertile"] = min(2, index * 3 // len(ordered))
    return rows


def row_options(
    total: int,
    lower: list[int],
    upper: list[int],
) -> list[tuple[int, int, int]]:
    return [
        (first, second, total - first - second)
        for first in range(lower[0], min(upper[0], total) + 1)
        for second in range(lower[1], min(upper[1], total - first) + 1)
        if lower[2] <= total - first - second <= upper[2]
    ]


def cell_quotas(
    candidates: list[dict[str, Any]],
    fixed: list[dict[str, Any]],
    type_targets: dict[str, int],
    size_targets: tuple[int, int, int],
) -> dict[tuple[str, int], int]:
    lower = Counter(
        (row["task_category"], row["patch_size_tertile"]) for row in fixed
    )
    upper = Counter(
        (row["task_category"], row["patch_size_tertile"])
        for row in candidates
    )
    options = [
        row_options(
            type_targets[task_type],
            [lower[task_type, tertile] for tertile in range(3)],
            [upper[task_type, tertile] for tertile in range(3)],
        )
        for task_type in TASK_TYPES
    ]
    total = sum(type_targets.values())
    feasible: list[tuple[float, tuple[tuple[int, int, int], ...]]] = []
    for matrix in itertools.product(*options):
        if any(
            sum(row[tertile] for row in matrix) != size_targets[tertile]
            for tertile in range(3)
        ):
            continue
        deviation = sum(
            (
                matrix[type_index][tertile]
                - type_targets[task_type] * size_targets[tertile] / total
            )
            ** 2
            for type_index, task_type in enumerate(TASK_TYPES)
            for tertile in range(3)
        )
        feasible.append((deviation, matrix))
    if not feasible:
        raise ValueError("No feasible task-type/patch-size quota matrix")
    matrix = min(feasible)[1]
    return {
        (task_type, tertile): matrix[type_index][tertile]
        for type_index, task_type in enumerate(TASK_TYPES)
        for tertile in range(3)
    }


def stable_key(task_id: str) -> str:
    return hashlib.sha256(f"{SEED}\0{task_id}".encode()).hexdigest()


def extend_panel(
    rows: list[dict[str, Any]],
    preselected: set[str],
    targets: dict[str, dict[str, int]],
    size_targets: tuple[int, int, int],
    repo_caps: dict[str, int],
    languages: tuple[str, ...] = LANGUAGES,
) -> set[str]:
    selected = set(preselected)
    for language in languages:
        candidates = [row for row in rows if row["language"] == language]
        fixed = [row for row in candidates if row["instance_id"] in selected]
        quotas = cell_quotas(candidates, fixed, targets[language], size_targets)
        repo_counts = Counter(row["repo"] for row in fixed)
        cells = sorted(
            quotas,
            key=lambda cell: (
                sum(
                    row["task_category"] == cell[0]
                    and row["patch_size_tertile"] == cell[1]
                    for row in candidates
                ),
                cell,
            ),
        )
        for cell in cells:
            have = sum(
                row["task_category"] == cell[0]
                and row["patch_size_tertile"] == cell[1]
                for row in fixed
            )
            need = quotas[cell] - have
            if need <= 0:
                continue
            pool = [
                row
                for row in candidates
                if row["instance_id"] not in selected
                and row["task_category"] == cell[0]
                and row["patch_size_tertile"] == cell[1]
            ]
            pool.sort(
                key=lambda row: (
                    repo_counts[row["repo"]],
                    stable_key(row["instance_id"]),
                )
            )
            chosen: list[dict[str, Any]] = []
            for row in pool:
                if repo_counts[row["repo"]] >= repo_caps[language]:
                    continue
                chosen.append(row)
                repo_counts[row["repo"]] += 1
                if len(chosen) == need:
                    break
            if len(chosen) != need:
                raise ValueError(
                    f"Cannot fill {language} {cell} under repository cap"
                )
            selected.update(row["instance_id"] for row in chosen)
            fixed.extend(chosen)
        if len(fixed) != sum(targets[language].values()):
            raise AssertionError(f"Wrong {language} panel size")
        if Counter(row["task_category"] for row in fixed) != Counter(
            targets[language]
        ):
            raise AssertionError(f"Wrong {language} task-type distribution")
        if Counter(row["patch_size_tertile"] for row in fixed) != Counter(
            dict(enumerate(size_targets))
        ):
            raise AssertionError(f"Wrong {language} patch-size distribution")
        if max(repo_counts.values()) > repo_caps[language]:
            raise AssertionError(f"Exceeded {language} repository cap")
    return selected


def image_ref(task_id: str) -> str:
    return (
        "ghcr.io/timesler/swe-polybench.eval.x86_64."
        f"{task_id.lower()}:v1.1"
    )


def build_manifest() -> dict[str, Any]:
    pilot = json.loads(PILOT_PATH.read_text())["suites"]["swe_polybench_verified"]
    declared = Path(pilot["dataset"]["local_path"])
    dataset_path = ROOT / declared
    rows = load_rows(dataset_path)
    pilot28 = {task["id"] for task in pilot["tasks"]}
    prior_exclusions = {
        item["id"] for item in pilot["qualification"]["excluded"]
    }
    rows = [row for row in rows if row["instance_id"] not in prior_exclusions]
    selected64 = extend_panel(rows, pilot28, TARGET64, (5, 5, 6), CAP64)
    selected96 = extend_panel(rows, selected64, TARGET96, (8, 8, 8), CAP96)
    if len(selected64) != 64 or len(selected96) != 96:
        raise AssertionError("Wrong nested panel sizes")

    tasks = []
    for row in rows:
        task_id = row["instance_id"]
        if task_id not in selected96:
            continue
        tasks.append(
            {
                "task_id": task_id,
                "image_ref": image_ref(task_id),
                "language": row["language"].lower(),
                "task_type": row["task_category"],
                "repository": row["repo"],
                "patch_changes": row["patch_changes"],
                "patch_size_tertile": ("small", "medium", "large")[
                    row["patch_size_tertile"]
                ],
                "panel_membership": (
                    "balanced64_candidate"
                    if task_id in selected64
                    else "balanced96_extension_candidate"
                ),
                "previously_qualified_pilot28": task_id in pilot28,
            }
        )
    return {
        "name": "swe_polybench_balanced_candidate96_v1",
        "version": "2026-08-15",
        "source": pilot["source"],
        "dataset": pilot["dataset"],
        "selection": {
            "outcome_blind": True,
            "seed": SEED,
            "candidate_size": 96,
            "nested_balanced64_size": 64,
            "languages": {"balanced64": 16, "candidate96": 24},
            "patch_size_tertiles": {
                "balanced64": [5, 5, 6],
                "candidate96": [8, 8, 8],
            },
            "repository_caps": {
                "balanced64": {key.lower(): value for key, value in CAP64.items()},
                "candidate96": {key.lower(): value for key, value in CAP96.items()},
            },
            "task_type_targets": {
                "balanced64": {key.lower(): value for key, value in TARGET64.items()},
                "candidate96": {key.lower(): value for key, value in TARGET96.items()},
            },
            "includes_repeat_qualified_pilot28": True,
            "prior_mechanical_exclusions": sorted(prior_exclusions),
            "excludes_target_model_outcomes": True,
        },
        "qualification": {
            "status": "support_candidates_screened_not_scored",
            "target_observations_per_condition": 3,
            "evidence": "configs/swe_polybench_balanced_qualification_v1.json",
        },
        "suites": {
            "swe_polybench_balanced_candidate96": {
                "tasks": [
                    {"id": task["task_id"], "image_ref": task["image_ref"]}
                    for task in tasks
                ]
            }
        },
        "tasks": tasks,
    }


def build_java_extension_manifest() -> dict[str, Any]:
    pilot = json.loads(PILOT_PATH.read_text())["suites"]["swe_polybench_verified"]
    declared = Path(pilot["dataset"]["local_path"])
    rows = load_rows(ROOT / declared)
    candidate = build_manifest()
    unavailable = {
        task["task_id"] for task in candidate["tasks"]
    } | {
        item["id"] for item in pilot["qualification"]["excluded"]
    }
    rows = [
        row for row in rows
        if row["instance_id"] not in unavailable and row["language"] == "Java"
    ]
    target = {"Java": {"Bug Fix": 20, "Feature": 8, "Refactoring": 4}}
    selected = extend_panel(
        rows,
        set(),
        target,
        (10, 11, 11),
        {"Java": 10},
        languages=("Java",),
    )
    tasks = []
    for row in rows:
        if row["instance_id"] not in selected:
            continue
        tasks.append(
            {
                "task_id": row["instance_id"],
                "image_ref": image_ref(row["instance_id"]),
                "language": "java",
                "task_type": row["task_category"],
                "repository": row["repo"],
                "patch_changes": row["patch_changes"],
                "patch_size_tertile": ("small", "medium", "large")[
                    row["patch_size_tertile"]
                ],
            }
        )
    return {
        "name": "swe_polybench_balanced_java_extension32_v1",
        "version": "2026-08-15",
        "source": pilot["source"],
        "dataset": pilot["dataset"],
        "selection": {
            "outcome_blind": True,
            "seed": SEED,
            "adaptive_reason": (
                "The first mechanical candidate screen retained only nine "
                "Java tasks; select additional Java candidates without using "
                "any target-model outcomes."
            ),
            "uses_target_model_outcomes": False,
            "candidate_size": 32,
            "task_type_targets": target["Java"],
            "patch_size_tertiles": [10, 11, 11],
            "repository_cap": 10,
            "excluded_candidate96_and_prior_mechanical_failures": True,
        },
        "qualification": {
            "status": "support_candidates_screened_not_scored",
            "target_observations_per_condition": 3,
            "evidence": "configs/swe_polybench_balanced_qualification_v1.json",
        },
        "suites": {
            "swe_polybench_balanced_java_extension32": {
                "tasks": [
                    {"id": task["task_id"], "image_ref": task["image_ref"]}
                    for task in tasks
                ]
            }
        },
        "tasks": tasks,
    }


def build_java_strata_extension_manifest() -> dict[str, Any]:
    pilot = json.loads(PILOT_PATH.read_text())["suites"]["swe_polybench_verified"]
    declared = Path(pilot["dataset"]["local_path"])
    rows = load_rows(ROOT / declared)
    unavailable = {
        task["task_id"]
        for manifest in (build_manifest(), build_java_extension_manifest())
        for task in manifest["tasks"]
    } | {item["id"] for item in pilot["qualification"]["excluded"]}
    selected = [
        row
        for row in rows
        if row["language"] == "Java"
        and row["patch_size_tertile"] in (0, 1)
        and row["instance_id"] not in unavailable
    ]
    if len(selected) != 7:
        raise AssertionError(
            f"Expected seven remaining Java strata tasks, got {len(selected)}"
        )
    selected.sort(
        key=lambda row: (
            row["patch_size_tertile"],
            stable_key(row["instance_id"]),
        )
    )
    tasks = [
        {
            "task_id": row["instance_id"],
            "image_ref": image_ref(row["instance_id"]),
            "language": "java",
            "task_type": row["task_category"],
            "repository": row["repo"],
            "patch_changes": row["patch_changes"],
            "patch_size_tertile": ("small", "medium", "large")[
                row["patch_size_tertile"]
            ],
        }
        for row in selected
    ]
    return {
        "name": "swe_polybench_balanced_java_strata_extension7_v1",
        "version": "2026-08-15",
        "source": pilot["source"],
        "dataset": pilot["dataset"],
        "selection": {
            "outcome_blind": True,
            "uses_target_model_outcomes": False,
            "adaptive_reason": (
                "Mechanical candidate screens left only four qualified small "
                "and four qualified medium Java tasks. Screen every remaining "
                "eligible task in those source strata before relaxing balance."
            ),
            "candidate_size": 7,
            "patch_size_tertiles": {"small": 4, "medium": 3},
            "excluded_prior_candidates_and_mechanical_failures": True,
        },
        "qualification": {
            "status": "support_candidates_screened_not_scored",
            "target_observations_per_condition": 3,
            "evidence": "configs/swe_polybench_balanced_qualification_v1.json",
        },
        "suites": {
            "swe_polybench_balanced_java_strata_extension7": {
                "tasks": [
                    {"id": task["task_id"], "image_ref": task["image_ref"]}
                    for task in tasks
                ]
            }
        },
        "tasks": tasks,
    }


def main() -> int:
    manifest = build_manifest()
    java_extension = build_java_extension_manifest()
    java_strata_extension = build_java_strata_extension_manifest()
    OUTPUT_PATH.write_text(json.dumps(manifest, indent=2) + "\n")
    JAVA_EXTENSION_PATH.write_text(json.dumps(java_extension, indent=2) + "\n")
    JAVA_STRATA_EXTENSION_PATH.write_text(
        json.dumps(java_strata_extension, indent=2) + "\n"
    )
    print(
        f"wrote {len(manifest['tasks'])} candidates to "
        f"{OUTPUT_PATH.relative_to(ROOT)}"
    )
    print(
        f"wrote {len(java_extension['tasks'])} Java extension candidates to "
        f"{JAVA_EXTENSION_PATH.relative_to(ROOT)}"
    )
    print(
        f"wrote {len(java_strata_extension['tasks'])} Java strata candidates to "
        f"{JAVA_STRATA_EXTENSION_PATH.relative_to(ROOT)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
