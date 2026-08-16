"""Backfill Harbor agent-phase verdicts that predate the deadline fix.

Trials run before commit ``531d457`` ("classify Harbor agent deadlines as
budget exhaustion") recorded ``AgentTimeoutError`` agent exceptions as generic
adapter failures (``exit -1``, no ``failure_class``) even though the job
evidence already carried the exception type. This backfill derives the correct
verdict from that evidence:

- ``AgentTimeoutError`` → budget exhaustion: manifest ``exit_code=124`` /
  ``budget_exhausted=True`` and the runner's post-fix verdict shape
  (``failure_class="budget_exhausted"``).
- Other agent exceptions (e.g. ``NonZeroAgentExitCodeError``) → re-classify the
  verdict's ``failure_class`` from the manifest error surface via
  :func:`harness.failure_classify.classify_failure` (e.g. a provider
  ``Connection error.`` surfaces as ``connection_error``).

Only trials that carry a ``harbor_agent_exception`` are touched; verifier-graded
trials are left alone. The operation is idempotent and records provenance.
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from harness.failure_classify import classify_failure

BACKFILL_MARKER = "backfill-harbor-verdicts"


def _write_atomic(path: Path, payload: dict) -> None:
    temp_path = path.with_name(f"{path.name}.tmp")
    temp_path.write_text(json.dumps(payload, indent=2) + "\n")
    temp_path.replace(path)


def _manifest_paths(results_dir: Path):
    for manifest_path in results_dir.rglob("manifest.json"):
        trial_dir = manifest_path.parent
        if re.fullmatch(r"trial-\d+", trial_dir.name):
            yield manifest_path


def _matches(path: Path, filters: tuple[str, ...], excludes: tuple[str, ...]) -> bool:
    text = path.as_posix()
    for pattern in filters:
        if not re.search(pattern, text):
            return False
    for pattern in excludes:
        if re.search(pattern, text):
            return False
    return True


def derive_corrected(manifest: dict, verdict: dict) -> tuple[dict, dict] | None:
    """Return corrected (manifest, verdict) from job evidence, or None.

    Returns None when the trial has no Harbor agent exception, is already
    correct, or cannot be re-classified from evidence.
    """
    exc = manifest.get("harbor_agent_exception")
    if not isinstance(exc, dict) or not exc.get("exception_type"):
        return None

    new_manifest: dict = dict(manifest)
    new_verdict: dict | None = None

    if exc["exception_type"] == "AgentTimeoutError":
        already_budget = (
            verdict.get("budget_exhausted") is True
            and manifest.get("budget_exhausted") is True
            and manifest.get("exit_code") == 124
        )
        if already_budget:
            return None
        error = manifest.get("error") or "Agent capability budget exhausted"
        new_verdict = {
            "passed": False,
            "test_count": 0,
            "grader_output": error,
            "exit_code": 124,
            "budget_exhausted": True,
            "failure_class": "budget_exhausted",
        }
        new_manifest["exit_code"] = 124
        new_manifest["budget_exhausted"] = True
    else:
        cls = classify_failure(verdict, manifest)
        if cls in {"incorrect", "adapter_error_other"}:
            return None
        if verdict.get("failure_class") == cls:
            return None
        new_verdict = dict(verdict)
        new_verdict["failure_class"] = cls
        new_verdict["backfilled_failure_class"] = True

    new_manifest["backfill"] = {
        "script": BACKFILL_MARKER,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    return new_manifest, new_verdict


def backfill_manifest(
    manifest_path: Path,
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Backfill one trial's manifest+verdict; return a status summary."""
    manifest_path = Path(manifest_path)
    trial_dir = manifest_path.parent
    verdict_path = trial_dir / "verdict.json"
    try:
        manifest = json.loads(manifest_path.read_text())
        verdict = json.loads(verdict_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        return {"status": "error", "error": str(exc), "path": str(manifest_path)}

    corrected = derive_corrected(manifest, verdict)
    if corrected is None:
        return {"status": "unchanged", "updated": False, "path": str(manifest_path)}

    new_manifest, new_verdict = corrected
    if not dry_run:
        _write_atomic(manifest_path, new_manifest)
        _write_atomic(verdict_path, new_verdict)
    return {
        "status": "updated",
        "updated": True,
        "path": str(manifest_path),
        "failure_class": new_verdict.get("failure_class"),
    }


def backfill_results(
    results_dir: Path | str,
    *,
    filters: tuple[str, ...] = (),
    excludes: tuple[str, ...] = (),
    dry_run: bool = False,
) -> dict[str, int]:
    """Backfill every Harbor agent-exception trial under a results directory."""
    results_dir = Path(results_dir).resolve()
    summary = {"scanned": 0, "updated": 0, "unchanged": 0, "error": 0}
    for manifest_path in _manifest_paths(results_dir):
        if not _matches(manifest_path, filters, excludes):
            continue
        summary["scanned"] += 1
        result = backfill_manifest(manifest_path, dry_run=dry_run)
        status = result["status"]
        if status in summary:
            summary[status] += 1
    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backfill Harbor agent-phase verdicts from job evidence"
    )
    parser.add_argument(
        "--results-dir",
        default=Path(__file__).resolve().parent.parent / "results",
        help="Results directory or run wrapper to scan",
    )
    parser.add_argument("--filter", action="append", default=[], help="Regex path filter")
    parser.add_argument("--exclude", action="append", default=[], help="Regex path exclude")
    parser.add_argument("--dry-run", action="store_true", help="Report only; do not write files")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    summary = backfill_results(
        args.results_dir,
        filters=tuple(args.filter),
        excludes=tuple(args.exclude),
        dry_run=args.dry_run,
    )
    for key in ("scanned", "updated", "unchanged", "error"):
        print(f"{key}: {summary.get(key, 0)}")
    return 1 if summary.get("error") else 0


if __name__ == "__main__":
    raise SystemExit(main())
