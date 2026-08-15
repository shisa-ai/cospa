#!/usr/bin/env python3
"""Freeze one outcome-blind SWE-Explore Verified task per repository."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
BENCH_PATH = ROOT / "vendor" / "eval-data" / "swe-explore" / "bench.final.public.jsonl"
ISSUES_PATH = (
    ROOT
    / "vendor"
    / "eval-data"
    / "swe-explore"
    / "swe-bench-verified-issues.jsonl"
)
REPOS_PATH = ROOT / "vendor" / "eval-data" / "swe-explore" / "repos"
EVALUATOR_PATH = ROOT / "vendor" / "swe-explore-bench" / "eval.py"
OUTPUT_PATH = ROOT / "configs" / "swe_explore_verified12_v1.json"
SELECTION_SEED = "cospa-swe-explore-verified12-v1"

SOURCE_REVISION = "3c12dc5a551937038afcbdb6eb6bbf19f3ddd8c1"
DATASET_REVISION = "bdb0ae45d7c337d9e1dc3ebfe2a0af6bc7c1fbd9"
ISSUE_DATASET_REVISION = "c104f840cc67f8b6eec6f759ebc8b2693d585d4a"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def snapshot_sha256(root: Path) -> str:
    """Hash a repository snapshot without depending on tar metadata."""
    root = Path(root)
    digest = hashlib.sha256()
    for path in sorted(
        root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()
    ):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            kind = b"L"
            payload = str(path.readlink()).encode()
        elif path.is_dir():
            kind = b"D"
            payload = b""
        elif path.is_file():
            kind = b"F"
            payload = path.read_bytes()
        else:
            continue
        digest.update(kind)
        digest.update(relative.encode())
        digest.update(b"\0")
        digest.update(payload)
        digest.update(b"\0")
    return digest.hexdigest()


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line]


def _canonical_sha256(value: Any) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def build_manifest() -> dict[str, Any]:
    benchmark = {
        row["instance_id"]: row
        for row in _load_jsonl(BENCH_PATH)
        if row.get("dataset") == "verified"
    }
    issues = {row["instance_id"]: row for row in _load_jsonl(ISSUES_PATH)}
    common_ids = set(benchmark).intersection(issues)
    by_repository: dict[str, list[str]] = {}
    for task_id in common_ids:
        repository = str(issues[task_id]["repo"])
        by_repository.setdefault(repository, []).append(task_id)
    if len(benchmark) != 451 or len(by_repository) != 12:
        raise ValueError(
            "Pinned SWE-Explore Verified source no longer has 451 tasks / 12 repos"
        )

    selected_ids = []
    mechanically_rejected: dict[str, list[str]] = {}
    for repository in sorted(by_repository):
        ranked = sorted(
            by_repository[repository],
            key=lambda task_id: hashlib.sha256(
                f"{SELECTION_SEED}:{task_id}".encode()
            ).hexdigest(),
        )
        rejected = []
        for task_id in ranked:
            snapshot = REPOS_PATH / task_id
            if not snapshot.is_dir():
                raise FileNotFoundError(
                    f"Missing next ranked SWE-Explore snapshot: {snapshot}"
                )
            ground_truth = benchmark[task_id]["ground_truth"]
            valid = True
            for region in ground_truth.get("read_core_regions") or []:
                source_path = snapshot / str(region["path"])
                if not source_path.is_file():
                    valid = False
                    break
                line_count = len(
                    source_path.read_text(errors="replace").splitlines()
                )
                if not (
                    1
                    <= int(region["start"])
                    <= int(region["end"])
                    <= line_count
                ):
                    valid = False
                    break
            if valid:
                selected_ids.append(task_id)
                break
            rejected.append(task_id)
        else:
            raise ValueError(
                f"No mechanically valid SWE-Explore task for {repository}"
            )
        if rejected:
            mechanically_rejected[repository] = rejected

    tasks = []
    for task_id in selected_ids:
        issue = issues[task_id]
        record = benchmark[task_id]
        snapshot = REPOS_PATH / task_id
        if not snapshot.is_dir():
            raise FileNotFoundError(snapshot)
        problem_statement = str(issue["problem_statement"])
        ground_truth = record["ground_truth"]
        tasks.append(
            {
                "task_id": task_id,
                "repository": str(issue["repo"]),
                "base_commit": str(issue["base_commit"]),
                "source_dataset": "verified",
                "problem_statement_sha256": hashlib.sha256(
                    problem_statement.encode()
                ).hexdigest(),
                "ground_truth_sha256": _canonical_sha256(ground_truth),
                "snapshot_path": (
                    f"vendor/eval-data/swe-explore/repos/{task_id}"
                ),
                "snapshot_sha256": snapshot_sha256(snapshot),
                "selection_hash": hashlib.sha256(
                    f"{SELECTION_SEED}:{task_id}".encode()
                ).hexdigest(),
            }
        )

    return {
        "name": "swe-explore-verified12-v1",
        "version": "2026-08-16",
        "source": {
            "repository": "https://github.com/Qiushao-E/SWE-Explore-Bench.git",
            "revision": SOURCE_REVISION,
            "license": "MIT",
            "evaluator_path": "eval.py",
            "evaluator_sha256": sha256_file(EVALUATOR_PATH),
        },
        "dataset": {
            "repository": (
                "https://huggingface.co/datasets/"
                "SWE-Explore-Bench/SWE-Explore-Bench"
            ),
            "revision": DATASET_REVISION,
            "license": "CC-BY-NC-ND-4.0",
            "local_path": (
                "vendor/eval-data/swe-explore/bench.final.public.jsonl"
            ),
            "sha256": sha256_file(BENCH_PATH),
        },
        "issue_dataset": {
            "repository": (
                "https://huggingface.co/datasets/"
                "princeton-nlp/SWE-bench_Verified"
            ),
            "revision": ISSUE_DATASET_REVISION,
            "source_parquet_sha256": (
                "a45b1fe4e2f0c8390b2b2938ac83e92ed5979000856808f3679c07812e9e6dcd"
            ),
            "local_projection": (
                "vendor/eval-data/swe-explore/"
                "swe-bench-verified-issues.jsonl"
            ),
            "local_projection_sha256": sha256_file(ISSUES_PATH),
        },
        "selection": {
            "source_dataset": "verified",
            "seed": SELECTION_SEED,
            "uses_target_model_outcomes": False,
            "policy": (
                "Within each repository, take the minimum SHA-256 task rank "
                "whose official core paths and inclusive line spans are valid "
                "in the declared base-commit snapshot."
            ),
            "mechanical_gate": (
                "Every core region path exists and 1 <= start <= end <= file "
                "line count in the pinned base-commit snapshot."
            ),
            "mechanically_rejected": mechanically_rejected,
            "source_task_count": len(benchmark),
            "panel_size": len(tasks),
            "repository_count": len(by_repository),
            "tasks_per_repository": 1,
        },
        "protocol": {
            "top_k_regions": 5,
            "headline_metric": "weighted_core_coverage",
            "score_type": "continuous_non_coding",
            "secondary_metrics": [
                "precision",
                "recall",
                "f1_score",
                "hit_file_rate",
                "noise_file_rate",
                "hit_region_rate",
                "noise_region_rate",
                "context_efficiency",
                "optional_coverage",
                "ndcg_at_100",
                "ndcg_at_300",
                "ndcg_at_500",
                "recall_at_100",
                "recall_at_300",
                "recall_at_500",
                "first_useful_hit",
            ],
            "merge_with_coding_resolution": False,
        },
        "task_ids": selected_ids,
        "tasks": tasks,
    }


def main() -> int:
    manifest = build_manifest()
    OUTPUT_PATH.write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"wrote {len(manifest['tasks'])} tasks to {OUTPUT_PATH.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
