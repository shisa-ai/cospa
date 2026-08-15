"""Pinned SWE-Explore repository-localization diagnostic.

The agent receives one immutable repository snapshot and issue, then writes at
most five ranked file/line regions. Ground truth remains outside the sandbox;
Cospa scores the regions with the pinned upstream evaluator after the agent
finishes. This is a continuous exploration diagnostic, not coding resolution.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path
from types import ModuleType
from typing import Any

from harness.suites.terminal_bench import PROJECT_ROOT


PANEL_PATH = PROJECT_ROOT / "configs" / "swe_explore_verified12_v1.json"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_sha256(value: Any) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _snapshot_sha256(root: Path) -> str:
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


def _vendor_path(vendor_dir: Path, declared: str) -> Path:
    path = Path(declared)
    if path.parts and path.parts[0] == "vendor":
        return Path(vendor_dir).joinpath(*path.parts[1:])
    return PROJECT_ROOT / path


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line]


@lru_cache(maxsize=4)
def _load_evaluator_module(path_string: str, expected_sha256: str) -> ModuleType:
    path = Path(path_string)
    observed = _sha256_file(path)
    if observed != expected_sha256:
        raise ValueError(
            f"SWE-Explore evaluator checksum mismatch: {observed} != "
            f"{expected_sha256}"
        )
    spec = importlib.util.spec_from_file_location(
        f"cospa_swe_explore_eval_{expected_sha256[:12]}", path
    )
    if spec is None or spec.loader is None:
        raise ValueError(f"Could not load pinned SWE-Explore evaluator: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SweExploreVerified12Suite:
    """Outcome-blind, repository-distinct SWE-Explore Verified panel."""

    name = "swe_explore_verified12"
    version = "2026-08-16"
    languages = ["python"]
    task_count = 12

    def __init__(self) -> None:
        self.panel = json.loads(PANEL_PATH.read_text())
        self.selected = {
            task["task_id"]: task for task in self.panel["tasks"]
        }
        self._records: dict[str, dict[str, Any]] | None = None
        self._validated_snapshots: set[str] = set()

    def _source_root(self, vendor_dir: Path) -> Path:
        return Path(vendor_dir) / "swe-explore-bench"

    def _validate_source(self, vendor_dir: Path) -> bool:
        root = self._source_root(vendor_dir)
        evaluator_path = root / self.panel["source"]["evaluator_path"]
        if not evaluator_path.is_file() or not (root / ".git").exists():
            return False
        result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if (
            result.returncode != 0
            or result.stdout.strip() != self.panel["source"]["revision"]
        ):
            raise ValueError("SWE-Explore source checkout is not at the pinned revision")
        observed = _sha256_file(evaluator_path)
        expected = self.panel["source"]["evaluator_sha256"]
        if observed != expected:
            raise ValueError(
                f"SWE-Explore evaluator checksum mismatch: {observed} != {expected}"
            )
        return True

    def _load_records(self, vendor_dir: Path) -> dict[str, dict[str, Any]]:
        vendor_dir = Path(vendor_dir)
        if self._records is not None:
            return self._records
        if not self._validate_source(vendor_dir):
            return {}

        bench_path = _vendor_path(vendor_dir, self.panel["dataset"]["local_path"])
        issue_path = _vendor_path(
            vendor_dir, self.panel["issue_dataset"]["local_projection"]
        )
        if not bench_path.is_file() or not issue_path.is_file():
            return {}
        for path, expected in (
            (bench_path, self.panel["dataset"]["sha256"]),
            (
                issue_path,
                self.panel["issue_dataset"]["local_projection_sha256"],
            ),
        ):
            observed = _sha256_file(path)
            if observed != expected:
                raise ValueError(
                    f"SWE-Explore dataset checksum mismatch for {path}: "
                    f"{observed} != {expected}"
                )

        benchmark = {
            row["instance_id"]: row
            for row in _load_jsonl(bench_path)
            if row.get("dataset") == "verified"
        }
        issues = {row["instance_id"]: row for row in _load_jsonl(issue_path)}
        records: dict[str, dict[str, Any]] = {}
        for task_id, selected in self.selected.items():
            if task_id not in benchmark or task_id not in issues:
                raise ValueError(f"Missing selected SWE-Explore task: {task_id}")
            issue = issues[task_id]
            record = benchmark[task_id]
            problem_statement = str(issue["problem_statement"])
            ground_truth = record["ground_truth"]
            if hashlib.sha256(problem_statement.encode()).hexdigest() != selected[
                "problem_statement_sha256"
            ]:
                raise ValueError(f"SWE-Explore issue checksum mismatch: {task_id}")
            if _canonical_sha256(ground_truth) != selected["ground_truth_sha256"]:
                raise ValueError(
                    f"SWE-Explore ground-truth checksum mismatch: {task_id}"
                )
            if (
                str(issue["repo"]) != selected["repository"]
                or str(issue["base_commit"]) != selected["base_commit"]
            ):
                raise ValueError(f"SWE-Explore issue metadata mismatch: {task_id}")
            records[task_id] = {
                **selected,
                "problem_statement": problem_statement,
                "ground_truth": ground_truth,
            }
        self._records = records
        return records

    def _snapshot_path(self, task_id: str, vendor_dir: Path) -> Path:
        return _vendor_path(vendor_dir, self.selected[task_id]["snapshot_path"])

    def _validate_snapshot(self, task_id: str, vendor_dir: Path) -> bool:
        if task_id in self._validated_snapshots:
            return True
        snapshot = self._snapshot_path(task_id, vendor_dir)
        if not snapshot.is_dir():
            return False
        observed = _snapshot_sha256(snapshot)
        expected = self.selected[task_id]["snapshot_sha256"]
        if observed != expected:
            raise ValueError(
                f"SWE-Explore snapshot checksum mismatch for {task_id}: "
                f"{observed} != {expected}"
            )
        root = snapshot.resolve()
        for path in snapshot.rglob("*"):
            if path.is_symlink() and not path.resolve().is_relative_to(root):
                raise ValueError(
                    f"SWE-Explore snapshot contains escaping symlink: {path}"
                )
        self._validated_snapshots.add(task_id)
        return True

    def get_task_ids(self, vendor_dir: Path | None = None) -> list[str]:
        vendor_dir = Path(vendor_dir or PROJECT_ROOT / "vendor")
        records = self._load_records(vendor_dir)
        if not records:
            return []
        task_ids = list(self.panel["task_ids"])
        if any(not self._validate_snapshot(task_id, vendor_dir) for task_id in task_ids):
            return []
        return task_ids

    def materialize_task(
        self,
        task_id: str,
        workdir: Path,
        vendor_dir: Path | None = None,
    ) -> dict[str, Any]:
        vendor_dir = Path(vendor_dir or PROJECT_ROOT / "vendor")
        records = self._load_records(vendor_dir)
        if task_id not in self.selected or task_id not in records:
            raise ValueError(f"Unknown selected SWE-Explore task: {task_id}")
        if not self._validate_snapshot(task_id, vendor_dir):
            raise FileNotFoundError(self._snapshot_path(task_id, vendor_dir))
        record = records[task_id]
        snapshot = self._snapshot_path(task_id, vendor_dir).resolve()
        workdir = Path(workdir)
        if workdir.exists():
            shutil.rmtree(workdir)
        shutil.copytree(snapshot, workdir, symlinks=True)

        prompt = (
            "# SWE-Explore repository-localization task\n\n"
            f"- Task ID: `{task_id}`\n"
            f"- Repository: `{record['repository']}`\n"
            "- Work only in the current repository snapshot.\n"
            "- Explore read-only: do not modify source files or implement a patch.\n\n"
            "Identify the source files and exact line ranges most relevant to "
            "understanding and fixing the issue below. Write the final ranked "
            "answer to `swe_explore_regions.json` as a JSON array with at most 5 "
            "objects. Every object must contain exactly `path`, `start`, and "
            "`end`: a repository-relative path and inclusive 1-based line "
            "numbers. Rank the most useful root-cause region first. Do not put "
            "prose in the JSON file.\n\n"
            "## Issue\n\n"
            f"{record['problem_statement'].strip()}\n"
        )
        return {
            "task_id": task_id,
            "problem": task_id,
            "prompt": prompt,
            "problem_statement": record["problem_statement"],
            "repository": record["repository"],
            "base_commit": record["base_commit"],
            "ground_truth": record["ground_truth"],
            "snapshot_dir": str(snapshot),
            "vendor_dir": str(vendor_dir.resolve()),
            "language": "python",
            "timeout": 600,
        }

    def manifest_metadata(self, task_data: dict[str, Any]) -> dict[str, Any]:
        return {
            "protocol": "swe_explore_top5_localization",
            "panel": self.panel["name"],
            "panel_size": self.task_count,
            "repository": task_data["repository"],
            "base_commit": task_data["base_commit"],
            "source_revision": self.panel["source"]["revision"],
            "dataset_revision": self.panel["dataset"]["revision"],
            "verifier": "pinned_upstream_swe_explore_evaluator",
            "verifier_revision": self.panel["source"]["revision"],
            "verifier_sha256": self.panel["source"]["evaluator_sha256"],
            "top_k_regions": self.panel["protocol"]["top_k_regions"],
            "headline_metric": self.panel["protocol"]["headline_metric"],
            "score_type": self.panel["protocol"]["score_type"],
            "merge_with_coding_resolution": False,
        }

    def _invalid_output(self, message: str) -> dict[str, Any]:
        return {
            "passed": False,
            "test_count": 0,
            "score": 0.0,
            "headline_metric": self.panel["protocol"]["headline_metric"],
            "score_type": self.panel["protocol"]["score_type"],
            "grader_output": message,
            "exit_code": 1,
            "verifier_failed": False,
            "failure_class": "invalid_output",
        }

    @staticmethod
    def _region_paths(ground_truth: dict[str, Any]) -> set[str]:
        paths = {
            str(region["path"])
            for region in ground_truth.get("read_core_regions") or []
        }
        for regions in (
            ground_truth.get("read_optional_regions_map") or {}
        ).values():
            paths.update(str(region["path"]) for region in regions or [])
        return paths

    @staticmethod
    def _line_count(path: Path) -> int:
        with path.open("r", errors="replace") as source:
            return sum(1 for _ in source)

    def verify(self, task_data: dict[str, Any], workdir: Path) -> dict[str, Any]:
        workdir = Path(workdir).resolve()
        output = workdir / "swe_explore_regions.json"
        if (
            not output.is_file()
            or output.is_symlink()
            or not output.resolve().is_relative_to(workdir)
        ):
            return self._invalid_output("Missing regular swe_explore_regions.json")
        if output.stat().st_size > 65536:
            return self._invalid_output("SWE-Explore output exceeds 64 KiB")
        try:
            raw_regions = json.loads(output.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            return self._invalid_output(f"Invalid SWE-Explore JSON: {exc}")
        maximum = int(self.panel["protocol"]["top_k_regions"])
        if not isinstance(raw_regions, list) or len(raw_regions) > maximum:
            return self._invalid_output(
                f"SWE-Explore output must contain at most {maximum} regions"
            )

        snapshot = Path(task_data["snapshot_dir"]).resolve()
        predictions: list[tuple[str, int, int]] = []
        predicted_paths: set[str] = set()
        try:
            for raw in raw_regions:
                if not isinstance(raw, dict) or set(raw) != {"path", "start", "end"}:
                    raise ValueError("each region must contain path/start/end only")
                relative = str(raw["path"])
                relative_path = Path(relative)
                if relative_path.is_absolute() or ".." in relative_path.parts:
                    raise ValueError(f"unsafe repository path: {relative!r}")
                if any(
                    isinstance(raw[key], bool) or not isinstance(raw[key], int)
                    for key in ("start", "end")
                ):
                    raise ValueError("region line numbers must be integers")
                start = int(raw["start"])
                end = int(raw["end"])
                source_path = (snapshot / relative_path).resolve()
                if (
                    not source_path.is_relative_to(snapshot)
                    or not source_path.is_file()
                    or start < 1
                    or end < start
                ):
                    raise ValueError(f"invalid repository region: {raw!r}")
                line_count = self._line_count(source_path)
                if end > line_count:
                    raise ValueError(
                        f"region ends after line {line_count}: {raw!r}"
                    )
                predictions.append((relative_path.as_posix(), start, end))
                predicted_paths.add(relative_path.as_posix())
        except (OSError, ValueError) as exc:
            return self._invalid_output(str(exc))

        try:
            evaluator_path = (
                Path(task_data.get("vendor_dir", PROJECT_ROOT / "vendor"))
                / "swe-explore-bench"
                / self.panel["source"]["evaluator_path"]
            )
            if not evaluator_path.is_file():
                evaluator_path = (
                    PROJECT_ROOT
                    / "vendor"
                    / "swe-explore-bench"
                    / self.panel["source"]["evaluator_path"]
                )
            evaluator_module = _load_evaluator_module(
                str(evaluator_path.resolve()),
                self.panel["source"]["evaluator_sha256"],
            )
            all_paths = predicted_paths | self._region_paths(task_data["ground_truth"])
            line_counts = {}
            for relative in all_paths:
                source_path = (snapshot / relative).resolve()
                if source_path.is_relative_to(snapshot) and source_path.is_file():
                    line_counts[relative] = self._line_count(source_path)
            evaluator = evaluator_module.ExploreEvaluator.__new__(
                evaluator_module.ExploreEvaluator
            )
            evaluator.bench_data = []
            evaluator.bench_data_dict = {
                task_data["task_id"]: {"ground_truth": task_data["ground_truth"]}
            }
            evaluator.file_line_counts = {task_data["task_id"]: line_counts}
            evaluator._current_instance_id = None
            evaluator._current_file_line_counts = {}
            metrics = [
                self.panel["protocol"]["headline_metric"],
                *self.panel["protocol"]["secondary_metrics"],
            ]
            scored = evaluator.evaluate(
                lambda _issue, _instance_id: predictions,
                task_data["task_id"],
                metrics,
            )[task_data["task_id"]]
        except Exception as exc:
            return {
                "passed": False,
                "test_count": 0,
                "score": None,
                "grader_output": f"Pinned SWE-Explore evaluator failed: {exc}",
                "exit_code": -1,
                "verifier_failed": True,
                "failure_class": "verifier_failed",
            }

        headline = self.panel["protocol"]["headline_metric"]
        score = float(scored[headline])
        return {
            "passed": score > 0.0,
            "test_count": len(predictions),
            "score": score,
            "headline_metric": headline,
            "score_type": self.panel["protocol"]["score_type"],
            "metrics": {key: float(value) for key, value in scored.items()},
            "regions": [
                {"path": path, "start": start, "end": end}
                for path, start, end in predictions
            ],
            "binary_diagnostic": "any_core_line_hit",
            "grader_output": json.dumps(scored, sort_keys=True),
            "exit_code": 0,
            "verifier_failed": False,
            "failure_class": "diagnostic_scored",
        }
