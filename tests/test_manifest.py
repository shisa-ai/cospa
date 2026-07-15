"""
Tests for manifest completeness.

The manifest must record enough metadata to make runs comparable and
auditable (review finding #10). These tests pin the required fields and
their semantics:

  - provider, served_model, sampling params, tool_call_parser
  - env.hash must be a real hash, not sys.executable
  - terminal_bench_pin must read commit_hash from the registry
  - run_end_time must be set after the run
"""

import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock
import subprocess as sp

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from harness.adapters.pi_vanilla import PiVanillaAdapter
from harness.suites.aider_polyglot import AiderPolyglotSuite
from harness.runner import run_trial, get_env_hash, get_terminal_bench_pin


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


def test_manifest_has_required_fields():
    """Manifest must include provider, served_model, sampling, tool_call_parser."""
    suite = AiderPolyglotSuite()
    adapter = PiVanillaAdapter()

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        vendor_dir = tmp / "vendor"
        vendor_dir.mkdir()
        _make_problem(vendor_dir)
        results_dir = tmp / "results"

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = sp.CompletedProcess(
                args=[], returncode=0, stdout="ok", stderr=""
            )
            manifest, verdict = run_trial(
                suite, adapter, "test/model", "python/two-fer", 1,
                results_dir, vendor_dir,
            )

    # model block
    assert manifest["model"]["id"] == "test/model"
    assert manifest["model"]["provider"] == "test"
    # served_model must be present (may equal id when no proxy)
    assert "served_model" in manifest["model"], manifest["model"]
    # sampling params must be recorded
    assert "sampling" in manifest, manifest.keys()
    assert isinstance(manifest["sampling"], dict)
    assert manifest["sampling"]["temperature"] is not None
    assert manifest["sampling"]["top_p"] is not None
    assert manifest["sampling"]["max_tokens"] is not None
    # tool_call_parser/config identifier
    assert "tool_call_parser" in manifest, manifest.keys()
    assert manifest["tool_call_parser"] != "pi-default"
    # timing
    assert manifest.get("run_end_time"), "run_end_time must be set"
    assert manifest["timing"].get("wall_clock_seconds") is not None


def test_env_hash_is_a_real_hash_not_executable_path():
    """get_env_hash must return a hash digest, not a path to python."""
    h = get_env_hash()
    assert isinstance(h, str)
    # A 16+ char hex digest, not a filesystem path
    assert "/" not in h, f"env.hash looks like a path: {h}"
    assert len(h) >= 8, f"env.hash too short: {h}"
    assert all(c in "0123456789abcdef" for c in h.lower()), (
        f"env.hash not hex: {h}"
    )


def test_terminal_bench_pin_reads_checked_in_0_1_1_manifest():
    """The runner records the immutable Core 0.1.1 dataset commit."""
    with tempfile.TemporaryDirectory() as tmp:
        pin = get_terminal_bench_pin(Path(tmp) / "vendor")
    assert pin == "91e10457b5410f16c44364da1a34cb6de8c488a5", pin


def test_terminal_bench_pin_ignores_mutable_vendored_head_registry():
    """A vendored head registry must not override cospa's declared pin."""
    with tempfile.TemporaryDirectory() as tmp:
        vendor = Path(tmp) / "vendor"
        tb = vendor / "terminal-bench"
        tb.mkdir(parents=True)
        (tb / "registry.json").write_text(json.dumps([
            {
                "name": "terminal-bench-core",
                "version": "head",
                "commit_hash": "head",
                "task_id_subset": None,
            }
        ]))

        with patch("harness.runner.subprocess.run") as mock_run:
            pin = get_terminal_bench_pin(vendor)

    assert pin == "91e10457b5410f16c44364da1a34cb6de8c488a5", pin
    mock_run.assert_not_called()


def test_manifest_env_hash_recorded():
    """The manifest's env.hash must be the hash, not sys.executable."""
    suite = AiderPolyglotSuite()
    adapter = PiVanillaAdapter()

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        vendor_dir = tmp / "vendor"
        vendor_dir.mkdir()
        _make_problem(vendor_dir)
        results_dir = tmp / "results"

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = sp.CompletedProcess(
                args=[], returncode=0, stdout="ok", stderr=""
            )
            manifest, _ = run_trial(
                suite, adapter, "test/model", "python/two-fer", 1,
                results_dir, vendor_dir,
            )

    env_hash = manifest["env"]["hash"]
    assert "/" not in env_hash, f"env.hash is a path: {env_hash}"
    assert all(c in "0123456789abcdef" for c in env_hash.lower()), env_hash


def test_little_coder_version_probe_is_cached():
    """Full matrices must not spawn little-coder --version for every trial."""
    from harness import runner as runner_mod

    runner_mod.get_little_coder_version.cache_clear()
    try:
        with patch("harness.runner.subprocess.run") as mock_run:
            mock_run.return_value = sp.CompletedProcess(
                args=["little-coder", "--version"],
                returncode=0,
                stdout="0.79.10\n",
                stderr="",
            )
            assert runner_mod.get_little_coder_version() == "0.79.10"
            assert runner_mod.get_little_coder_version() == "0.79.10"

        assert mock_run.call_count == 1
    finally:
        runner_mod.get_little_coder_version.cache_clear()
