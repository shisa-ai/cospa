#!/usr/bin/env python3
"""Freeze FeatureBench's official 30-task Lite split before model outcomes."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PILOT_PATH = ROOT / "configs" / "ornith_runtime_pilot_v1.json"
OUTPUT_PATH = ROOT / "configs" / "featurebench_lite30_v1.json"
VENDOR_DIR = ROOT / "vendor"


_READER = r'''
import json
import sys

import pandas as pd

rows = []
for raw in pd.read_parquet(sys.argv[1]).to_dict(orient="records"):
    row = {}
    for key, value in raw.items():
        if hasattr(value, "tolist"):
            value = value.tolist()
        row[key] = value
    row["FAIL_TO_PASS"] = list(row.get("FAIL_TO_PASS") or [])
    row["PASS_TO_PASS"] = list(row.get("PASS_TO_PASS") or [])
    row["repo_settings"] = json.loads(row.get("repo_settings") or "{}")
    rows.append(row)
print(json.dumps(rows))
'''.strip()


def _dataset_config() -> dict[str, Any]:
    return json.loads(PILOT_PATH.read_text())["suites"]["featurebench_lite"]


def _dataset_path(config: dict[str, Any]) -> Path:
    declared = Path(config["dataset"]["local_path"])
    return ROOT / declared


def load_rows() -> list[dict[str, Any]]:
    config = _dataset_config()
    dataset_path = _dataset_path(config)
    observed = hashlib.sha256(dataset_path.read_bytes()).hexdigest()
    expected = config["dataset"]["sha256"]
    if observed != expected:
        raise ValueError(
            f"FeatureBench dataset checksum mismatch: {observed} != {expected}"
        )
    python = VENDOR_DIR / "featurebench" / ".venv" / "bin" / "python"
    if not python.is_file():
        raise FileNotFoundError(
            "FeatureBench parquet reader missing; run "
            "`uv sync --project vendor/featurebench`"
        )
    completed = subprocess.run(
        [str(python), "-c", _READER, str(dataset_path)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise ValueError(f"Pinned FeatureBench dataset reader failed: {detail}")
    loaded = json.loads(completed.stdout)
    if not isinstance(loaded, list):
        raise ValueError("Pinned FeatureBench dataset reader returned non-list")
    return loaded


def _task_metadata(row: dict[str, Any]) -> dict[str, Any]:
    task_id = str(row["instance_id"])
    settings = row.get("repo_settings") or {}
    run_args = (settings.get("docker_specs") or {}).get("run_args") or {}
    visible = run_args.get(
        "cuda_visible_num", run_args.get("cuda_visible_devices")
    )
    number_once = run_args.get("number_once", 1)
    if not isinstance(number_once, int) or number_once < 1:
        number_once = 1
    return {
        "task_id": task_id,
        "repository": str(row["repo"]),
        "level": int(task_id.rsplit(".lv", 1)[1]),
        "base_commit": str(row["base_commit"]),
        "image_ref": str(row["image_name"]),
        "patch_bytes": len(str(row.get("patch") or "").encode()),
        "test_patch_bytes": len(str(row.get("test_patch") or "").encode()),
        "problem_statement_sha256": hashlib.sha256(
            str(row["problem_statement"]).encode()
        ).hexdigest(),
        "f2p_file_count": len(row.get("FAIL_TO_PASS") or []),
        "p2p_file_count": len(row.get("PASS_TO_PASS") or []),
        "timeout_run_seconds": int(settings.get("timeout_run", 1800)),
        "timeout_one_seconds": int(settings.get("timeout_one", 10)),
        "needs_gpu": bool(visible),
        "requested_gpus": number_once if visible else 0,
    }


def build_manifest() -> dict[str, Any]:
    config = _dataset_config()
    tasks = [_task_metadata(row) for row in load_rows()]
    repositories = sorted({task["repository"] for task in tasks})
    return {
        "name": "featurebench-lite30-v1",
        "version": "2026-08-15",
        "source": config["source"],
        "dataset": config["dataset"],
        "selection": {
            "official_split": "lite",
            "outcome_blind": True,
            "uses_target_model_outcomes": False,
            "panel_size": len(tasks),
            "repositories": len(repositories),
            "repository_names": repositories,
            "level_counts": {
                "lv1": sum(task["level"] == 1 for task in tasks),
                "lv2": sum(task["level"] == 2 for task in tasks),
            },
            "note": (
                "All rows in the pinned official Lite parquet are candidates; "
                "mechanical gold/null screening may produce a distinctly named "
                "hermetic campaign subset."
            ),
        },
        "qualification": {
            "status": "candidate_screen_pending",
            "gold_policy": "three no-network observations for released Level 1 gold",
            "null_policy": "three no-network observations",
            "level2_gold_status": "not_released_upstream",
            "uses_target_model_outcomes": False,
        },
        "task_ids": [task["task_id"] for task in tasks],
        "tasks": tasks,
        "suites": {
            "featurebench_lite30_candidate": {
                "tasks": [
                    {"id": task["task_id"], "image_ref": task["image_ref"]}
                    for task in tasks
                ]
            }
        },
    }


def main() -> int:
    manifest = build_manifest()
    OUTPUT_PATH.write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"wrote {len(manifest['tasks'])} tasks to {OUTPUT_PATH.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
