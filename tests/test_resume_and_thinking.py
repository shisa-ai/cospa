"""
Tests for resume-skip and configurable thinking/effort.

Two capabilities that the runner currently lacks but that the live
full-20260704 eval needs:

1. **Resume.** Re-running the same `(model, adapter, suite, task, k)`
   with existing durable artifacts MUST skip the trial rather than
   re-execute (and overwrite) it. Without this, restarting a killed
   run wastes every trial already completed. A partial artifact set
   (for example, verdict without manifest) MUST be rerun.

2. **Configurable thinking/effort.** `pi_vanilla` MUST pass
   `--thinking <level>` when the runner is invoked with `--thinking`,
   and the level MUST be recorded in the manifest's `sampling` block so
   runs at different effort are comparable and distinguishable.

Both tests are RED against the current codebase.
"""

import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from harness.adapters.little_coder import LittleCoderAdapter
from harness.adapters.little_coder_superpowers import LittleCoderSuperpowersAdapter
from harness.adapters.pi_devstack import PiDevstackAdapter
from harness.adapters.pi_devstack_superpowers import PiDevstackSuperpowersAdapter
from harness.adapters.pi_superpowers import PiSuperpowersAdapter
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
    task, k). If `verdict.json` and `manifest.json` are already present,
    the second run_trial call for the same key MUST return without calling
    the adapter again.
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
        assert (trial_dir / "manifest.json").exists(), (
            "test setup: first run must write manifest.json"
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


def test_run_trial_reruns_when_manifest_missing():
    """Partial artifacts must not be treated as a resumable completed trial."""
    suite = AiderPolyglotSuite()
    adapter = CountingAdapter()

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        vendor_dir = tmp / "vendor"
        vendor_dir.mkdir()
        _make_aider_problem(vendor_dir)
        results_dir = tmp / "results"

        run_trial(
            suite, adapter, "test/model", "python/two-fer", 1,
            results_dir, vendor_dir,
        )

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
        (trial_dir / "manifest.json").unlink()

        run_trial(
            suite, adapter, "test/model", "python/two-fer", 1,
            results_dir, vendor_dir,
        )

        assert adapter.run_count == 2, (
            "resume: verdict-only partial trial must be rerun, got "
            f"run_count={adapter.run_count}"
        )
        assert (trial_dir / "manifest.json").exists()


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
        with patch("harness.adapters.pi_vanilla.run_command", fake_run):
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
        with patch("harness.adapters.pi_vanilla.run_command", fake_run):
            adapter.run(
                task_data={"prompt": "do thing", "model_id": "test/model"},
                workdir=Path(tmp),
                log_file=Path(tmp) / "out.log",
                stderr_file=Path(tmp) / "err.log",
            )

    assert "--thinking" not in captured_cmd["cmd"], (
        f"pi_vanilla must NOT add --thinking when unset; got {captured_cmd['cmd']}"
    )


def test_all_comparable_adapters_pass_thinking_flag_when_configured():
    """Every comparable adapter must forward pinned thinking/effort."""
    adapters = [
        PiVanillaAdapter(),
        PiDevstackAdapter(),
        PiDevstackSuperpowersAdapter(),
        PiSuperpowersAdapter(),
        LittleCoderAdapter(),
        LittleCoderSuperpowersAdapter(),
    ]

    for adapter in adapters:
        captured_cmd = {}

        def fake_run(cmd, *args, **kwargs):
            captured_cmd["cmd"] = list(cmd)

            class _R:
                returncode = 0

            return _R()

        with tempfile.TemporaryDirectory() as tmp:
            with patch(f"{adapter.__class__.__module__}.run_command", fake_run):
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
            f"{adapter.name} must include --thinking when task_data['thinking'] "
            f"is set; got {cmd}"
        )
        idx = cmd.index("--thinking")
        assert cmd[idx + 1] == "high", (
            f"{adapter.name} --thinking must be followed by 'high'; got {cmd}"
        )


def test_all_comparable_adapters_use_trial_local_session_dir():
    """Long result paths must not be flattened into a >255-byte session name."""
    adapters = [
        PiVanillaAdapter(),
        PiDevstackAdapter(),
        PiDevstackSuperpowersAdapter(),
        PiSuperpowersAdapter(),
        LittleCoderAdapter(),
        LittleCoderSuperpowersAdapter(),
    ]

    for adapter in adapters:
        captured_cmd = {}

        def fake_run(cmd, *args, **kwargs):
            captured_cmd["cmd"] = list(cmd)

            class _R:
                returncode = 0

            return _R()

        with tempfile.TemporaryDirectory() as tmp:
            trial_dir = (
                Path(tmp)
                / ("model-" + "m" * 60)
                / adapter.name
                / "aider_polyglot"
                / ("javascript%2F" + "parallel-letter-frequency")
                / "trial-1"
            )
            out_dir = trial_dir / "out"
            out_dir.mkdir(parents=True)
            workdir = trial_dir / "workdir"
            workdir.mkdir()
            log_file = out_dir / "session.log"
            stderr_file = out_dir / "stderr.log"

            with patch(f"{adapter.__class__.__module__}.run_command", fake_run):
                adapter.run(
                    task_data={"prompt": "do thing", "model_id": "test/model"},
                    workdir=workdir,
                    log_file=log_file,
                    stderr_file=stderr_file,
                )

            cmd = captured_cmd["cmd"]
            assert "--session-dir" in cmd, (
                f"{adapter.name} must use an explicit trial-local session dir; got {cmd}"
            )
            idx = cmd.index("--session-dir")
            assert Path(cmd[idx + 1]) == out_dir / "pi-sessions"
            assert max(len(part.encode()) for part in Path(cmd[idx + 1]).parts) <= 255


def test_all_comparable_adapters_request_workspace_sandbox():
    """Every Aider adapter must hide shared vendor and prior result trees."""
    adapters = [
        PiVanillaAdapter(),
        PiDevstackAdapter(),
        PiDevstackSuperpowersAdapter(),
        PiSuperpowersAdapter(),
        LittleCoderAdapter(),
        LittleCoderSuperpowersAdapter(),
    ]

    for adapter in adapters:
        captured_kwargs = {}

        def fake_run(cmd, *args, **kwargs):
            captured_kwargs.update(kwargs)

            class _R:
                returncode = 0

            return _R()

        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            with patch(f"{adapter.__class__.__module__}.run_command", fake_run):
                adapter.run(
                    task_data={
                        "prompt": "do thing",
                        "model_id": "test/model",
                        "problem": "two-fer",
                    },
                    workdir=workdir,
                    log_file=workdir / "out.log",
                    stderr_file=workdir / "err.log",
                )

            assert captured_kwargs.get("sandbox_workdir") == workdir, (
                f"{adapter.name} must request the agent workspace sandbox; "
                f"got kwargs={captured_kwargs}"
            )
            assert captured_kwargs.get("sandbox_name") == "two-fer"


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


def test_codex_manifest_records_openai_reasoning_effort_without_local_budget():
    """OpenAI/Codex effort levels are symbolic provider settings, not local budgets."""
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
            suite,
            _OkAdapter(),
            "codex/gpt-5.5",
            "python/two-fer",
            1,
            results_dir,
            vendor_dir,
            thinking="high",
        )

    sampling = manifest.get("sampling", {})
    assert sampling.get("thinking") == "high"
    assert sampling.get("reasoning_effort") == "high"
    assert sampling.get("reasoning_effort_source") == "openai"
    assert "thinking_token_budget" not in sampling, sampling
