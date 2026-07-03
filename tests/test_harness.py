"""
Tests for the coding-eval harness.

Covers:
- Path encoding/decoding for model and task IDs with slashes
- Adapter command construction (verifying --model flag, stderr file handling)
- Suite materialization (aider_polyglot, terminal_bench)
- Runner directory structure
- View-scores server path decoding
"""

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from harness.adapters import load_adapter
from harness.adapters.pi_vanilla import PiVanillaAdapter
from harness.adapters.pi_devstack import PiDevstackAdapter
from harness.adapters.little_coder import LittleCoderAdapter
from harness.suites import load_suite
from harness.suites.aider_polyglot import AiderPolyglotSuite
from harness.suites.terminal_bench import TerminalBenchSuite
from harness.runner import run_trial
from harness.path_utils import (
    encode_model_path,
    decode_model_path,
    encode_task_path,
    decode_task_path,
)


class TestPathUtils:
    """Test path encoding/decoding utilities."""

    def test_encode_decode_model_path(self):
        """Test that model IDs with slashes are properly encoded/decoded."""
        model_id = "nvidia/nemotron-3-ultra-550b-a55b"
        encoded = encode_model_path(model_id)
        assert encoded == "nvidia%2Fnemotron-3-ultra-550b-a55b"
        assert decode_model_path(encoded) == model_id

    def test_encode_decode_task_path(self):
        """Test that task IDs with slashes are properly encoded/decoded."""
        task_id = "python/hello"
        encoded = encode_task_path(task_id)
        assert encoded == "python%2Fhello"
        assert decode_task_path(encoded) == task_id

    def test_encode_simple_model_path(self):
        """Test that model IDs without slashes are preserved."""
        model_id = "test-model"
        encoded = encode_model_path(model_id)
        assert encoded == "test-model"
        assert decode_model_path(encoded) == model_id

    def test_encode_simple_task_path(self):
        """Test that task IDs without slashes are preserved."""
        task_id = "hello"
        encoded = encode_task_path(task_id)
        assert encoded == "hello"
        assert decode_task_path(encoded) == task_id

    def test_encode_special_characters(self):
        """Test encoding of special characters."""
        model_id = "provider/model-v1.0 (beta)"
        encoded = encode_model_path(model_id)
        assert "%" in encoded
        assert decode_model_path(encoded) == model_id


class TestAdapters:
    """Test adapter loading and command construction."""

    def test_load_adapter_pi_vanilla(self):
        adapter = load_adapter("pi_vanilla")
        assert isinstance(adapter, PiVanillaAdapter)
        assert adapter.name == "pi_vanilla"

    def test_load_adapter_pi_devstack(self):
        adapter = load_adapter("pi_devstack")
        assert isinstance(adapter, PiDevstackAdapter)
        assert adapter.name == "pi_devstack"

    def test_load_adapter_little_coder(self):
        adapter = load_adapter("little_coder")
        assert isinstance(adapter, LittleCoderAdapter)
        assert adapter.name == "little_coder"

    def test_load_adapter_unknown(self):
        with pytest.raises(ValueError, match="Unknown adapter"):
            load_adapter("unknown_adapter")

    def test_pi_vanilla_uses_model_flag(self):
        """Test that pi_vanilla uses --model flag (not -m)."""
        adapter = PiVanillaAdapter()
        task_data = {"model_id": "test/model", "prompt": "test prompt"}
        workdir = Path(tempfile.mkdtemp())
        log_file = workdir / "log.txt"
        stderr_file = workdir / "stderr.txt"

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="output", stderr="")
            adapter.run(task_data, workdir, log_file, stderr_file)

            cmd = mock_run.call_args[0][0]
            assert "--model" in cmd
            assert "-m" not in cmd  # Should not use short form
            assert "test/model" in cmd

        shutil.rmtree(workdir)

    def test_pi_vanilla_opens_stderr_file(self):
        """Test that pi_vanilla opens stderr file properly (not passes Path object)."""
        adapter = PiVanillaAdapter()
        task_data = {"model_id": "test/model", "prompt": "test prompt"}
        workdir = Path(tempfile.mkdtemp())
        log_file = workdir / "log.txt"
        stderr_file = workdir / "stderr.txt"

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="output", stderr="")
            adapter.run(task_data, workdir, log_file, stderr_file)

            # Check that stdout and stderr are opened files, not Path objects
            kwargs = mock_run.call_args[1]
            assert isinstance(kwargs["stdout"], type(open("/dev/null", "w")))
            assert isinstance(kwargs["stderr"], type(open("/dev/null", "w")))

        shutil.rmtree(workdir)

    def test_pi_devstack_uses_model_flag(self):
        """Test that pi_devstack uses --model flag."""
        adapter = PiDevstackAdapter()
        task_data = {"model_id": "test/model", "prompt": "test prompt"}
        workdir = Path(tempfile.mkdtemp())
        log_file = workdir / "log.txt"
        stderr_file = workdir / "stderr.txt"

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="output", stderr="")
            adapter.run(task_data, workdir, log_file, stderr_file)

            cmd = mock_run.call_args[0][0]
            assert "--model" in cmd
            assert "test/model" in cmd

        shutil.rmtree(workdir)

    def test_little_coder_uses_model_flag(self):
        """Test that little_coder uses --model flag."""
        adapter = LittleCoderAdapter()
        task_data = {"model_id": "test/model", "prompt": "test prompt"}
        workdir = Path(tempfile.mkdtemp())
        log_file = workdir / "log.txt"
        stderr_file = workdir / "stderr.txt"

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="output", stderr="")
            adapter.run(task_data, workdir, log_file, stderr_file)

            cmd = mock_run.call_args[0][0]
            assert "--model" in cmd
            assert "test/model" in cmd

        shutil.rmtree(workdir)


class TestSuites:
    """Test suite loading and task materialization."""

    def test_load_suite_aider_polyglot(self):
        suite = load_suite("aider_polyglot")
        assert isinstance(suite, AiderPolyglotSuite)
        assert suite.name == "aider_polyglot"

    def test_load_suite_terminal_bench(self):
        suite = load_suite("terminal_bench")
        assert isinstance(suite, TerminalBenchSuite)
        assert suite.name == "terminal_bench"

    def test_load_suite_unknown(self):
        with pytest.raises(ValueError, match="Unknown suite"):
            load_suite("unknown_suite")

    def test_aider_polyglot_materialize_task(self, make_polyglot_problem):
        """Test that aider_polyglot materializes tasks correctly."""
        suite = AiderPolyglotSuite()

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            vendor_dir = tmpdir / "vendor"
            make_polyglot_problem(
                vendor_dir, "python", "two-fer",
                instructions="Write a two-fer function",
                starter_name="two_fer",
                starter_content="def two_fer(name=None):\n    pass\n",
                test_content=(
                    "from two_fer import two_fer\n"
                    "def test_two_fer():\n"
                    "    assert two_fer() == 'One for you, one for me.'\n"
                ),
            )

            workdir = tmpdir / "workdir"
            task_data = suite.materialize_task("python/two-fer", workdir, vendor_dir)

            # Check that starter and test files were copied to workdir root
            assert (workdir / "two_fer.py").exists()
            assert (workdir / "two_fer_test.py").exists()

            # Check task_data
            assert "two-fer" in task_data["prompt"]
            assert task_data["language"] == "python"
            assert task_data["problem"] == "two-fer"

    def test_aider_polyglot_get_task_ids(self, make_polyglot_problem):
        """Test that aider_polyglot discovers tasks correctly."""
        suite = AiderPolyglotSuite()

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            vendor_dir = tmpdir / "vendor"
            make_polyglot_problem(
                vendor_dir, "python", "two-fer",
                starter_name="two_fer",
            )
            make_polyglot_problem(
                vendor_dir, "javascript", "fib",
                starter_content="function fib(n) { return n; }\n",
                test_content="console.log('test');\n",
            )

            task_ids = suite.get_task_ids(vendor_dir)
            assert len(task_ids) == 2
            assert "javascript/fib" in task_ids
            assert "python/two-fer" in task_ids

    def test_terminal_bench_get_task_ids_empty(self):
        """Test that terminal_bench returns empty list when no registry."""
        suite = TerminalBenchSuite()

        with tempfile.TemporaryDirectory() as tmpdir:
            task_ids = suite.get_task_ids(Path(tmpdir))
            assert task_ids == []

    def test_terminal_bench_materialize_task(self):
        """Test that terminal_bench materializes tasks from original-tasks."""
        suite = TerminalBenchSuite()

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            vendor_dir = tmpdir / "vendor"
            vendor_dir.mkdir()

            # Create original-tasks directory
            task_dir = vendor_dir / "terminal-bench" / "original-tasks" / "my-task"
            task_dir.mkdir(parents=True)
            (task_dir / "instruction.md").write_text("Solve this task")
            (task_dir / "verifier.py").write_text("print('verified')")

            workdir = tmpdir / "workdir"
            task_data = suite.materialize_task("my-task", workdir, vendor_dir)

            # Check that files were copied
            assert (workdir / "instruction.md").exists()
            assert (workdir / "verifier.py").exists()

            # Check task_data
            assert task_data["task_id"] == "my-task"
            assert task_data["prompt"] == "Solve this task"


class TestRunner:
    """Test runner functionality."""

    def test_run_trial_creates_directory_structure(self, make_polyglot_problem):
        """Test that run_trial creates the correct directory structure."""
        suite = AiderPolyglotSuite()
        adapter = PiVanillaAdapter()

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            vendor_dir = tmpdir / "vendor"
            make_polyglot_problem(
                vendor_dir, "python", "two-fer",
                instructions="Write a two-fer function",
                starter_name="two_fer",
                starter_content="def two_fer(name=None):\n    pass\n",
                test_content=(
                    "from two_fer import two_fer\n"
                    "def test_two_fer():\n"
                    "    assert two_fer() == 'One for you, one for me.'\n"
                ),
            )

            results_dir = tmpdir / "results"

            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0, stdout="LLM output", stderr="")
                manifest, verdict = run_trial(
                    suite, adapter, "test/model", "python/two-fer", 1,
                    results_dir, vendor_dir
                )

                # Check that trial directory was created with encoded paths
                trial_dir = results_dir / "test%2Fmodel" / "pi_vanilla" / "aider_polyglot" / "python%2Ftwo-fer" / "trial-1"
                assert trial_dir.exists()
                assert (trial_dir / "manifest.json").exists()
                assert (trial_dir / "verdict.json").exists()
                assert (trial_dir / "workdir").exists()

                # Check manifest
                assert manifest["model"]["id"] == "test/model"
                assert manifest["model"]["provider"] == "test"
                assert manifest["adapter"]["id"] == "PiVanillaAdapter"
                assert manifest["suite"]["task_id"] == "python/two-fer"

    def test_model_id_passed_correctly(self, make_polyglot_problem):
        """Test that model_id from args is used in command and manifest."""
        suite = AiderPolyglotSuite()
        adapter = PiVanillaAdapter()

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            vendor_dir = tmpdir / "vendor"
            make_polyglot_problem(
                vendor_dir, "python", "two-fer",
                instructions="Write a two-fer function",
                starter_name="two_fer",
                starter_content="def two_fer(name=None):\n    pass\n",
                test_content=(
                    "from two_fer import two_fer\n"
                    "def test_two_fer():\n"
                    "    assert two_fer() == 'One for you, one for me.'\n"
                ),
            )

            results_dir = tmpdir / "results"

            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0, stdout="LLM output", stderr="")
                manifest, verdict = run_trial(
                    suite, adapter, "my-custom/model", "python/two-fer", 1,
                    results_dir, vendor_dir
                )

                # Check that the adapter was called with the correct model
                # Find the pi command that includes the model_id
                pi_cmd = None
                for call in mock_run.call_args_list:
                    cmd = call[0][0]
                    if cmd[0] == "pi" and "my-custom/model" in cmd:
                        pi_cmd = cmd
                        break
                assert pi_cmd is not None, "No pi command with model found in subprocess calls"
                assert "my-custom/model" in pi_cmd

                # Check manifest
                assert manifest["model"]["id"] == "my-custom/model"
                assert manifest["model"]["provider"] == "my-custom"


class TestViewScores:
    """Test view-scores server path decoding."""

    def test_decode_encoded_model_path(self):
        """Test that the viewer can decode URL-encoded model paths."""
        # The path_utils functions handle decoding correctly
        encoded = encode_model_path("nvidia/nemotron-3-ultra-550b-a55b")
        decoded = decode_model_path(encoded)
        assert decoded == "nvidia/nemotron-3-ultra-550b-a55b"

    def test_decode_encoded_task_path(self):
        """Test that the viewer can decode URL-encoded task paths."""
        encoded = encode_task_path("python/hello")
        decoded = decode_task_path(encoded)
        assert decoded == "python/hello"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
