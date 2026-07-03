"""
Tests for the coding-eval harness.
"""

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from harness.adapters import load_adapter
from harness.adapters.pi_vanilla import PiVanillaAdapter
from harness.adapters.pi_devstack import PiDevstackAdapter
from harness.adapters.little_coder import LittleCoderAdapter
from harness.suites import load_suite
from harness.suites.aider_polyglot import AiderPolyglotSuite
from harness.runner import run_trial


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
        try:
            load_adapter("unknown_adapter")
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "Unknown adapter" in str(e)

    def test_pi_vanilla_command_construction(self):
        """Test that pi_vanilla constructs the correct command."""
        adapter = PiVanillaAdapter()
        task_data = {"model_id": "test/model", "prompt": "test prompt"}
        workdir = Path(tempfile.mkdtemp())
        log_file = workdir / "log.txt"
        stderr_file = workdir / "stderr.txt"

        # Mock subprocess.run to capture the command
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            adapter.run(task_data, workdir, log_file, stderr_file)

            # Check that subprocess.run was called
            assert mock_run.called
            call_args = mock_run.call_args

            # Check the command
            cmd = call_args[0][0]
            assert cmd[0] == "pi"
            assert "--no-extensions" in cmd
            assert "--print" in cmd
            assert "-m" in cmd
            assert "test/model" in cmd

        # Cleanup
        shutil.rmtree(workdir)

    def test_pi_devstack_command_construction(self):
        """Test that pi_devstack constructs the correct command."""
        adapter = PiDevstackAdapter()
        task_data = {"model_id": "test/model", "prompt": "test prompt"}
        workdir = Path(tempfile.mkdtemp())
        log_file = workdir / "log.txt"
        stderr_file = workdir / "stderr.txt"

        # Mock subprocess.run to capture the command
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            adapter.run(task_data, workdir, log_file, stderr_file)

            # Check the command
            cmd = mock_run.call_args[0][0]
            assert cmd[0] == "pi"
            assert "--no-extensions" in cmd
            assert "--no-skills" in cmd
            assert "--print" in cmd
            assert "-m" in cmd
            assert "test/model" in cmd

        # Cleanup
        shutil.rmtree(workdir)

    def test_little_coder_command_construction(self):
        """Test that little_coder constructs the correct command."""
        adapter = LittleCoderAdapter()
        task_data = {"model_id": "test/model", "prompt": "test prompt"}
        workdir = Path(tempfile.mkdtemp())
        log_file = workdir / "log.txt"
        stderr_file = workdir / "stderr.txt"

        # Mock subprocess.run to capture the command
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            adapter.run(task_data, workdir, log_file, stderr_file)

            # Check the command
            cmd = mock_run.call_args[0][0]
            assert cmd[0] == "little-coder"
            assert "--print" in cmd
            assert "-m" in cmd
            assert "test/model" in cmd

        # Cleanup
        shutil.rmtree(workdir)


class TestSuites:
    """Test suite loading and task materialization."""

    def test_load_suite_aider_polyglot(self):
        suite = load_suite("aider_polyglot")
        assert isinstance(suite, AiderPolyglotSuite)
        assert suite.name == "aider_polyglot"

    def test_load_suite_unknown(self):
        try:
            load_suite("unknown_suite")
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "Unknown suite" in str(e)

    def test_aider_polyglot_materialize_task(self):
        """Test that aider_polyglot materializes tasks correctly."""
        suite = AiderPolyglotSuite()

        # Create a temporary problem directory structure
        # The materialize_task expects: vendor_dir/aider-polyglot/problems/{language}/{problem}/
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            vendor_dir = tmpdir / "vendor"
            vendor_dir.mkdir()
            problem_dir = vendor_dir / "aider-polyglot" / "problems" / "python" / "hello"
            problem_dir.mkdir(parents=True)

            # Create problem.txt
            (problem_dir / "problem.txt").write_text("Write a hello function")

            # Create starter files
            starter_dir = problem_dir / "starter"
            starter_dir.mkdir()
            (starter_dir / "hello.py").write_text("def hello():\n    pass")

            # Create test files
            tests_dir = problem_dir / "tests"
            tests_dir.mkdir()
            (tests_dir / "test_hello.py").write_text("from hello import hello\ndef test_hello():\n    assert hello() == 'Hello, World!'")

            # Materialize the task
            workdir = tmpdir / "workdir"
            task_data = suite.materialize_task("python/hello", workdir, vendor_dir)

            # Check that files were copied
            assert (workdir / "hello.py").exists()
            assert (workdir / "tests" / "test_hello.py").exists()

            # Check task_data
            assert task_data["prompt"] == "Write a hello function"
            assert task_data["language"] == "python"
            assert task_data["problem"] == "hello"


class TestRunner:
    """Test runner functionality."""

    def test_run_trial_creates_directory_structure(self):
        """Test that run_trial creates the correct directory structure."""
        suite = AiderPolyglotSuite()
        adapter = PiVanillaAdapter()

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            vendor_dir = tmpdir / "vendor"
            vendor_dir.mkdir()

            # Create a problem directory
            problem_dir = vendor_dir / "aider-polyglot" / "problems" / "python" / "hello"
            problem_dir.mkdir(parents=True)
            (problem_dir / "problem.txt").write_text("Write a hello function")
            (problem_dir / "starter").mkdir()
            (problem_dir / "starter" / "hello.py").write_text("def hello():\n    pass")
            (problem_dir / "tests").mkdir()
            (problem_dir / "tests" / "test_hello.py").write_text("from hello import hello\ndef test_hello():\n    assert hello() == 'Hello, World!'")

            results_dir = tmpdir / "results"

            # Mock subprocess.run for the adapter
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0, stdout="LLM output here", stderr="")
                manifest, verdict = run_trial(
                    suite, adapter, "test/model", "python/hello", 1,
                    results_dir, vendor_dir
                )

                # Check that trial directory was created
                trial_dir = results_dir / "test/model" / "pi_vanilla" / "aider_polyglot" / "python/hello" / "trial-1"
                assert trial_dir.exists()
                assert (trial_dir / "manifest.json").exists()
                assert (trial_dir / "verdict.json").exists()
                assert (trial_dir / "workdir").exists()

                # Check manifest
                assert manifest["model"]["id"] == "test/model"
                assert manifest["adapter"]["id"] == "PiVanillaAdapter"
                assert manifest["suite"]["task_id"] == "python/hello"

    def test_model_id_passed_to_task_data(self):
        """Test that model_id from args is passed to task_data and used in command."""
        suite = AiderPolyglotSuite()
        adapter = PiVanillaAdapter()

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            vendor_dir = tmpdir / "vendor"
            vendor_dir.mkdir()

            # Create a problem directory
            problem_dir = vendor_dir / "aider-polyglot" / "problems" / "python" / "hello"
            problem_dir.mkdir(parents=True)
            (problem_dir / "problem.txt").write_text("Write a hello function")
            (problem_dir / "starter").mkdir()
            (problem_dir / "starter" / "hello.py").write_text("def hello():\n    pass")
            (problem_dir / "tests").mkdir()
            (problem_dir / "tests" / "test_hello.py").write_text("from hello import hello\ndef test_hello():\n    assert hello() == 'Hello, World!'")

            results_dir = tmpdir / "results"
            workdir = tmpdir / "workdir"

            # Materialize the task
            task_data = suite.materialize_task("python/hello", workdir, vendor_dir)

            # Override model_id with the custom model
            task_data["model_id"] = "my-custom/model"

            # Test that the adapter uses the correct model_id
            log_file = workdir / "log.txt"
            stderr_file = workdir / "stderr.txt"

            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0, stdout="LLM output here", stderr="")
                adapter.run(task_data, workdir, log_file, stderr_file)

                # Check that subprocess.run was called with the correct model
                cmd = mock_run.call_args[0][0]
                assert "my-custom/model" in cmd
                assert cmd[0] == "pi"


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
