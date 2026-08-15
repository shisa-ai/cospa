#!/usr/bin/env python3
"""Freeze the repeat-qualified SWE-PolyBench balanced64 panel."""

from __future__ import annotations

import hashlib
import itertools
import json
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PILOT_PATH = ROOT / "configs" / "ornith_runtime_pilot_v1.json"
CANDIDATE_PATH = (
    ROOT / "configs" / "swe_polybench_balanced_candidate96_v1.json"
)
CANDIDATE_IMAGE_PATH = (
    ROOT / "configs" / "swe_polybench_balanced_candidate96_images_v1.json"
)
JAVA_EXTENSION_PATH = (
    ROOT / "configs" / "swe_polybench_balanced_java_extension32_v1.json"
)
JAVA_EXTENSION_IMAGE_PATH = (
    ROOT / "configs" / "swe_polybench_balanced_java_extension32_images_v1.json"
)
JAVA_STRATA_EXTENSION_PATH = (
    ROOT
    / "configs"
    / "swe_polybench_balanced_java_strata_extension7_v1.json"
)
JAVA_STRATA_EXTENSION_IMAGE_PATH = (
    ROOT
    / "configs"
    / "swe_polybench_balanced_java_strata_extension7_images_v1.json"
)
QUALIFICATION_PATH = (
    ROOT / "configs" / "swe_polybench_balanced_qualification_v1.json"
)
OUTPUT_PATH = (
    ROOT / "configs" / "swe_polybench_verified_balanced64_v1.json"
)
OUTPUT_IMAGE_PATH = (
    ROOT / "configs" / "swe_polybench_verified_balanced64_images_v1.json"
)
LANGUAGES = ("java", "javascript", "python", "typescript")
TASK_TYPES = ("Bug Fix", "Feature", "Refactoring")
SIZE_TARGET = Counter({"small": 5, "medium": 5, "large": 6})
PLANNED_TYPE_TARGETS = {
    "java": Counter({"Bug Fix": 10, "Feature": 4, "Refactoring": 2}),
    "javascript": Counter({"Bug Fix": 11, "Feature": 4, "Refactoring": 1}),
    "python": Counter({"Bug Fix": 12, "Feature": 3, "Refactoring": 1}),
    "typescript": Counter({"Bug Fix": 12, "Feature": 3, "Refactoring": 1}),
}
PLANNED_REPOSITORY_CAPS = {
    "java": 4,
    "javascript": 5,
    "python": 5,
    "typescript": 6,
}
SEED = "cospa-polybench-balanced-qualified-v1"


def stable_key(task_id: str) -> str:
    return hashlib.sha256(f"{SEED}\0{task_id}".encode()).hexdigest()


def counter_distance(actual: Counter[str], target: Counter[str]) -> int:
    return sum(abs(actual[key] - target[key]) for key in set(actual) | set(target))


def qualification_passed(record: dict[str, Any]) -> bool:
    return (
        record["gold_observations"] == record["gold_passes"] == 3
        and record["null_observations"] == record["null_failures"] == 3
    )


def select_language_tasks(
    language: str,
    tasks: list[dict[str, Any]],
    qualification: dict[str, dict[str, Any]],
    pilot_ids: set[str],
) -> list[dict[str, Any]]:
    qualified = [
        task
        for task in tasks
        if task["language"] == language
        and qualification_passed(qualification[task["task_id"]])
    ]
    fixed = [task for task in qualified if task["task_id"] in pilot_ids]
    optional = [task for task in qualified if task["task_id"] not in pilot_ids]
    need = 16 - len(fixed)
    if need < 0 or len(optional) < need:
        raise ValueError(
            f"Insufficient qualified {language} tasks for balanced64: "
            f"{len(qualified)}"
        )

    ranked: list[tuple[tuple[Any, ...], list[dict[str, Any]]]] = []
    for combination in itertools.combinations(optional, need):
        selected = fixed + list(combination)
        type_counts = Counter(task["task_type"] for task in selected)
        size_counts = Counter(task["patch_size_tertile"] for task in selected)
        if set(type_counts) != set(TASK_TYPES) or set(size_counts) != set(SIZE_TARGET):
            continue
        if max(size_counts.values()) - min(size_counts.values()) > 2:
            continue
        repo_counts = Counter(task["repository"] for task in selected)
        cap = PLANNED_REPOSITORY_CAPS[language]
        cap_excess = sum(max(0, count - cap) for count in repo_counts.values())
        nonpilot = [task for task in selected if task["task_id"] not in pilot_ids]
        verifier_seconds = sum(
            float(qualification[task["task_id"]].get("gold_verifier_seconds", 0))
            for task in nonpilot
        )
        long_verifier_tasks = sum(
            float(qualification[task["task_id"]].get("gold_verifier_seconds", 0))
            / max(1, qualification[task["task_id"]]["gold_observations"])
            > 600
            for task in nonpilot
        )
        score = (
            long_verifier_tasks,
            cap_excess,
            counter_distance(type_counts, PLANNED_TYPE_TARGETS[language]),
            counter_distance(size_counts, SIZE_TARGET),
            max(repo_counts.values()),
            verifier_seconds,
            tuple(sorted(stable_key(task["task_id"]) for task in selected)),
        )
        ranked.append((score, selected))
    if not ranked:
        raise ValueError(f"No qualified stratified {language} balanced64 selection")
    return min(ranked, key=lambda item: item[0])[1]


def build_outputs() -> tuple[dict[str, Any], dict[str, Any]]:
    pilot = json.loads(PILOT_PATH.read_text())["suites"]["swe_polybench_verified"]
    candidate = json.loads(CANDIDATE_PATH.read_text())
    java_extension = json.loads(JAVA_EXTENSION_PATH.read_text())
    java_strata_extension = json.loads(JAVA_STRATA_EXTENSION_PATH.read_text())
    ledger = json.loads(QUALIFICATION_PATH.read_text())
    qualification = {record["task_id"]: record for record in ledger["tasks"]}
    source_tasks = {
        task["task_id"]: task
        for task in (
            candidate["tasks"]
            + java_extension["tasks"]
            + java_strata_extension["tasks"]
        )
    }
    if set(source_tasks) != set(qualification):
        missing = sorted(set(source_tasks) ^ set(qualification))
        raise ValueError(f"Qualification ledger/task mismatch: {missing}")
    pilot_ids = {task["id"] for task in pilot["tasks"]}

    selected: list[dict[str, Any]] = []
    for language in LANGUAGES:
        selected.extend(
            select_language_tasks(
                language,
                list(source_tasks.values()),
                qualification,
                pilot_ids,
            )
        )
    selected.sort(
        key=lambda task: (
            LANGUAGES.index(task["language"]),
            stable_key(task["task_id"]),
        )
    )

    type_targets: dict[str, dict[str, int]] = {}
    size_targets: dict[str, dict[str, int]] = {}
    effective_caps: dict[str, int] = {}
    for language in LANGUAGES:
        language_tasks = [task for task in selected if task["language"] == language]
        type_targets[language] = dict(
            sorted(Counter(task["task_type"] for task in language_tasks).items())
        )
        size_targets[language] = dict(
            sorted(
                Counter(
                    task["patch_size_tertile"] for task in language_tasks
                ).items()
            )
        )
        effective_caps[language] = max(
            Counter(task["repository"] for task in language_tasks).values()
        )

    tasks = []
    for source in selected:
        task = dict(source)
        task.pop("panel_membership", None)
        task.pop("previously_qualified_pilot28", None)
        task["qualification"] = {
            key: qualification[task["task_id"]].get(key, 0)
            for key in (
                "source",
                "gold_observations",
                "gold_passes",
                "null_observations",
                "null_failures",
                "gold_verifier_seconds",
                "null_verifier_seconds",
            )
        }
        tasks.append(task)

    manifest = {
        "name": "swe_polybench_verified_balanced64_v1",
        "version": "2026-08-15",
        "source": candidate["source"],
        "dataset": candidate["dataset"],
        "selection": {
            "uses_target_model_outcomes": False,
            "mechanical_qualification_only": True,
            "seed": SEED,
            "panel_size": 64,
            "tasks_per_language": 16,
            "includes_repeat_qualified_pilot28": True,
            "planned_task_type_targets": {
                language: dict(PLANNED_TYPE_TARGETS[language])
                for language in LANGUAGES
            },
            "task_type_targets": type_targets,
            "planned_patch_size_targets": dict(SIZE_TARGET),
            "patch_size_targets": size_targets,
            "planned_repository_caps": PLANNED_REPOSITORY_CAPS,
            "repository_caps": effective_caps,
            "verifier_outlier_seconds_per_observation": 600,
            "adaptive_note": (
                "Mechanical gold/null qualification reduced some strata. "
                "Selection first avoids verifier outliers above ten minutes, then "
                "minimizes repository-cap, task-type, patch-size, and total "
                "verifier-cost deviations without target-model outcomes."
            ),
        },
        "qualification": {
            "status": "repeat_qualified",
            "observations_per_condition": 3,
            "gold_passed": 64 * 3,
            "null_failed": 64 * 3,
            "verifier_network": "no-network",
            "completed_at": ledger["completed_at"],
            "evidence": ledger["evidence"],
            "screened_candidates": len(source_tasks),
            "fully_qualified_candidates": sum(
                qualification_passed(record) for record in qualification.values()
            ),
        },
        "suites": {
            "swe_polybench_verified_balanced64": {
                "tasks": [
                    {"id": task["task_id"], "image_ref": task["image_ref"]}
                    for task in tasks
                ]
            }
        },
        "tasks": tasks,
    }

    source_images: dict[str, dict[str, Any]] = {}
    for path in (
        CANDIDATE_IMAGE_PATH,
        JAVA_EXTENSION_IMAGE_PATH,
        JAVA_STRATA_EXTENSION_IMAGE_PATH,
    ):
        source_images.update(json.loads(path.read_text())["images"])
    final_images = {}
    for task in tasks:
        image_ref = task["image_ref"]
        image = dict(source_images[image_ref])
        image["suites"] = ["swe_polybench_verified_balanced64"]
        image["task_ids"] = [task["task_id"]]
        final_images[image_ref] = image
    manifest_bytes = (json.dumps(manifest, indent=2) + "\n").encode()
    image_lock = {
        "name": "swe_polybench_verified_balanced64_images_v1",
        "source_manifest": str(OUTPUT_PATH.relative_to(ROOT)),
        "source_manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "platform": {"os": "linux", "architecture": "amd64"},
        "images": dict(sorted(final_images.items())),
    }
    return manifest, image_lock


def main() -> int:
    manifest, image_lock = build_outputs()
    OUTPUT_PATH.write_text(json.dumps(manifest, indent=2) + "\n")
    OUTPUT_IMAGE_PATH.write_text(json.dumps(image_lock, indent=2) + "\n")
    print(f"wrote {len(manifest['tasks'])} tasks to {OUTPUT_PATH.relative_to(ROOT)}")
    print(
        f"wrote {len(image_lock['images'])} image pins to "
        f"{OUTPUT_IMAGE_PATH.relative_to(ROOT)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
