"""Tests for backfilling usage metadata into existing result manifests."""

import json
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from harness.backfill_usage import backfill_results
from harness.path_utils import encode_model_path, encode_task_path
from harness.telemetry import pi_session_dir_for_cwd


def _write_trial(results_dir: Path) -> tuple[Path, Path]:
    trial_dir = (
        results_dir
        / encode_model_path("local/ornith-1.0-35b")
        / "pi_vanilla"
        / "aider_polyglot"
        / encode_task_path("python/two-fer")
        / "trial-1"
    )
    (trial_dir / "workdir").mkdir(parents=True)
    (trial_dir / "out").mkdir()
    (trial_dir / "manifest.json").write_text(json.dumps({
        "model": {
            "id": "local/ornith-1.0-35b",
            "provider": "local",
            "served_model": "local/ornith-1.0-35b",
        },
        "adapter": {"id": "PiVanillaAdapter", "version": "vanilla"},
        "suite": {"id": "AiderPolyglotSuite", "task_id": "python/two-fer"},
        "sampling": {"thinking": "high"},
        "timing": {"wall_clock_seconds": 10.0},
        "token_usage": {},
        "created_at": "2026-07-04T14:07:00+00:00",
        "run_end_time": "2026-07-04T14:08:00+00:00",
    }, indent=2))
    (trial_dir / "verdict.json").write_text(json.dumps({"passed": True}))
    return trial_dir, trial_dir / "manifest.json"


def _write_session(sessions_root: Path, workdir: Path) -> None:
    session_dir = pi_session_dir_for_cwd(workdir, sessions_root=sessions_root)
    session_dir.mkdir(parents=True)
    (session_dir / "session.jsonl").write_text("\n".join([
        json.dumps({
            "type": "session",
            "id": "session-1",
            "timestamp": "2026-07-04T14:07:01Z",
            "cwd": str(workdir),
        }),
        json.dumps({
            "type": "message",
            "message": {
                "provider": "local",
                "model": "Ornith-1.0-35B",
                "responseId": "chatcmpl-one",
                "responseModel": "ornith-35b-fp8-block",
                "usage": {
                    "input": 100,
                    "output": 25,
                    "cacheRead": 50,
                    "reasoning": 5,
                    "totalTokens": 180,
                    "cost": {"total": 0.001},
                },
            },
        }),
    ]) + "\n")


def test_backfill_results_updates_manifest_and_copies_trace():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        results_dir = tmp / "results"
        sessions_root = tmp / "sessions"
        trial_dir, manifest_path = _write_trial(results_dir)
        _write_session(sessions_root, trial_dir / "workdir")

        summary = backfill_results(results_dir, sessions_root=sessions_root)
        manifest = json.loads(manifest_path.read_text())
        copied_trace_exists = (trial_dir / "out" / "pi_session.jsonl").exists()

    assert summary["scanned"] == 1
    assert summary["updated"] == 1
    assert summary["observed"] == 1
    assert manifest["token_usage"]["status"] == "observed"
    assert manifest["token_usage"]["prompt_tokens"] == 100
    assert manifest["token_usage"]["cached_tokens"] == 50
    assert manifest["token_usage"]["reasoning_tokens"] == 5
    assert manifest["token_usage"]["cost_usd"] == 0.001
    assert manifest["model"]["served_model"] == "ornith-35b-fp8-block"
    assert manifest["sampling"]["thinking_token_budget"] == 8192
    assert copied_trace_exists


def test_backfill_results_does_not_overwrite_observed_usage_by_default():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        results_dir = tmp / "results"
        sessions_root = tmp / "sessions"
        trial_dir, manifest_path = _write_trial(results_dir)
        manifest = json.loads(manifest_path.read_text())
        manifest["token_usage"] = {
            "source": "manual",
            "status": "observed",
            "prompt_tokens": 1,
        }
        manifest_path.write_text(json.dumps(manifest, indent=2))
        _write_session(sessions_root, trial_dir / "workdir")

        summary = backfill_results(results_dir, sessions_root=sessions_root)
        updated = json.loads(manifest_path.read_text())

    assert summary["skipped_observed"] == 1
    assert updated["token_usage"]["source"] == "manual"
    assert updated["token_usage"]["prompt_tokens"] == 1
