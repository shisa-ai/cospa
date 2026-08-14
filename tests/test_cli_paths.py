"""
Tests for CLI argument handling in harness/runner.py.

The CLI parser returns strings for user-provided paths. Suites immediately
use Path division (`vendor_dir / "..."`), which crashes with
`TypeError: unsupported operand type(s) for /: 'str' and 'str'`.

See ORNITH-CODER-REVIEW.md follow-up audit item G.
"""

import sys
import tempfile
import io
import threading
import time
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from harness.suites.aider_polyglot import AiderPolyglotSuite
from harness.suites.terminal_bench import TerminalBenchSuite


def _make_aider_problem(vendor_dir: Path):
    """Build a real-shaped polyglot-benchmark problem."""
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


def test_aider_get_task_ids_accepts_str_vendor_dir():
    """get_task_ids must accept a str (as produced by argparse) without crashing."""
    with tempfile.TemporaryDirectory() as tmp:
        vendor_dir = Path(tmp) / "vendor"
        vendor_dir.mkdir()
        _make_aider_problem(vendor_dir)
        suite = AiderPolyglotSuite()
        # Pass a STRING, exactly what argparse produces
        ids = suite.get_task_ids(vendor_dir=str(vendor_dir))
    assert ids == ["python/two-fer"], ids


def test_terminal_bench_get_task_ids_accepts_str_vendor_dir():
    """get_task_ids must accept a str vendor_dir without crashing."""
    suite = TerminalBenchSuite()
    # Empty/nonexistent path must not raise, just return []
    ids = suite.get_task_ids(vendor_dir="/does/not/exist")
    assert ids == []


def test_aider_materialize_task_accepts_str_vendor_dir():
    """materialize_task must accept a str vendor_dir without crashing."""
    with tempfile.TemporaryDirectory() as tmp:
        vendor_dir = Path(tmp) / "vendor"
        _make_aider_problem(vendor_dir)
        workdir = Path(tmp) / "workdir"
        suite = AiderPolyglotSuite()
        task_data = suite.materialize_task(
            "python/two-fer", workdir, vendor_dir=str(vendor_dir)
        )
    assert task_data["task_id"] == "python/two-fer"


def test_run_trial_accepts_str_paths():
    """run_trial must accept str results_dir and vendor_dir (CLI shape)."""
    import json
    from unittest.mock import patch, MagicMock
    import subprocess as sp
    from harness.runner import run_trial
    from harness.adapters.pi_vanilla import PiVanillaAdapter

    suite = AiderPolyglotSuite()
    adapter = PiVanillaAdapter()

    with tempfile.TemporaryDirectory() as tmp:
        vendor_dir = Path(tmp) / "vendor"
        vendor_dir.mkdir()
        _make_aider_problem(vendor_dir)
        results_dir = Path(tmp) / "results"

        with patch("harness.adapters.pi_vanilla.run_command") as mock_adapter_run, \
             patch("harness.suites.aider_polyglot.run_command") as mock_verify_run:
            mock_adapter_run.return_value = sp.CompletedProcess(
                args=[], returncode=0, stdout="ok", stderr=""
            )
            mock_verify_run.return_value = sp.CompletedProcess(
                args=[], returncode=0, stdout="ok", stderr=""
            )
            manifest, verdict = run_trial(
                suite, adapter, "test/model", "python/two-fer", 1,
                str(results_dir), str(vendor_dir),  # STRINGS, as from argparse
            )

    assert manifest["exit_code"] == 0


def test_resolve_results_dir_defaults_to_model_run_wrapper():
    """Omitting --results-dir must isolate CLI output by model + run id."""
    from harness.runner import resolve_results_dir

    results_dir, run_id = resolve_results_dir(
        "test/model",
        requested_results_dir=None,
        run_id="run-a",
    )

    assert run_id == "run-a"
    assert results_dir == PROJECT_ROOT / "results" / "runs" / "test%2Fmodel-run-a"


def test_resolve_results_dir_preserves_explicit_output_root():
    """Explicit --results-dir remains an intentional shared/merge root."""
    from harness.runner import resolve_results_dir

    with tempfile.TemporaryDirectory() as tmp:
        requested = Path(tmp) / "shared-results"
        results_dir, run_id = resolve_results_dir(
            "test/model",
            requested_results_dir=requested,
            run_id="run-a",
        )

    assert results_dir == requested
    assert run_id is None


def test_runner_main_uses_default_model_run_results_wrapper():
    """Normal CLI invocations should not race on default results/ paths."""
    import argparse
    from harness import runner as runner_mod

    vendor_dir = Path(tempfile.mkdtemp())
    args = argparse.Namespace(
        suite="aider_polyglot",
        adapter="pi_vanilla",
        model="test/model",
        problems=1,
        k=1,
        results_dir=None,
        run_id="run-a",
        vendor_dir=vendor_dir,
        config=Path("/tmp/c"),
        skip_reachability=True,
    )
    captured_results = []

    def fake_run_trial(
        suite,
        adapter,
        model,
        task_id,
        trial_k,
        results_dir,
        vendor_dir,
        thinking=None,
        **kwargs,
    ):
        captured_results.append(Path(results_dir))
        return {"timing": {"wall_clock_seconds": 0}}, {"passed": True}

    with patch.object(runner_mod, "parse_args", return_value=args), \
         patch.object(runner_mod, "load_suite") as mock_suite, \
         patch.object(runner_mod, "load_adapter") as mock_adapter, \
         patch.object(runner_mod, "run_trial_with_retries", side_effect=fake_run_trial):
        mock_suite.return_value.name = "aider_polyglot"
        mock_suite.return_value.get_task_ids.return_value = ["python/two-fer"]
        mock_adapter.return_value.name = "pi_vanilla"
        runner_mod.main()

    assert captured_results == [
        PROJECT_ROOT / "results" / "runs" / "test%2Fmodel-run-a"
    ]


def test_runner_main_writes_run_heartbeat():
    """The runner should leave a cell-level heartbeat/status artifact."""
    import argparse
    import json
    from harness import runner as runner_mod

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        results_dir = tmp / "results"
        args = argparse.Namespace(
            suite="aider_polyglot",
            adapter="pi_vanilla",
            model="test/model",
            problems=1,
            k=1,
            results_dir=results_dir,
            run_id=None,
            vendor_dir=tmp / "vendor",
            config=Path("/tmp/c"),
            skip_reachability=True,
        )

        def fake_run_trial(suite, adapter, model, task_id, trial_k, results_dir, vendor_dir, thinking=None, **kwargs):
            return {"timing": {"wall_clock_seconds": 0}}, {"passed": True}

        with patch.object(runner_mod, "parse_args", return_value=args), \
             patch.object(runner_mod, "load_suite") as mock_suite, \
             patch.object(runner_mod, "load_adapter") as mock_adapter, \
             patch.object(runner_mod, "run_trial_with_retries", side_effect=fake_run_trial):
            mock_suite.return_value.name = "aider_polyglot"
            mock_suite.return_value.get_task_ids.return_value = ["python/two-fer"]
            mock_adapter.return_value.name = "pi_vanilla"
            runner_mod.main()

        heartbeat_path = (
            results_dir
            / "test%2Fmodel"
            / "pi_vanilla"
            / "aider_polyglot"
            / ".runner-heartbeat.json"
        )
        heartbeat = json.loads(heartbeat_path.read_text())

    assert heartbeat["state"] == "complete"
    assert heartbeat["model"] == "test/model"
    assert heartbeat["adapter"] == "pi_vanilla"
    assert heartbeat["suite"] == "aider_polyglot"
    assert heartbeat["completed_trials"] == 1
    assert heartbeat["total_trials"] == 1


def test_run_heartbeat_records_process_interruption():
    """A termination callback must not leave a fresh `running` heartbeat."""
    import json
    import signal
    from harness.runner import RunHeartbeat

    with tempfile.TemporaryDirectory() as tmp:
        heartbeat = RunHeartbeat(
            results_dir=Path(tmp),
            model_id="test/model",
            adapter_name="pi_vanilla",
            suite_name="test_suite",
            run_id="interrupt-test",
            total_trials=4,
            concurrency=2,
        )
        heartbeat.start()
        heartbeat.interrupt(signal.SIGTERM)
        data = json.loads(heartbeat.path.read_text())

    assert data["state"] == "interrupted"
    assert data["termination_signal"] == signal.SIGTERM
    assert data["active_trials"] == 0


def test_run_with_tty_updates_emits_heartbeat(monkeypatch):
    """Interactive runs should show periodic progress while a trial runs."""
    from harness.runner import run_with_tty_updates

    class TtyBuffer(io.StringIO):
        def isatty(self):
            return True

    out = TtyBuffer()
    monkeypatch.setattr(sys, "stdout", out)

    def slow_result():
        time.sleep(0.03)
        return "done"

    result = run_with_tty_updates(slow_result, "Trial 1/1", interval=0.01)

    assert result == "done"
    assert "running" in out.getvalue()


def test_run_with_tty_updates_stays_quiet_without_tty(monkeypatch):
    """Non-interactive logs should not receive spinner/heartbeat noise."""
    from harness.runner import run_with_tty_updates

    out = io.StringIO()
    monkeypatch.setattr(sys, "stdout", out)

    result = run_with_tty_updates(lambda: "done", "Trial 1/1", interval=0.01)

    assert result == "done"
    assert out.getvalue() == ""


def test_runner_main_rejects_nonpositive_k():
    """--k must be a positive trial count, not a silent no-op."""
    import argparse
    from harness import runner as runner_mod

    args = argparse.Namespace(
        suite="aider_polyglot",
        adapter="pi_vanilla",
        model="test/model",
        problems=1,
        k=0,
        results_dir=Path(tempfile.mkdtemp()),
        vendor_dir=Path(tempfile.mkdtemp()),
        config=Path("/tmp/c"),
        skip_reachability=True,
    )

    with patch.object(runner_mod, "parse_args", return_value=args), \
         patch.object(runner_mod, "load_suite") as mock_suite:
        try:
            runner_mod.main()
        except SystemExit as e:
            assert e.code != 0, f"expected nonzero exit, got {e.code}"
        else:
            assert False, "main() must exit for --k 0"

    mock_suite.assert_not_called()


def test_runner_main_rejects_nonpositive_problem_limit():
    """--problems must be positive when provided."""
    import argparse
    from harness import runner as runner_mod

    args = argparse.Namespace(
        suite="aider_polyglot",
        adapter="pi_vanilla",
        model="test/model",
        problems=-1,
        k=1,
        results_dir=Path(tempfile.mkdtemp()),
        vendor_dir=Path(tempfile.mkdtemp()),
        config=Path("/tmp/c"),
        skip_reachability=True,
    )

    with patch.object(runner_mod, "parse_args", return_value=args), \
         patch.object(runner_mod, "load_suite") as mock_suite:
        try:
            runner_mod.main()
        except SystemExit as e:
            assert e.code != 0, f"expected nonzero exit, got {e.code}"
        else:
            assert False, "main() must exit for negative --problems"

    mock_suite.assert_not_called()


def test_runner_main_rejects_nonpositive_concurrency():
    """--concurrency must be positive instead of creating a zero-worker run."""
    import argparse
    from harness import runner as runner_mod

    args = argparse.Namespace(
        suite="aider_polyglot",
        adapter="pi_vanilla",
        model="test/model",
        problems=1,
        k=1,
        concurrency=0,
        results_dir=Path(tempfile.mkdtemp()),
        vendor_dir=Path(tempfile.mkdtemp()),
        config=Path("/tmp/c"),
        skip_reachability=True,
    )

    with patch.object(runner_mod, "parse_args", return_value=args), \
         patch.object(runner_mod, "load_suite") as mock_suite:
        try:
            runner_mod.main()
        except SystemExit as exc:
            assert exc.code != 0, f"expected nonzero exit, got {exc.code}"
        else:
            assert False, "main() must exit for --concurrency 0"

    mock_suite.assert_not_called()


def test_runner_main_bounds_parallel_trials_and_runs_each_once():
    """Concurrency three must run all k=2 work once with at most three active."""
    import argparse
    import json
    from harness import runner as runner_mod

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        args = argparse.Namespace(
            suite="aider_polyglot",
            adapter="pi_vanilla",
            model="test/model",
            problems=None,
            k=2,
            concurrency=3,
            results_dir=tmp_path / "results",
            run_id=None,
            vendor_dir=tmp_path / "vendor",
            config=Path("/tmp/c"),
            skip_reachability=True,
            thinking=None,
            retries=0,
        )
        lock = threading.Lock()
        active = 0
        max_active = 0
        calls = []

        def fake_run_trial(
            suite,
            adapter,
            model,
            task_id,
            trial_k,
            results_dir,
            vendor_dir,
            thinking=None,
            **kwargs,
        ):
            nonlocal active, max_active
            with lock:
                active += 1
                max_active = max(max_active, active)
                calls.append((task_id, trial_k))
            time.sleep(0.03)
            with lock:
                active -= 1
            return {"timing": {"wall_clock_seconds": 0.03}}, {"passed": True}

        with patch.object(runner_mod, "parse_args", return_value=args), \
             patch.object(runner_mod, "load_suite") as mock_suite, \
             patch.object(runner_mod, "load_adapter") as mock_adapter, \
             patch.object(
                 runner_mod,
                 "run_trial_with_retries",
                 side_effect=fake_run_trial,
             ):
            mock_suite.return_value.name = "aider_polyglot"
            mock_suite.return_value.get_task_ids.return_value = [
                "task/a",
                "task/b",
                "task/c",
                "task/d",
            ]
            mock_adapter.return_value.name = "pi_vanilla"
            runner_mod.main()

        heartbeat_path = (
            args.results_dir
            / "test%2Fmodel"
            / "pi_vanilla"
            / "aider_polyglot"
            / ".runner-heartbeat.json"
        )
        heartbeat = json.loads(heartbeat_path.read_text())

    assert sorted(calls) == sorted(
        (task_id, trial_k)
        for task_id in ("task/a", "task/b", "task/c", "task/d")
        for trial_k in (1, 2)
    )
    assert max_active == 3
    assert heartbeat["completed_trials"] == 8
    assert heartbeat["concurrency"] == 3
