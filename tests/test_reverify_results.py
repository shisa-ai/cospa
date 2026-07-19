"""Tests for reverifying existing result verdicts."""

import json
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from harness.path_utils import encode_model_path, encode_task_path
from harness.reverify_results import main, reverify_results


def _write_python_trial(
    results_dir: Path,
    *,
    passed: bool,
    adapter_failed: bool = False,
    model_id: str = "codex/gpt-5.5",
    provider: str = "codex",
    adapter: str = "pi_devstack",
    run_id: str = "codex%2Fgpt-5.5-smoke",
    task_id: str = "python/two-fer",
) -> Path:
    trial_dir = (
        results_dir
        / "runs"
        / run_id
        / encode_model_path(model_id)
        / adapter
        / "aider_polyglot"
        / encode_task_path(task_id)
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
        "model": {"id": model_id, "provider": provider},
        "adapter": {"id": "PiDevstackAdapter", "version": "devstack"},
        "suite": {"id": "AiderPolyglotSuite", "task_id": task_id},
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


def test_reverify_results_uses_canonical_vendor_tests(make_polyglot_problem):
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        results_dir = root / "results"
        vendor_dir = root / "vendor"
        make_polyglot_problem(
            vendor_dir,
            "python",
            "two-fer",
            starter_name="two_fer",
            starter_content="def two_fer(name='you'):\n    pass\n",
            test_content=(
                "from two_fer import two_fer\n\n"
                "def test_default():\n"
                "    assert two_fer() == 'One for you, one for me.'\n"
            ),
        )
        trial_dir = _write_python_trial(results_dir, passed=True)
        (trial_dir / "workdir" / "two_fer.py").write_text(
            "def two_fer(name='you'):\n    return 'wrong'\n"
        )
        (trial_dir / "workdir" / "two_fer_test.py").write_text(
            "def test_model_edited():\n    assert True\n"
        )

        summary = reverify_results(
            results_dir,
            suites=("aider_polyglot",),
            vendor_dir=vendor_dir,
        )

    assert summary["scanned"] == 1
    assert summary["changed"] == 1
    assert summary["changes"][0]["old"]["passed"] is True
    assert summary["changes"][0]["new"]["passed"] is False
    assert summary["changes"][0]["canonical_verifier"] is True


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


def test_reverify_results_reports_matched_run_cells():
    with tempfile.TemporaryDirectory() as tmp:
        results_dir = Path(tmp) / "results"
        _write_python_trial(
            results_dir,
            passed=True,
            model_id="zai/glm-5.2",
            provider="zai",
            adapter="pi_vanilla",
            run_id="zai%2Fglm-5.2-full-20260704",
        )
        _write_python_trial(
            results_dir,
            passed=True,
            model_id="zai/glm-5.2",
            provider="zai",
            adapter="pi_devstack",
            run_id="zai%2Fglm-5.2-full-20260704",
            task_id="python/hello-world",
        )
        _write_python_trial(
            results_dir,
            passed=True,
            model_id="local/ornith-1.0-35b",
            provider="local",
            adapter="pi_vanilla",
            run_id="local%2Fornith-1.0-35b-full-20260704",
        )

        summary = reverify_results(
            results_dir,
            suites=("aider_polyglot",),
            filters=("glm-5\\.2",),
        )

    matched = summary["matched_runs"]
    assert [row["adapter"] for row in matched] == ["pi_devstack", "pi_vanilla"]
    assert {row["model"] for row in matched} == {"zai/glm-5.2"}
    assert {row["run"] for row in matched} == {"runs/zai%2Fglm-5.2-full-20260704"}
    assert all(row["trials"] == 1 for row in matched)


def test_reverify_cli_prints_matched_runs(capsys):
    with tempfile.TemporaryDirectory() as tmp:
        results_dir = Path(tmp) / "results"
        _write_python_trial(
            results_dir,
            passed=True,
            model_id="zai/glm-5.2",
            provider="zai",
            adapter="pi_vanilla",
            run_id="zai%2Fglm-5.2-full-20260704",
        )

        rc = main([
            "--results-dir",
            str(results_dir),
            "--suite",
            "aider_polyglot",
            "--filter",
            "glm-5\\.2",
        ])

    out = capsys.readouterr().out
    assert rc == 0
    assert "Matched runs:" in out
    assert "runs/zai%2Fglm-5.2-full-20260704" in out
    assert "zai/glm-5.2 | pi_vanilla | aider_polyglot" in out
