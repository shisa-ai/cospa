"""Backfill token usage and trace metadata into existing result manifests."""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from harness.telemetry import (
    collect_pi_session_usage,
    load_model_metadata,
    thinking_token_budget,
)


def _parse_time(value: str | None) -> float | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except ValueError:
        return None


def _manifest_paths(results_dir: Path):
    yield from results_dir.rglob("manifest.json")


def _matches(path: Path, filters: tuple[str, ...], excludes: tuple[str, ...]) -> bool:
    text = path.as_posix()
    for pattern in filters:
        if not re.search(pattern, text):
            return False
    for pattern in excludes:
        if re.search(pattern, text):
            return False
    return True


def _write_manifest(path: Path, manifest: dict) -> None:
    temp_path = path.with_name(f"{path.name}.tmp")
    temp_path.write_text(json.dumps(manifest, indent=2) + "\n")
    temp_path.replace(path)


def _usage_observed(manifest: dict) -> bool:
    usage = manifest.get("token_usage")
    return isinstance(usage, dict) and usage.get("status") == "observed"


def _merge_model_metadata(manifest: dict) -> bool:
    model = manifest.get("model")
    if not isinstance(model, dict):
        return False
    model_id = model.get("id")
    if not isinstance(model_id, str):
        return False

    metadata = load_model_metadata(model_id)
    changed = False
    for key, value in metadata.items():
        if model.get(key) != value:
            model[key] = value
            changed = True
    return changed


def _merge_thinking_budget(manifest: dict) -> bool:
    sampling = manifest.get("sampling")
    if not isinstance(sampling, dict):
        return False
    budget = thinking_token_budget(sampling.get("thinking"))
    if budget is None:
        return False
    if sampling.get("thinking_token_budget") == budget:
        return False
    sampling["thinking_token_budget"] = budget
    return True


def backfill_manifest(
    manifest_path: Path | str,
    *,
    sessions_root: Path | str | None = None,
    overwrite: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Backfill one manifest and return a status summary."""
    manifest_path = Path(manifest_path)
    trial_dir = manifest_path.parent
    try:
        manifest = json.loads(manifest_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        return {"status": "error", "error": str(exc), "path": str(manifest_path)}

    changed = False
    changed |= _merge_model_metadata(manifest)
    changed |= _merge_thinking_budget(manifest)

    if _usage_observed(manifest) and not overwrite:
        if changed and not dry_run:
            _write_manifest(manifest_path, manifest)
        return {
            "status": "skipped_observed",
            "updated": changed,
            "path": str(manifest_path),
        }

    usage = collect_pi_session_usage(
        trial_dir / "workdir",
        trial_dir / "out",
        sessions_root=sessions_root,
        start_time=_parse_time(manifest.get("created_at")),
        end_time=_parse_time(manifest.get("run_end_time")),
    )
    if usage.get("status") == "observed":
        manifest["token_usage"] = usage
        response_models = usage.get("response_models")
        model = manifest.get("model")
        if isinstance(model, dict) and isinstance(response_models, list) and response_models:
            model["served_model"] = response_models[-1]
        changed = True
        status = "observed"
    else:
        status = "unavailable"
        if not manifest.get("token_usage"):
            manifest["token_usage"] = usage
            changed = True

    if changed and not dry_run:
        _write_manifest(manifest_path, manifest)
    return {
        "status": status,
        "updated": changed,
        "path": str(manifest_path),
    }


def backfill_results(
    results_dir: Path | str,
    *,
    sessions_root: Path | str | None = None,
    filters: tuple[str, ...] = (),
    excludes: tuple[str, ...] = (),
    overwrite: bool = False,
    dry_run: bool = False,
) -> dict[str, int]:
    """Backfill every manifest under a results directory."""
    results_dir = Path(results_dir)
    summary = {
        "scanned": 0,
        "updated": 0,
        "observed": 0,
        "unavailable": 0,
        "skipped_observed": 0,
        "errors": 0,
    }
    for manifest_path in _manifest_paths(results_dir):
        if not _matches(manifest_path, filters, excludes):
            continue
        summary["scanned"] += 1
        result = backfill_manifest(
            manifest_path,
            sessions_root=sessions_root,
            overwrite=overwrite,
            dry_run=dry_run,
        )
        status = result["status"]
        if status in summary:
            summary[status] += 1
        if result.get("updated"):
            summary["updated"] += 1
        if status == "error":
            summary["errors"] += 1
    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill usage from pi JSONL sessions")
    parser.add_argument(
        "--results-dir",
        default=Path(__file__).resolve().parent.parent / "results",
        help="Results directory or run wrapper to scan",
    )
    parser.add_argument(
        "--sessions-root",
        default=None,
        help="pi sessions root (defaults to ~/.pi/agent/sessions)",
    )
    parser.add_argument("--filter", action="append", default=[], help="Regex path filter")
    parser.add_argument("--exclude", action="append", default=[], help="Regex path exclude")
    parser.add_argument("--overwrite", action="store_true", help="Replace observed usage")
    parser.add_argument("--dry-run", action="store_true", help="Report only; do not write manifests")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    summary = backfill_results(
        args.results_dir,
        sessions_root=args.sessions_root,
        filters=tuple(args.filter),
        excludes=tuple(args.exclude),
        overwrite=args.overwrite,
        dry_run=args.dry_run,
    )
    for key in ("scanned", "updated", "observed", "unavailable", "skipped_observed", "errors"):
        print(f"{key}: {summary[key]}")
    return 1 if summary["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
