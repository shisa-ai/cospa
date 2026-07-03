"""
Tests for Terminal-Bench integration with the runner and Harbor.

Reproduces ORNITH-CODER-REVIEW.md findings #4 and follow-up audit item B:
  - materialize_task must read task.yaml (not instruction.md), and must
    not raise UnboundLocalError on tasks lacking verifier.py/scorer.py.
  - run_harbor_job must use --n-attempts/-k, --model/-m, --agent/-a,
    --registry-path, and the head version's commit_hash.
  - Terminal-Bench must preserve adapter identity via custom Harbor agents,
    not collapse pi_vanilla/pi_devstack/pi_superpowers into the same agent.
  - The runner must delegate terminal_bench trials to run_harbor_job
    instead of the generic adapter path.
"""

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from harness.suites.terminal_bench import TerminalBenchSuite


def _make_task_yaml_task(vendor_dir: Path, task_id="hello-world"):
    """Create a real-shaped Terminal-Bench task using task.yaml."""
    task_dir = vendor_dir / "terminal-bench" / "original-tasks" / task_id
    task_dir.mkdir(parents=True)
    (task_dir / "task.yaml").write_text(
        "# canary\n"
        "instruction: |-\n"
        "  Create a file called /app/hello.txt. Write \"Hello, world!\" to it.\n"
        "author_name: Test\n"
        "difficulty: easy\n"
        "category: file-operations\n"
        "tags:\n"
        "  - file-operations\n"
        "parser_name: pytest\n"
        "max_agent_timeout_sec: 900.0\n"
        "max_test_timeout_sec: 180.0\n"
    )
    (task_dir / "Dockerfile").write_text("FROM python:3.13\n")
    (task_dir / "run-tests.sh").write_text("#!/bin/bash\nuv run pytest\n")
    (task_dir / "solution.sh").write_text("#!/bin/bash\necho hi > /app/hello.txt\n")
    (task_dir / "tests").mkdir()
    (task_dir / "tests" / "test_outputs.py").write_text(
        "def test_ok():\n    assert True\n"
    )
    return task_dir


def test_materialize_task_reads_task_yaml_instruction():
    """materialize_task must extract the prompt from task.yaml `instruction`."""
    suite = TerminalBenchSuite()
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        vendor_dir = tmp / "vendor"
        _make_task_yaml_task(vendor_dir, "hello-world")

        workdir = tmp / "workdir"
        task_data = suite.materialize_task("hello-world", workdir, vendor_dir)

    assert "Hello, world!" in task_data["prompt"], task_data["prompt"]
    assert task_data["task_id"] == "hello-world"


def test_materialize_task_does_not_raise_on_missing_optional_files():
    """A task with only task.yaml must not UnboundLocalError on verifier/scorer."""
    suite = TerminalBenchSuite()
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        vendor_dir = tmp / "vendor"
        task_dir = vendor_dir / "terminal-bench" / "original-tasks" / "minimal"
        task_dir.mkdir(parents=True)
        (task_dir / "task.yaml").write_text("instruction: |-\n  Do the thing.\n")

        workdir = tmp / "workdir"
        # Must not raise
        task_data = suite.materialize_task("minimal", workdir, vendor_dir)

    assert task_data["prompt"] == "Do the thing.\n", task_data["prompt"]


def test_run_harbor_job_uses_correct_flags():
    """run_harbor_job must use --n-attempts, --model, --agent, --registry-path."""
    suite = TerminalBenchSuite()
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = list(cmd)
        captured["kwargs"] = kwargs
        import subprocess as sp
        return sp.CompletedProcess(args=cmd, returncode=0, stdout="ok", stderr="")

    with patch("subprocess.run", side_effect=fake_run) as mock:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp) / "workdir"
            workdir.mkdir()
            jobs_dir = Path(tmp) / "jobs"
            result = suite.run_harbor_job(
                task_id="hello-world",
                model_id="nvidia/nemotron-3-ultra-550b-a55b",
                adapter_name="pi_vanilla",
                workdir=workdir,
                jobs_dir=jobs_dir,
                n_attempts=3,
                vendor_dir=Path(tmp) / "vendor",
            )

    cmd = captured["cmd"]
    assert cmd[0] == "harbor", cmd
    assert "run" in cmd, cmd

    # Must use --n-attempts (or -k) for attempts, NOT -n (which is concurrency)
    assert "--n-attempts" in cmd or "-k" in cmd, f"missing --n-attempts/-k in {cmd}"
    assert "3" in cmd, f"n_attempts=3 not forwarded: {cmd}"
    # Must NOT use bare -n for attempts
    # (it's allowed for --n-concurrent, but not as the attempt flag)
    assert "-n" not in [c for c in cmd if c == "-n"] or "--n-attempts" in cmd, cmd

    # Must pass a model
    assert "--model" in cmd or "-m" in cmd, f"missing --model/-m in {cmd}"
    assert "nvidia/nemotron-3-ultra-550b-a55b" in cmd, cmd

    # Must pass an agent
    assert "--agent" in cmd or "-a" in cmd, f"missing --agent/-a in {cmd}"

    assert result["returncode"] == 0, result


def test_run_harbor_job_uses_custom_agent_for_each_adapter_family():
    """Adapter labels must resolve to coding-eval custom Harbor agents."""
    suite = TerminalBenchSuite()
    seen = {}

    def fake_run(cmd, **kwargs):
        import subprocess as sp
        for i, c in enumerate(cmd):
            if c in ("--agent", "-a") and i + 1 < len(cmd):
                seen[current_adapter] = cmd[i + 1]
        return sp.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    with patch("subprocess.run", side_effect=fake_run):
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp) / "w"
            workdir.mkdir()
            jobs = Path(tmp) / "jobs"
            for current_adapter in (
                "pi_vanilla",
                "pi_devstack",
                "pi_superpowers",
                "little_coder",
            ):
                suite.run_harbor_job("t", "test/model", current_adapter, workdir, jobs, 1)

    assert seen["pi_vanilla"] == "harness.harbor_agents:PiVanillaHarborAgent"
    assert seen["pi_devstack"] == "harness.harbor_agents:PiDevstackHarborAgent"
    assert seen["pi_superpowers"] == "harness.harbor_agents:PiSuperpowersHarborAgent"
    assert seen["little_coder"] == "harness.harbor_agents:LittleCoderHarborAgent"


def test_run_harbor_job_uses_distinct_custom_agents_for_adapter_variants():
    """Each harness adapter must map to a distinct custom Harbor agent.

    Otherwise Terminal-Bench would repeat the same built-in Harbor agent under
    different result labels, invalidating the scaffold comparison.
    """
    suite = TerminalBenchSuite()
    seen = {}

    def fake_run(cmd, **kwargs):
        import subprocess as sp
        for i, c in enumerate(cmd):
            if c in ("--agent", "-a") and i + 1 < len(cmd):
                seen[current_adapter] = cmd[i + 1]
        return sp.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    adapters = (
        "pi_vanilla",
        "pi_devstack",
        "pi_superpowers",
        "little_coder",
        "little_coder_superpowers",
    )
    with patch("subprocess.run", side_effect=fake_run):
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp) / "w"
            workdir.mkdir()
            jobs = Path(tmp) / "jobs"
            for current_adapter in adapters:
                suite.run_harbor_job("t", "test/model", current_adapter, workdir, jobs, 1)

    assert set(seen) == set(adapters), seen
    assert len(set(seen.values())) == len(adapters), seen
    assert all(":" in agent for agent in seen.values()), seen
    assert "pi" not in seen.values(), seen
    assert "aider" not in seen.values(), seen


def test_run_harbor_job_sets_pythonpath_for_custom_agent_import():
    """The Harbor subprocess must be able to import harness.* custom agents."""
    suite = TerminalBenchSuite()
    captured = {}

    def fake_run(cmd, **kwargs):
        import subprocess as sp
        captured["env"] = kwargs.get("env", {})
        return sp.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    with patch("subprocess.run", side_effect=fake_run):
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp) / "w"
            workdir.mkdir()
            suite.run_harbor_job(
                "hello-world",
                "test/model",
                "pi_vanilla",
                workdir,
                Path(tmp) / "jobs",
                1,
            )

    pythonpath = captured["env"].get("PYTHONPATH", "")
    assert str(PROJECT_ROOT) in pythonpath.split(os.pathsep), pythonpath


def test_get_terminal_bench_pin_reads_commit_hash():
    """get_terminal_bench_pin must read commit_hash, not the nonexistent 'pin'."""
    from harness.runner import get_terminal_bench_pin
    with tempfile.TemporaryDirectory() as tmp:
        vendor = Path(tmp) / "vendor"
        (vendor / "terminal-bench").mkdir(parents=True)
        (vendor / "terminal-bench" / "registry.json").write_text(json.dumps([
            {
                "name": "terminal-bench-core",
                "version": "head",
                "commit_hash": "abc123def",
                "task_id_subset": None,
            }
        ]))
        pin = get_terminal_bench_pin(vendor)
    assert pin == "abc123def", pin


def test_runner_delegates_terminal_bench_to_harbor():
    """For suite=terminal_bench, run_trial must call run_harbor_job, not adapter.run."""
    from harness.runner import run_trial
    from harness.adapters.pi_vanilla import PiVanillaAdapter

    suite = TerminalBenchSuite()
    adapter = PiVanillaAdapter()

    harbor_calls = []
    adapter_calls = []

    def fake_harbor(self, task_id, model_id, adapter_name, workdir, jobs_dir,
                    n_attempts=1, vendor_dir=None):
        harbor_calls.append((task_id, model_id, adapter_name))
        return {"returncode": 0, "stdout": "", "stderr": ""}

    original_run = adapter.run

    def fake_adapter_run(*a, **kw):
        adapter_calls.append(a)
        import subprocess as sp
        return type("R", (), {"returncode": 0, "usage": None, "error": None})()

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        vendor_dir = tmp / "vendor"
        _make_task_yaml_task(vendor_dir, "hello-world")
        results_dir = tmp / "results"

        with patch.object(TerminalBenchSuite, "run_harbor_job", fake_harbor), \
             patch.object(adapter, "run", fake_adapter_run):
            manifest, verdict = run_trial(
                suite, adapter, "nvidia/nemotron-3-ultra-550b-a55b",
                "hello-world", 1, results_dir, vendor_dir,
            )

    assert len(harbor_calls) == 1, f"run_harbor_job must be called once, got {harbor_calls}"
    assert adapter_calls == [], (
        f"adapter.run must NOT be called for terminal_bench, got {adapter_calls}"
    )
    assert harbor_calls[0][0] == "hello-world"
    assert harbor_calls[0][1] == "nvidia/nemotron-3-ultra-550b-a55b"


def test_runner_terminal_bench_trial_uses_one_harbor_attempt_per_trial():
    """run_trial's trial index must not be forwarded as Harbor attempts.

    The outer runner already loops over k trials. Forwarding trial_k to
    --n-attempts makes k=3 run 1+2+3 attempts instead of 3 comparable trials.
    """
    from harness.runner import run_trial
    from harness.adapters.pi_vanilla import PiVanillaAdapter

    suite = TerminalBenchSuite()
    adapter = PiVanillaAdapter()
    attempts = []

    def fake_harbor(self, task_id, model_id, adapter_name, workdir, jobs_dir,
                    n_attempts=1, vendor_dir=None):
        attempts.append(n_attempts)
        return {"returncode": 0, "stdout": "", "stderr": ""}

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        vendor_dir = tmp / "vendor"
        _make_task_yaml_task(vendor_dir, "hello-world")
        with patch.object(TerminalBenchSuite, "run_harbor_job", fake_harbor):
            run_trial(
                suite,
                adapter,
                "nvidia/nemotron-3-ultra-550b-a55b",
                "hello-world",
                3,
                tmp / "results",
                vendor_dir,
            )

    assert attempts == [1], attempts
