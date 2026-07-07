"""Tests for reverifying existing result verdicts."""

import json
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from harness.path_utils import encode_model_path, encode_task_path
from harness.reverify_results import reverify_results


def _write_python_trial(
    results_dir: Path,
    *,
    passed: bool,
    adapter_failed: bool = False,
) -> Path:
    trial_dir = (
        results_dir
        / "runs"
        / "codex%2Fgpt-5.5-smoke"
        / encode_model_path("codex/gpt-5.5")
        / "pi_devstack"
        / "aider_polyglot"
        / encode_task_path("python/two-fer")
        / "trial-1"
    )
    workdir = trial_dir / "workdir"
    workdir.mkdir(parents=True)
    (workdir / "two_fer.py").write_text(
        "def two_fer(name='you'):\n"
        "    return f'One for {name}, one for me.'\n"
    )
    (workdir / "two_fer_test.py").write_text(
        "from two_fer import two_fer\n\n"
        "def test_default():\n"
        "    assert two_fer() == 'One for you, one for me.'\n"
    )
    (trial_dir / "manifest.json").write_text(json.dumps({
        "model": {"id": "codex/gpt-5.5", "provider": "codex"},
        "adapter": {"id": "PiDevstackAdapter", "version": "devstack"},
        "suite": {"id": "AiderPolyglotSuite", "task_id": "python/two-fer"},
        "trial": 1,
        "sampling": {"thinking": "medium"},
        "timing": {"wall_clock_seconds": 12.0},
    }, indent=2))
    (trial_dir / "verdict.json").write_text(json.dumps({
        "passed": passed,
        "test_count": 0 if not passed else 1,
        "grader_output": "old",
        "exit_code": 1 if not passed else 0,
        **({"adapter_failed": True} if adapter_failed else {}),
    }, indent=2))
    return trial_dir


def test_reverify_results_dry_run_reports_changed_verdict_without_writing():
    with tempfile.TemporaryDirectory() as tmp:
        results_dir = Path(tmp) / "results"
        trial_dir = _write_python_trial(results_dir, passed=False)

        summary = reverify_results(results_dir, suites=("aider_polyglot",))
        stored = json.loads((trial_dir / "verdict.json").read_text())

    assert summary["scanned"] == 1
    assert summary["changed"] == 1
    assert summary["updated"] == 0
    assert summary["changes"][0]["old"]["passed"] is False
    assert summary["changes"][0]["new"]["passed"] is True
    assert stored["passed"] is False


def test_reverify_results_write_backs_up_and_replaces_changed_verdict():
    with tempfile.TemporaryDirectory() as tmp:
        results_dir = Path(tmp) / "results"
        trial_dir = _write_python_trial(results_dir, passed=False)

        summary = reverify_results(
            results_dir,
            suites=("aider_polyglot",),
            write=True,
        )
        stored = json.loads((trial_dir / "verdict.json").read_text())
        backups = sorted(trial_dir.glob("verdict.json.pre-reverify-*.bak"))

    assert summary["scanned"] == 1
    assert summary["changed"] == 1
    assert summary["updated"] == 1
    assert stored["passed"] is True
    assert stored["reverified"]["previous"]["passed"] is False
    assert len(backups) == 1


def test_reverify_results_skips_adapter_failed_trials_by_default():
    with tempfile.TemporaryDirectory() as tmp:
        results_dir = Path(tmp) / "results"
        trial_dir = _write_python_trial(
            results_dir,
            passed=False,
            adapter_failed=True,
        )

        summary = reverify_results(results_dir, suites=("aider_polyglot",))
        stored = json.loads((trial_dir / "verdict.json").read_text())

    assert summary["scanned"] == 1
    assert summary["skipped_adapter_failed"] == 1
    assert summary["changed"] == 0
    assert stored["adapter_failed"] is True
