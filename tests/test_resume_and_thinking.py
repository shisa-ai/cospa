"""
Tests for resume-skip and configurable thinking/effort.

Two capabilities that the runner currently lacks but that the live
full-20260704 eval needs:

1. **Resume.** Re-running the same `(model, adapter, suite, task, k)`
   with an existing `verdict.json` MUST skip the trial rather than
   re-execute (and overwrite) it. Without this, restarting a killed
   run wastes every trial already completed.

2. **Configurable thinking/effort.** `pi_vanilla` MUST pass
   `--thinking <level>` when the runner is invoked with `--thinking`,
   and the level MUST be recorded in the manifest's `sampling` block so
   runs at different effort are comparable and distinguishable.

Both tests are RED against the current codebase.
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from harness.adapters.pi_vanilla import PiVanillaAdapter, AdapterResult
from harness.suites.aider_polyglot import AiderPolyglotSuite
from harness.runner import run_trial


def _make_aider_problem(vendor_dir: Path):
    """Build a real-shaped polyglot-benchmark problem (mirrors test_runner_failure)."""
    pdir = (
        vendor_dir
        / "polyglot-benchmark"
        / "python"
        / "exercises"
        / "practice"
        / "two-fer"
    )
    pdir.mkdir(parents=True)
    (pdir / ".docs").mkdir()
    (pdir / ".docs" / "instructions.md").write_text("Write a two-fer function")
    (pdir / "two_fer.py").write_text("def two_fer(name=None):\n    pass\n")
    (pdir / "two_fer_test.py").write_text(
        "from two_fer import two_fer\n"
        "def test_two_fer():\n    assert two_fer() == 'One for you, one for me.'"
    )


class CountingAdapter:
    """Adapter that records how many times run() was invoked."""

    name = "counting"
    version = "test"

    def __init__(self):
        self.run_count = 0

    def run(self, task_data, workdir, log_file, stderr_file):
        self.run_count += 1
        # Write a stub solution so verification would pass if it ran.
        (workdir / "two_fer.py").write_text(
            "def two_fer(name=None):\n"
            "    if name is None:\n        return 'One for you, one for me.'\n"
        )
        return AdapterResult(returncode=0)


def test_run_trial_skips_when_verdict_already_exists():
    """RED: re-running a completed trial must NOT re-invoke the adapter.

    The trial_dir is deterministic in (results_dir, model, adapter, suite,
    task, k). If `verdict.json` is already present, the second run_trial
    call for the same key MUST return without calling the adapter again.
    """
    suite = AiderPolyglotSuite()
    adapter = CountingAdapter()

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        vendor_dir = tmp / "vendor"
        vendor_dir.mkdir()
        _make_aider_problem(vendor_dir)
        results_dir = tmp / "results"

        # First run: executes the trial, writes verdict.json.
        run_trial(
            suite, adapter, "test/model", "python/two-fer", 1,
            results_dir, vendor_dir,
        )
        assert adapter.run_count == 1, "first run should execute once"

        # Sanity: a verdict was written at the deterministic trial dir.
        # trial_dir layout: results/<encoded_model>/<adapter>/<suite>/<encoded_task>/trial-<k>
        from urllib.parse import quote
        encoded_model = quote("test/model", safe="")
        encoded_task = quote("python/two-fer", safe="")
        trial_dir = (
            results_dir
            / encoded_model
            / adapter.name
            / suite.name
            / encoded_task
            / "trial-1"
        )
        assert (trial_dir / "verdict.json").exists(), (
            "test setup: first run must write verdict.json"
        )

        # Second run: same key. MUST skip — adapter must not run again.
        run_trial(
            suite, adapter, "test/model", "python/two-fer", 1,
            results_dir, vendor_dir,
        )
        assert adapter.run_count == 1, (
            f"resume: adapter must NOT re-run when verdict.json exists; "
            f"got run_count={adapter.run_count}"
        )


def test_pi_vanilla_passes_thinking_flag_when_configured():
    """RED: pi_vanilla MUST add `--thinking <level>` when task_data sets it."""
    adapter = PiVanillaAdapter()

    captured_cmd = {}

    def fake_run(cmd, *args, **kwargs):
        captured_cmd["cmd"] = list(cmd)
        class _R:
            returncode = 0
        return _R()

    with tempfile.TemporaryDirectory() as tmp:
        with patch("harness.adapters.pi_vanilla.subprocess.run", fake_run):
            adapter.run(
                task_data={
                    "prompt": "do thing",
                    "model_id": "test/model",
                    "thinking": "high",
                },
                workdir=Path(tmp),
                log_file=Path(tmp) / "out.log",
                stderr_file=Path(tmp) / "err.log",
            )

    cmd = captured_cmd["cmd"]
    assert "--thinking" in cmd, (
        f"pi_vanilla cmd must include --thinking when task_data['thinking'] "
        f"is set; got {cmd}"
    )
    idx = cmd.index("--thinking")
    assert cmd[idx + 1] == "high", (
        f"--thinking must be followed by the level ('high'); got {cmd}"
    )


def test_pi_vanilla_omits_thinking_flag_when_unset():
    """RED: when thinking is unset, pi_vanilla MUST NOT pass --thinking."""
    adapter = PiVanillaAdapter()

    captured_cmd = {}

    def fake_run(cmd, *args, **kwargs):
        captured_cmd["cmd"] = list(cmd)
        class _R:
            returncode = 0
        return _R()

    with tempfile.TemporaryDirectory() as tmp:
        with patch("harness.adapters.pi_vanilla.subprocess.run", fake_run):
            adapter.run(
                task_data={"prompt": "do thing", "model_id": "test/model"},
                workdir=Path(tmp),
                log_file=Path(tmp) / "out.log",
                stderr_file=Path(tmp) / "err.log",
            )

    assert "--thinking" not in captured_cmd["cmd"], (
        f"pi_vanilla must NOT add --thinking when unset; got {captured_cmd['cmd']}"
    )


def test_manifest_records_thinking_level():
    """RED: manifest['sampling']['thinking'] MUST record the configured level."""
    suite = AiderPolyglotSuite()

    class _OkAdapter:
        name = "ok"
        version = "test"

        def run(self, task_data, workdir, log_file, stderr_file):
            (workdir / "two_fer.py").write_text(
                "def two_fer(name=None):\n"
                "    if name is None:\n        return 'One for you, one for me.'\n"
            )
            return AdapterResult(returncode=0)

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        vendor_dir = tmp / "vendor"
        vendor_dir.mkdir()
        _make_aider_problem(vendor_dir)
        results_dir = tmp / "results"

        manifest, _ = run_trial(
            suite, _OkAdapter(), "test/model", "python/two-fer", 1,
            results_dir, vendor_dir, thinking="high",
        )

    sampling = manifest.get("sampling", {})
    assert sampling.get("thinking") == "high", (
        f"manifest.sampling.thinking must record 'high' when --thinking high; "
        f"got sampling={sampling}"
    )
