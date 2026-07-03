"""
Tests for CLI argument handling in harness/runner.py.

The CLI parser returns strings for user-provided paths. Suites immediately
use Path division (`vendor_dir / "..."`), which crashes with
`TypeError: unsupported operand type(s) for /: 'str' and 'str'`.

See ORNITH-CODER-REVIEW.md follow-up audit item G.
"""

import sys
import tempfile
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

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = sp.CompletedProcess(
                args=[], returncode=0, stdout="ok", stderr=""
            )
            manifest, verdict = run_trial(
                suite, adapter, "test/model", "python/two-fer", 1,
                str(results_dir), str(vendor_dir),  # STRINGS, as from argparse
            )

    assert manifest["exit_code"] == 0


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
