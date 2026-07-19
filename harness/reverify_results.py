"""Re-run suite verifiers against existing result workdirs."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from harness.path_utils import decode_model_path, decode_task_path
from harness.suites import load_suite


SUMMARY_KEYS = (
    "scanned",
    "reverified",
    "changed",
    "updated",
    "unchanged",
    "skipped_missing_artifacts",
    "skipped_adapter_failed",
    "skipped_suite",
    "errors",
)

VERDICT_COMPARE_KEYS = (
    "passed",
    "test_count",
    "exit_code",
    "pending",
    "adapter_failed",
    "verifier_failed",
)


def _iter_trial_dirs(results_dir: Path):
    for verdict_path in results_dir.rglob("verdict.json"):
        trial_dir = verdict_path.parent
        if re.fullmatch(r"trial-\d+", trial_dir.name):
            yield trial_dir


def _matches(path: Path, filters: tuple[str, ...], excludes: tuple[str, ...]) -> bool:
    text = path.as_posix()
    for pattern in filters:
        if not re.search(pattern, text):
            return False
    for pattern in excludes:
        if re.search(pattern, text):
            return False
    return True


def _trial_suite_name(trial_dir: Path) -> str | None:
    try:
        return trial_dir.parent.parent.name
    except IndexError:
        return None


def _matched_run_info(
    results_dir: Path,
    trial_dir: Path,
    manifest: dict[str, Any] | None,
) -> dict[str, str]:
    task_dir = trial_dir.parent
    suite_dir = task_dir.parent
    adapter_dir = suite_dir.parent
    model_dir = adapter_dir.parent
    try:
        run_parent = model_dir.parent.relative_to(results_dir)
        run = "" if str(run_parent) == "." else run_parent.as_posix()
    except ValueError:
        run = ""

    model = manifest.get("model") if isinstance(manifest, dict) else None
    sampling = manifest.get("sampling") if isinstance(manifest, dict) else None
    model_id = model.get("id") if isinstance(model, dict) else None
    provider = model.get("provider") if isinstance(model, dict) else None
    thinking = sampling.get("thinking") if isinstance(sampling, dict) else None

    if not isinstance(model_id, str):
        model_id = decode_model_path(model_dir.name)
    if not isinstance(provider, str):
        provider = model_id.split("/")[0] if "/" in model_id else "unknown"
    if not isinstance(thinking, str) or not thinking:
        thinking = "default"

    return {
        "run": run,
        "model": model_id,
        "adapter": adapter_dir.name,
        "suite": suite_dir.name,
        "thinking": thinking,
        "provider": provider,
    }


def _matched_run_key(info: dict[str, str]) -> tuple[str, str, str, str, str, str]:
    return (
        info["run"],
        info["model"],
        info["adapter"],
        info["suite"],
        info["thinking"],
        info["provider"],
    )


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    temp_path = path.with_name(f"{path.name}.tmp")
    temp_path.write_text(json.dumps(payload, indent=2) + "\n")
    temp_path.replace(path)


def _task_id_from_trial(trial_dir: Path, manifest: dict[str, Any]) -> str | None:
    suite = manifest.get("suite")
    if isinstance(suite, dict) and isinstance(suite.get("task_id"), str):
        return suite["task_id"]
    try:
        return decode_task_path(trial_dir.parent.name)
    except Exception:
        return None


def _task_data_from_manifest(
    trial_dir: Path,
    manifest: dict[str, Any],
    *,
    timeout: int,
) -> dict[str, Any] | None:
    task_id = _task_id_from_trial(trial_dir, manifest)
    if not task_id:
        return None

    model = manifest.get("model")
    sampling = manifest.get("sampling")
    task_data: dict[str, Any] = {
        "task_id": task_id,
        "timeout": timeout,
    }
    if isinstance(model, dict) and isinstance(model.get("id"), str):
        task_data["model_id"] = model["id"]
    if isinstance(sampling, dict):
        task_data["thinking"] = sampling.get("thinking")

    parts = task_id.split("/", 1)
    if len(parts) == 2:
        task_data["language"], task_data["problem"] = parts
    return task_data


def _verdict_projection(verdict: dict[str, Any]) -> dict[str, Any]:
    return {
        key: verdict.get(key)
        for key in VERDICT_COMPARE_KEYS
        if key in verdict
    }


def _verdict_changed(
    old_verdict: dict[str, Any],
    new_verdict: dict[str, Any],
) -> bool:
    return _verdict_projection(old_verdict) != _verdict_projection(new_verdict)


def _backup_path(verdict_path: Path, timestamp: str) -> Path:
    return verdict_path.with_name(f"verdict.json.pre-reverify-{timestamp}.bak")


def reverify_trial(
    trial_dir: Path | str,
    *,
    timeout: int = 300,
    write: bool = False,
    include_adapter_failed: bool = False,
    timestamp: str | None = None,
    vendor_dir: Path | str | None = None,
) -> dict[str, Any]:
    trial_dir = Path(trial_dir)
    verdict_path = trial_dir / "verdict.json"
    manifest_path = trial_dir / "manifest.json"
    workdir = trial_dir / "workdir"
    suite_name = _trial_suite_name(trial_dir)
    if not suite_name:
        return {"status": "error", "error": "could not infer suite", "path": str(trial_dir)}

    old_verdict = _load_json(verdict_path)
    manifest = _load_json(manifest_path)
    if old_verdict is None or manifest is None or not workdir.is_dir():
        return {"status": "skipped_missing_artifacts", "path": str(trial_dir)}
    if old_verdict.get("adapter_failed") and not include_adapter_failed:
        return {"status": "skipped_adapter_failed", "path": str(trial_dir)}

    task_data = _task_data_from_manifest(trial_dir, manifest, timeout=timeout)
    if task_data is None:
        return {"status": "error", "error": "could not infer task id", "path": str(trial_dir)}

    canonical_verifier = False
    dataset: dict[str, Any] | None = None
    try:
        suite = load_suite(suite_name)
        if suite_name == "aider_polyglot" and vendor_dir is not None:
            with tempfile.TemporaryDirectory(prefix="cospa-reverify-canonical-") as tmp:
                canonical_workdir = Path(tmp) / "workdir"
                canonical_task_data = suite.materialize_task(
                    task_data["task_id"],
                    canonical_workdir,
                    Path(vendor_dir),
                )
                for key in ("model_id", "thinking", "timeout"):
                    if key in task_data:
                        canonical_task_data[key] = task_data[key]
                dataset_value = canonical_task_data.get("dataset")
                if isinstance(dataset_value, dict):
                    dataset = dataset_value
                new_verdict = suite.verify(canonical_task_data, workdir)
            canonical_verifier = True
        else:
            new_verdict = suite.verify(task_data, workdir)
    except Exception as exc:
        return {"status": "error", "error": str(exc), "path": str(trial_dir)}

    changed = _verdict_changed(old_verdict, new_verdict)
    result: dict[str, Any] = {
        "status": "changed" if changed else "unchanged",
        "path": str(trial_dir),
        "old": _verdict_projection(old_verdict),
        "new": _verdict_projection(new_verdict),
        "canonical_verifier": canonical_verifier,
    }
    if dataset is not None:
        result["dataset"] = dataset
    if not new_verdict.get("passed"):
        grader_output = new_verdict.get("grader_output")
        if isinstance(grader_output, str):
            result["new_grader_output_tail"] = grader_output[-8000:]
    if changed and write:
        timestamp = timestamp or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup = _backup_path(verdict_path, timestamp)
        suffix = 1
        while backup.exists():
            backup = verdict_path.with_name(
                f"verdict.json.pre-reverify-{timestamp}-{suffix}.bak"
            )
            suffix += 1
        shutil.copy2(verdict_path, backup)
        new_verdict = dict(new_verdict)
        new_verdict["reverified"] = {
            "at": datetime.now(timezone.utc).isoformat(),
            "source": "harness.reverify_results",
            "previous": _verdict_projection(old_verdict),
            "backup": backup.name,
        }
        _write_json_atomic(verdict_path, new_verdict)
        result["updated"] = True
        result["backup"] = str(backup)
    else:
        result["updated"] = False
    return result


def reverify_results(
    results_dir: Path | str,
    *,
    filters: tuple[str, ...] = (),
    excludes: tuple[str, ...] = (),
    suites: tuple[str, ...] = (),
    timeout: int = 300,
    write: bool = False,
    include_adapter_failed: bool = False,
    limit: int | None = None,
    vendor_dir: Path | str | None = None,
) -> dict[str, Any]:
    results_dir = Path(results_dir).resolve()
    suite_filter = set(suites)
    summary: dict[str, Any] = {key: 0 for key in SUMMARY_KEYS}
    summary["changes"] = []
    matched_runs: dict[tuple[str, str, str, str, str, str], dict[str, Any]] = {}

    for trial_dir in _iter_trial_dirs(results_dir):
        if limit is not None and summary["scanned"] >= limit:
            break
        if not _matches(trial_dir, filters, excludes):
            continue
        summary["scanned"] += 1
        suite_name = _trial_suite_name(trial_dir)
        if suite_filter and suite_name not in suite_filter:
            summary["skipped_suite"] += 1
            continue

        manifest = _load_json(trial_dir / "manifest.json")
        run_info = _matched_run_info(results_dir, trial_dir, manifest)
        run_key = _matched_run_key(run_info)
        if run_key not in matched_runs:
            matched_runs[run_key] = {**run_info, "trials": 0}
        matched_runs[run_key]["trials"] += 1

        result = reverify_trial(
            trial_dir,
            timeout=timeout,
            write=write,
            include_adapter_failed=include_adapter_failed,
            vendor_dir=vendor_dir,
        )
        status = result.get("status")
        if status == "changed":
            summary["changed"] += 1
            summary["reverified"] += 1
            summary["changes"].append(result)
            if result.get("updated"):
                summary["updated"] += 1
        elif status == "unchanged":
            summary["unchanged"] += 1
            summary["reverified"] += 1
        elif status in summary:
            summary[status] += 1
        else:
            summary["errors"] += 1
    summary["matched_runs"] = [
        matched_runs[key] for key in sorted(matched_runs)
    ]
    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Re-run suite verifiers against existing result workdirs. "
            "Dry-run by default; pass --write to replace changed verdicts."
        )
    )
    parser.add_argument(
        "--results-dir",
        default=Path(__file__).resolve().parent.parent / "results",
        help="Results directory or run wrapper to scan",
    )
    parser.add_argument("--suite", action="append", default=[], help="Suite to include")
    parser.add_argument("--filter", action="append", default=[], help="Regex path filter")
    parser.add_argument("--exclude", action="append", default=[], help="Regex path exclude")
    parser.add_argument("--timeout", type=int, default=300, help="Verifier timeout seconds")
    parser.add_argument("--limit", type=int, default=None, help="Maximum matching trials to scan")
    parser.add_argument("--write", action="store_true", help="Replace changed verdict.json files")
    parser.add_argument(
        "--vendor-dir",
        default=None,
        help=(
            "Materialize canonical Aider verifier inputs from this vendor directory "
            "instead of grading saved model-edited tests"
        ),
    )
    parser.add_argument(
        "--include-adapter-failed",
        action="store_true",
        help="Also reverify trials marked adapter_failed",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    summary = reverify_results(
        args.results_dir,
        filters=tuple(args.filter),
        excludes=tuple(args.exclude),
        suites=tuple(args.suite),
        timeout=args.timeout,
        write=args.write,
        include_adapter_failed=args.include_adapter_failed,
        limit=args.limit,
        vendor_dir=args.vendor_dir,
    )

    mode = "write" if args.write else "dry-run"
    print(f"Reverify results ({mode})")
    print(f"Results: {Path(args.results_dir).resolve()}")
    print("Matched runs:")
    if summary["matched_runs"]:
        for run in summary["matched_runs"]:
            run_name = run["run"] or "(root)"
            print(
                "- "
                f"{run_name} | {run['model']} | {run['adapter']} | "
                f"{run['suite']} | thinking={run['thinking']} | "
                f"provider={run['provider']} | trials={run['trials']}"
            )
    else:
        print("- none")
    for key in SUMMARY_KEYS:
        print(f"{key}: {summary[key]}")
    for change in summary["changes"]:
        print(
            "changed: "
            f"{change['path']} "
            f"{change['old']} -> {change['new']}"
        )
    return 1 if summary["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
