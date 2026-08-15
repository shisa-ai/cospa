#!/usr/bin/env python3
"""Freeze the repeat-qualified FeatureBench Lite Pareto12 panel."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CANDIDATE_PATH = ROOT / "configs" / "featurebench_lite30_v1.json"
CANDIDATE_IMAGE_LOCK_PATH = (
    ROOT / "configs" / "featurebench_lite30_images_v1.json"
)
OUTPUT_PATH = ROOT / "configs" / "featurebench_lite_pareto12_v1.json"
OUTPUT_IMAGE_LOCK_PATH = (
    ROOT / "configs" / "featurebench_lite_pareto12_images_v1.json"
)

PILOT_IDS = [
    "Lightning-AI__pytorch-lightning.126fa6f1.test_data.c8b292af.lv1",
    "sphinx-doc__sphinx.e347e59c.test_domain_c.4068b9e8.lv1",
]
EXTENSION_IDS = [
    "Netflix__metaflow.b390a8d4.test_stub_generator.7bf08c98.lv1",
    "astropy__astropy.b0db0daa.test_table.48eef659.lv1",
    "huggingface__transformers.e2e8dbed.test_serve.4e7860c7.lv1",
    "mlflow__mlflow.93dab383.test_databricks_tracing_utils.8ef44eb4.lv1",
    "mwaskom__seaborn.7001ebe7.test_regression.ce8c62e2.lv1",
    "mwaskom__seaborn.7001ebe7.test_algorithms.1f0181c2.lv1",
    "pandas-dev__pandas.82fa2715.test_concat.ebe5de39.lv1",
    "pydantic__pydantic.e1dcaf9e.test_deprecated_fields.40a2ec54.lv1",
    "pydata__xarray.97f3a746.test_backends_chunks.fa55f68a.lv1",
    "sympy__sympy.c1097516.test_nullspace.f14fc970.lv1",
]
SELECTED_IDS = PILOT_IDS + EXTENSION_IDS

PILOT_REPEAT = (
    "results/qualification/featurebench-pilot3-repeat2-20260815T2210Z/summary.json"
)
EXTENSION_FIRST_GOLD = [
    "results/qualification/featurebench-lite30-ready-gold1-v2-20260815T2230Z/summary.json",
    "results/qualification/featurebench-lite30-remaining4-gold1-20260815T2240Z/summary.json",
]
EXTENSION_REPEAT = (
    "results/qualification/featurebench-pareto12-new10-repeat-20260815T2210Z/summary.json"
)


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def _qualification(task_id: str) -> dict[str, Any]:
    if task_id in PILOT_IDS:
        source = "pilot6_mechanical_screen"
        evidence = [PILOT_REPEAT]
    else:
        source = "lite30_outcome_blind_extension"
        evidence = EXTENSION_FIRST_GOLD + [EXTENSION_REPEAT]
    return {
        "source": source,
        "gold_observations": 3,
        "gold_passes": 3,
        "null_observations": 3,
        "null_failures": 3,
        "evidence": evidence,
    }


def build_manifest() -> dict[str, Any]:
    candidate = _load(CANDIDATE_PATH)
    by_id = {task["task_id"]: task for task in candidate["tasks"]}
    missing = set(SELECTED_IDS).difference(by_id)
    if missing:
        raise ValueError(f"Missing selected FeatureBench tasks: {sorted(missing)}")

    tasks = []
    for task_id in SELECTED_IDS:
        task = dict(by_id[task_id])
        task["qualification"] = _qualification(task_id)
        tasks.append(task)
    repository_counts: dict[str, int] = {}
    for task in tasks:
        repo = task["repository"]
        repository_counts[repo] = repository_counts.get(repo, 0) + 1

    return {
        "name": "featurebench-lite-pareto12-v1",
        "version": "2026-08-15",
        "source": candidate["source"],
        "dataset": candidate["dataset"],
        "selection": {
            "official_split": "lite",
            "parent_manifest": "configs/featurebench_lite30_v1.json",
            "uses_target_model_outcomes": False,
            "mechanical_qualification_only": True,
            "panel_size": len(tasks),
            "repository_count": len(repository_counts),
            "repository_counts": dict(sorted(repository_counts.items())),
            "maximum_tasks_per_repository": max(repository_counts.values()),
            "level_counts": {
                "lv1": sum(task["level"] == 1 for task in tasks),
                "lv2": sum(task["level"] == 2 for task in tasks),
            },
            "policy": (
                "Preserve the two repeat-stable Level 1 pilot rows, then take "
                "the fastest first-gold-pass row from each repository not yet "
                "represented and the fastest remaining row under a repository "
                "cap of two. Selection used only verifier validity, repository "
                "coverage, and verifier wall time; no target-model outcomes."
            ),
        },
        "qualification": {
            "status": "repeat_qualified",
            "observations_per_condition": 3,
            "gold_passed": len(tasks) * 3,
            "null_failed": len(tasks) * 3,
            "verifier_network": "no-network",
            "completed_at": "2026-08-15",
            "screened_official_tasks": 30,
            "released_level1_gold_tasks": 26,
            "level2_without_released_gold": 4,
            "first_gold_passing_level1_tasks": 21,
            "fully_qualified_selected_tasks": len(tasks),
            "evidence": {
                "pilot_repeat": PILOT_REPEAT,
                "extension_first_gold": EXTENSION_FIRST_GOLD,
                "extension_repeat_gold_null": EXTENSION_REPEAT,
            },
        },
        "task_ids": SELECTED_IDS,
        "tasks": tasks,
        "suites": {
            "featurebench_lite_pareto12": {
                "tasks": [
                    {"id": task["task_id"], "image_ref": task["image_ref"]}
                    for task in tasks
                ]
            }
        },
    }


def build_image_lock(manifest: dict[str, Any]) -> dict[str, Any]:
    candidate_lock = _load(CANDIDATE_IMAGE_LOCK_PATH)
    selected_by_image: dict[str, list[str]] = {}
    for task in manifest["tasks"]:
        selected_by_image.setdefault(task["image_ref"], []).append(task["task_id"])

    images = {}
    for image_ref, task_ids in sorted(selected_by_image.items()):
        if image_ref not in candidate_lock["images"]:
            raise ValueError(f"Missing pinned FeatureBench image: {image_ref}")
        source = candidate_lock["images"][image_ref]
        images[image_ref] = {
            "suites": ["featurebench_lite_pareto12"],
            "task_ids": sorted(task_ids),
            "digest": source["digest"],
            "pinned_ref": source["pinned_ref"],
        }

    manifest_bytes = (json.dumps(manifest, indent=2) + "\n").encode()
    return {
        "name": "featurebench_lite_pareto12_images_v1",
        "source_manifest": "configs/featurebench_lite_pareto12_v1.json",
        "source_manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "platform": candidate_lock["platform"],
        "images": images,
    }


def main() -> int:
    manifest = build_manifest()
    image_lock = build_image_lock(manifest)
    OUTPUT_PATH.write_text(json.dumps(manifest, indent=2) + "\n")
    OUTPUT_IMAGE_LOCK_PATH.write_text(json.dumps(image_lock, indent=2) + "\n")
    print(
        f"wrote {len(manifest['tasks'])} tasks and "
        f"{len(image_lock['images'])} images"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
