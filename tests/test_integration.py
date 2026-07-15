"""
End-to-end integration tests that exercise the adapter → runner → viewer
pipeline WITHOUT mocking subprocess.run.

These catch the class of bugs that pure mock-based tests miss (e.g. the
original `stderr=Path` bug, the `-m` vs `--model` flag bug). We use a fake
executable (a tiny shell script placed on PATH) as the adapter binary so we
get real subprocess semantics.
"""

import json
import os
import stat
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from harness.adapters.pi_vanilla import PiVanillaAdapter
from harness.suites.aider_polyglot import AiderPolyglotSuite
from harness.runner import run_trial


def _write_fake_bin(tmpdir: Path, name: str, body: str):
    """Create an executable script named `name` in tmpdir and return its path."""
    path = tmpdir / name
    path.write_text("#!/bin/bash\n" + body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return path


def _make_problem(vendor_dir: Path):
    pdir = (
        vendor_dir / "polyglot-benchmark" / "python" / "exercises" / "practice" / "two-fer"
    )
    pdir.mkdir(parents=True)
    (pdir / ".docs").mkdir()
    (pdir / ".docs" / "instructions.md").write_text("Solve two-fer.")
    (pdir / "two_fer.py").write_text("def two_fer(name=None):\n    pass\n")
    (pdir / "two_fer_test.py").write_text(
        "from two_fer import two_fer\ndef test_two_fer():\n    assert True\n"
    )


def test_adapter_runs_real_subprocess_and_writes_logs(monkeypatch):
    """A real adapter subprocess must launch, write stdout to log_file and
    stderr to stderr_file, and report the real return code.

    This is the integration guard against `stderr=Path` and flag regressions.
    """
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        bindir = tmp / "bin"
        bindir.mkdir()
        # Fake `pi` that prints argv to stdout, writes a sentinel to stderr,
        # and echoes the prompt back. Exits 0.
        pi_path = _write_fake_bin(bindir, "pi", """
            echo "pi-invoked"
            for a in "$@"; do echo "arg: $a"; done
            echo "stderr-sentinel" >&2
            exit 0
        """)

        # Put bindir first on PATH for the subprocess.
        monkeypatch.setenv("PATH", f"{bindir}:{os.environ.get('PATH', '')}")

        workdir = tmp / "workdir"
        workdir.mkdir()
        (workdir / "starter.py").write_text("# starter")
        log_file = tmp / "session.log"
        stderr_file = tmp / "stderr.log"

        adapter = PiVanillaAdapter()
        task_data = {
            "model_id": "test/model",
            "prompt": "solve the problem",
            "timeout": 30,
        }

        result = adapter.run(task_data, workdir, log_file, stderr_file)

        assert result.returncode == 0, result
        assert "pi-invoked" in log_file.read_text(), log_file.read_text()
        assert "stderr-sentinel" in stderr_file.read_text(), stderr_file.read_text()
        # The --model flag (not -m) must appear in the recorded args
        log_text = log_file.read_text()
        assert "--model" in log_text, log_text
        assert "test/model" in log_text, log_text


def test_full_pipeline_runner_to_viewer_with_encoded_paths(tmp_path):
    """End-to-end: run_trial writes an encoded tree, the viewer reads it back.

    This catches the integration gap where the runner encodes but the viewer
    decodes incorrectly (or vice versa).
    """
    suite = AiderPolyglotSuite()
    adapter = PiVanillaAdapter()
    vendor_dir = tmp_path / "vendor"
    _make_problem(vendor_dir)
    results_dir = tmp_path / "results"

    import subprocess as sp

    with patch("harness.adapters.pi_vanilla.run_command") as mock_adapter_run, \
         patch("harness.suites.aider_polyglot.run_command") as mock_verify_run:
        mock_adapter_run.return_value = sp.CompletedProcess(
            args=[], returncode=0, stdout="ok", stderr=""
        )
        mock_verify_run.return_value = sp.CompletedProcess(
            args=[], returncode=0, stdout="1 passed", stderr=""
        )
        manifest, verdict = run_trial(
            suite, adapter, "nvidia/nemotron-3-ultra-550b-a55b",
            "python/two-fer", 1, results_dir, vendor_dir,
        )

    # Now load the viewer against this real tree
    import importlib.util
    server_path = PROJECT_ROOT / "view-scores" / "server.py"
    spec = importlib.util.spec_from_file_location("view_scores_server", server_path)
    server_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(server_mod)
    server_mod.RESULTS_DIR = results_dir

    h = server_mod.ScoreHandler.__new__(server_mod.ScoreHandler)
    scores = h.get_scores()
    assert len(scores) == 1, scores
    row = scores[0]
    assert row["model"] == "nvidia/nemotron-3-ultra-550b-a55b", row
    assert row["adapter"] == "pi_vanilla", row
    assert row["suite"] == "aider_polyglot", row
    assert row["total_tasks"] == 1, row

    # Task details round-trip with decoding
    from harness.path_utils import encode_model_path
    details = h.get_task_details(encode_model_path("nvidia/nemotron-3-ultra-550b-a55b"),
                                 "pi_vanilla", "aider_polyglot")
    assert "error" not in details, details
    assert any(t["task_id"] == "python/two-fer" for t in details["tasks"]), details


def test_terminal_bench_materialize_against_real_vendored_task():
    """materialize_task must extract the prompt from a REAL task.yaml in vendor/."""
    tb_root = PROJECT_ROOT / "vendor" / "terminal-bench" / "tasks"
    if not tb_root.exists():
        import pytest
        pytest.skip("vendor/terminal-bench not present")

    suite = __import__("harness.suites.terminal_bench", fromlist=["TerminalBenchSuite"]).TerminalBenchSuite()
    task_ids = suite.get_task_ids(vendor_dir=PROJECT_ROOT / "vendor")
    assert task_ids, "expected >0 terminal-bench tasks"

    # Pick hello-world if present (well-known), else the first task
    target = "hello-world" if "hello-world" in task_ids else task_ids[0]
    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp) / "workdir"
        td = suite.materialize_task(target, workdir, vendor_dir=PROJECT_ROOT / "vendor")

        assert td["prompt"], f"empty prompt for {target}"
        assert td["task_id"] == target
        assert (workdir / "task.yaml").exists(), "task.yaml not copied"
