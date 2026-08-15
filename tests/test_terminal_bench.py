"""
Tests for Terminal-Bench integration with the runner and Harbor.

Reproduces ORNITH-CODER-REVIEW.md findings #4 and follow-up audit item B:
  - materialize_task must read task.yaml (not instruction.md), and must
    not raise UnboundLocalError on tasks lacking verifier.py/scorer.py.
  - run_harbor_job must use --n-attempts/-k, --model/-m, --agent/-a,
    and a local --path when a vendored task is present.
  - Terminal-Bench must preserve adapter identity via custom Harbor agents,
    not collapse pi_vanilla/pi_devstack/pi_superpowers into the same agent.
  - The runner must delegate terminal_bench trials to run_harbor_job
    instead of the generic adapter path.
"""

import asyncio
import json
import importlib
import os
import runpy
import shutil
import sys
import tempfile
import tomllib
import types
from collections import Counter
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from harness.suites import load_suite
from harness.suites.terminal_bench import TerminalBenchSuite, _parse_task_yaml


def _make_task_yaml_task(vendor_dir: Path, task_id="hello-world"):
    """Create a real-shaped Terminal-Bench task using task.yaml."""
    task_dir = vendor_dir / "terminal-bench" / "tasks" / task_id
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


def _write_pi_session_trace(path: Path, cwd: str = "/terminal-bench/workdir"):
    path.parent.mkdir(parents=True)
    path.write_text("\n".join([
        json.dumps({
            "type": "session",
            "id": "session-terminal-bench",
            "timestamp": "2026-07-05T10:00:00Z",
            "cwd": cwd,
        }),
        json.dumps({
            "type": "message",
            "timestamp": "2026-07-05T10:00:00Z",
            "message": {"role": "user", "content": "fix it"},
        }),
        json.dumps({
            "type": "message",
            "timestamp": "2026-07-05T10:00:02Z",
            "message": {
                "role": "assistant",
                "content": [{
                    "type": "toolCall",
                    "id": "shell-1",
                    "name": "bash",
                    "arguments": {"command": "git status --short"},
                }],
                "provider": "local",
                "model": "Ornith-1.0-35B",
                "responseId": "chatcmpl-terminal-bench",
                "responseModel": "ornith-35b-fp8-block",
                "usage": {
                    "input": 700,
                    "output": 80,
                    "cacheRead": 50,
                    "reasoning": 10,
                    "totalTokens": 840,
                    "cost": {"total": 0.007},
                },
            },
        }),
        json.dumps({
            "type": "message",
            "timestamp": "2026-07-05T10:00:05Z",
            "message": {
                "role": "toolResult",
                "toolCallId": "shell-1",
                "toolName": "bash",
                "content": [{"type": "text", "text": ""}],
                "isError": False,
            },
        }),
        json.dumps({
            "type": "message",
            "timestamp": "2026-07-05T10:00:07Z",
            "message": {
                "role": "assistant",
                "content": [{"type": "text", "text": "done"}],
            },
        }),
    ]) + "\n")


def _make_local_harbor_task(workdir: Path) -> None:
    workdir.mkdir(parents=True, exist_ok=True)
    (workdir / "task.toml").write_text('name = "test-task"\n')


def test_task_yaml_fallback_matches_yaml_chomping_semantics():
    cases = (
        ("instruction: |-\n  Do the thing.\n", "Do the thing."),
        ("instruction: |\n  Do the thing.\n", "Do the thing.\n"),
    )
    for payload, expected in cases:
        with patch.dict(sys.modules, {"yaml": None}):
            parsed = _parse_task_yaml(payload)
        assert parsed["instruction"] == expected


def test_pareto20_panel_is_outcome_blind_stratified_and_loadable():
    manifest_path = (
        PROJECT_ROOT / "configs/terminal_bench_core_pareto20_v1.json"
    )
    manifest = json.loads(manifest_path.read_text())
    pilot_manifest = json.loads(
        (
            PROJECT_ROOT / "configs/terminal_bench_core_pilot8_v1.json"
        ).read_text()
    )
    tasks = manifest["tasks"]
    pilot = json.loads(
        (PROJECT_ROOT / "configs/ornith_runtime_pilot_v1.json").read_text()
    )["suites"]["terminal_bench_core_0_1_1"]
    pilot_ids = {task["id"] for task in pilot["tasks"]}

    selector = runpy.run_path(
        str(PROJECT_ROOT / "scripts/select-terminal-bench-panel.py")
    )
    assert selector["build_manifest"]() == manifest
    assert selector["build_pilot_manifest"]() == pilot_manifest
    assert manifest["selection"]["outcome_blind"] is True
    assert manifest["selection"]["uses_target_model_outcomes"] is False
    assert manifest["qualification"]["status"] == "ready_baseline"
    assert manifest["qualification"]["pilot8_result"] == "3/8"
    assert manifest["qualification"]["budget_exhausted"] == 4
    assert manifest["qualification"]["infrastructure_failures"] == 0
    assert len(tasks) == len({task["task_id"] for task in tasks}) == 20
    assert pilot_ids.issubset(task["task_id"] for task in tasks)
    assert Counter(task["category"] for task in tasks) == Counter(
        manifest["selection"]["category_targets"]
    )
    assert Counter(task["difficulty"] for task in tasks) == Counter(
        manifest["selection"]["difficulty_targets"]
    )
    assert Counter(task["runtime_bucket"] for task in tasks) == Counter(
        manifest["selection"]["runtime_bucket_targets"]
    )
    assert len({task["variant_family"] for task in tasks}) == 20
    assert all("passed" not in task and "resolved" not in task for task in tasks)

    official = load_suite("terminal_bench")
    pilot_suite = load_suite("terminal_bench_core_pilot8")
    pareto = load_suite("terminal_bench_core_pareto20")
    assert official.task_count == len(official.get_task_ids(PROJECT_ROOT / "vendor")) == 80
    assert pilot_suite.task_count == 8
    assert pilot_suite.get_task_ids(PROJECT_ROOT / "vendor") == sorted(pilot_ids)
    assert pareto.task_count == 20
    assert pareto.get_task_ids(PROJECT_ROOT / "vendor") == [
        task["task_id"] for task in tasks
    ]


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
        task_dir = vendor_dir / "terminal-bench" / "tasks" / "minimal"
        task_dir.mkdir(parents=True)
        (task_dir / "task.yaml").write_text("instruction: |-\n  Do the thing.\n")

        workdir = tmp / "workdir"
        # Must not raise
        task_data = suite.materialize_task("minimal", workdir, vendor_dir)

    assert task_data["prompt"] == "Do the thing.", task_data["prompt"]


def test_run_harbor_job_uses_correct_flags():
    """run_harbor_job must use attempts/model/agent and local vendored task path."""
    suite = TerminalBenchSuite()
    captured = {}

    def fake_run(cmd, **kwargs):
        if cmd[:3] == ["harbor", "task", "migrate"]:
            output_dir = Path(cmd[cmd.index("--output") + 1])
            migrated_task = output_dir / "hello-world"
            migrated_task.mkdir(parents=True)
            (migrated_task / "task.toml").write_text(
                'name = "hello-world"\n'
            )
            captured["migrate_cmd"] = list(cmd)
        elif cmd[:2] == ["harbor", "run"]:
            captured["cmd"] = list(cmd)
            captured["kwargs"] = kwargs
            if "--path" in cmd:
                local_path = Path(cmd[cmd.index("--path") + 1])
                captured["local_task_exists"] = (
                    local_path / "hello-world"
                ).exists()
                task_file = local_path / "hello-world" / "task.toml"
                if task_file.exists():
                    captured["task_config"] = tomllib.loads(
                        task_file.read_text()
                    )
        if "--path" in cmd:
            local_path = Path(cmd[cmd.index("--path") + 1])
            captured["local_task_exists"] = (local_path / "hello-world").exists()
        import subprocess as sp
        return sp.CompletedProcess(args=cmd, returncode=0, stdout="ok", stderr="")

    with patch(
        "harness.suites.terminal_bench.run_command", side_effect=fake_run
    ), patch.dict(
        os.environ,
        {"CODING_EVAL_HARBOR_MODEL_BASE_URL": "http://model-relay:8013/v1"},
    ):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            vendor_dir = tmp / "vendor"
            _make_task_yaml_task(vendor_dir, "hello-world")
            (vendor_dir / "terminal-bench" / "registry.json").write_text(json.dumps([
                {
                    "name": "terminal-bench-core",
                    "version": "head",
                    "commit_hash": "head",
                    "task_id_subset": None,
                }
            ]))
            workdir = tmp / "workdir"
            workdir.mkdir()
            jobs_dir = tmp / "jobs"
            result = suite.run_harbor_job(
                task_id="hello-world",
                model_id="nvidia/nemotron-3-ultra-550b-a55b",
                adapter_name="pi_vanilla",
                workdir=workdir,
                jobs_dir=jobs_dir,
                n_attempts=3,
                vendor_dir=vendor_dir,
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

    assert "--path" in cmd, f"missing local --path for vendored task: {cmd}"
    local_path = Path(cmd[cmd.index("--path") + 1])
    assert local_path.name.startswith("_local_tasks_"), cmd
    assert captured["local_task_exists"], cmd
    assert "--registry-path" not in cmd, f"must not resolve vendored smoke remotely: {cmd}"
    assert captured["migrate_cmd"][:3] == ["harbor", "task", "migrate"]
    migrate_input = Path(
        captured["migrate_cmd"][captured["migrate_cmd"].index("--input") + 1]
    )
    assert migrate_input.name == "hello-world", captured["migrate_cmd"]
    task_config = captured["task_config"]
    assert task_config["agent"]["network_mode"] == "allowlist"
    assert task_config["agent"]["allowed_hosts"] == ["model-relay"]
    assert cmd[cmd.index("--allow-agent-host") + 1] == "model-relay"

    assert result["returncode"] == 0, result


def test_run_harbor_job_strips_legacy_solution_yaml_from_migration_copy(tmp_path):
    suite = TerminalBenchSuite()
    vendor_dir = tmp_path / "vendor"
    source = _make_task_yaml_task(vendor_dir, "legacy-solution")
    (source / "solution.sh").unlink()
    (source / "solution.yaml").write_text(
        "- command: echo solved > /app/answer\n"
    )
    captured = {}

    def fake_run(cmd, **kwargs):
        import subprocess as sp

        captured["env"] = kwargs.get("env", {})
        if cmd[:3] == ["harbor", "task", "migrate"]:
            migrate_input = Path(cmd[cmd.index("--input") + 1])
            captured["input"] = migrate_input
            captured["has_legacy_solution"] = (
                migrate_input / "solution.yaml"
            ).exists()
            generated_solution = migrate_input / "solution.sh"
            captured["generated_solution"] = (
                generated_solution.read_text()
                if generated_solution.is_file()
                else None
            )
            output = Path(cmd[cmd.index("--output") + 1]) / "legacy-solution"
            output.mkdir(parents=True)
            (output / "task.toml").write_text('name = "legacy-solution"\n')
        return sp.CompletedProcess(cmd, 0, "", "")

    with patch(
        "harness.suites.terminal_bench.run_command", side_effect=fake_run
    ), patch.dict(
        os.environ,
        {"CODING_EVAL_HARBOR_MODEL_BASE_URL": "http://model-relay:8013/v1"},
    ):
        result = suite.run_harbor_job(
            "legacy-solution",
            "test/model",
            "pi_vanilla",
            tmp_path / "workdir",
            tmp_path / "jobs",
            vendor_dir=vendor_dir,
        )

    assert result["returncode"] == 0
    assert captured["has_legacy_solution"] is False
    assert "echo solved > /app/answer" in captured["generated_solution"]
    assert (source / "solution.yaml").is_file()
    assert not (source / "solution.sh").exists()
    assert captured["input"] != source.resolve()
    assert captured["env"]["CPUS"] == "2"
    assert captured["env"]["MEMORY"] == "8G"
    assert captured["env"]["TEST_DIR"] == "/tests"


def test_terminal_bench_agent_phase_is_model_host_allowlisted(tmp_path):
    """Harbor task setup may use network, but the solving phase may not."""
    task_dir = tmp_path / "task"
    task_dir.mkdir()
    task_file = task_dir / "task.toml"
    task_file.write_text(
        'name = "terminal-bench/example"\n\n'
        '[agent]\n'
        'timeout_sec = 900\n\n'
        '[steps.solve.agent]\n'
        'network_mode = "public"\n'
        'allowed_hosts = ["example.com"]\n'
    )

    TerminalBenchSuite._set_agent_network_allowlist(task_dir, "model-relay")

    data = tomllib.loads(task_file.read_text())
    assert data["agent"]["network_mode"] == "allowlist"
    assert data["agent"]["allowed_hosts"] == ["model-relay"]
    assert data["steps"]["solve"]["agent"]["network_mode"] == "allowlist"
    assert data["steps"]["solve"]["agent"]["allowed_hosts"] == [
        "model-relay"
    ]


def test_run_harbor_job_refuses_task_without_hermetic_policy(tmp_path):
    """A registry/workdir fallback must not silently restore public egress."""
    suite = TerminalBenchSuite()
    workdir = tmp_path / "workdir"
    workdir.mkdir()

    with patch.dict(
        os.environ,
        {"CODING_EVAL_HARBOR_MODEL_BASE_URL": "http://model-relay:8013/v1"},
    ), patch("harness.suites.terminal_bench.run_command") as run:
        result = suite.run_harbor_job(
            "hello-world",
            "test/model",
            "pi_vanilla",
            workdir,
            tmp_path / "jobs",
        )

    assert result["returncode"] == -1
    assert "hermetic" in result["stderr"].lower()
    run.assert_not_called()


def test_harbor_env_accepts_container_reachable_model_override(monkeypatch):
    """Loopback host endpoints need an explicit container-side URL."""
    monkeypatch.setenv(
        "CODING_EVAL_HARBOR_MODEL_BASE_URL", "http://model-relay:8013/v1"
    )
    monkeypatch.setenv("CODING_EVAL_LOCAL_BASE_URL", "http://127.0.0.1:8013/v1")

    env = TerminalBenchSuite()._harbor_env("local/model")

    assert env["CODING_EVAL_PI_PROVIDER_BASE_URL"] == (
        "http://model-relay:8013/v1"
    )


def test_verify_reads_harbor_result_json_rewards():
    """Harbor 0.16 writes trial verdicts to <job>/<trial>/result.json."""
    suite = TerminalBenchSuite()
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        workdir = tmp / "trial-1" / "workdir"
        result_dir = (
            tmp
            / "trial-1"
            / "jobs"
            / "2026-07-04__10-45-00"
            / "hello-world__abc123"
        )
        result_dir.mkdir(parents=True)
        (result_dir / "result.json").write_text(json.dumps({
            "task_name": "hello-world",
            "agent_result": {"output": "done"},
            "verifier_result": {"rewards": {"reward": 1.0}},
            "exception_info": None,
        }))

        verdict = suite.verify({"task_id": "hello-world"}, workdir)

    assert verdict["passed"] is True, verdict
    assert verdict["test_count"] == 1, verdict
    assert verdict["exit_code"] == 0, verdict
    assert not verdict.get("pending", False), verdict
    assert "verifier_result" in verdict["grader_output"], verdict


def test_verify_reports_harbor_result_json_exception_as_failure():
    """Harbor trial exceptions are final failed results, not pending output."""
    suite = TerminalBenchSuite()
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        workdir = tmp / "trial-1" / "workdir"
        result_dir = (
            tmp
            / "trial-1"
            / "jobs"
            / "2026-07-04__10-45-00"
            / "hello-world__abc123"
        )
        result_dir.mkdir(parents=True)
        (result_dir / "result.json").write_text(json.dumps({
            "task_name": "hello-world",
            "verifier_result": None,
            "exception_info": {
                "exception_type": "NonZeroAgentExitCodeError",
                "exception_message": "agent failed",
            },
        }))

        verdict = suite.verify({"task_id": "hello-world"}, workdir)

    assert verdict["passed"] is False, verdict
    assert verdict["exit_code"] == -1, verdict
    assert not verdict.get("pending", False), verdict
    assert "NonZeroAgentExitCodeError" in verdict["grader_output"], verdict


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

    with patch(
        "harness.suites.terminal_bench.run_command", side_effect=fake_run
    ), patch.dict(
        os.environ,
        {"CODING_EVAL_HARBOR_MODEL_BASE_URL": "http://model-relay:8013/v1"},
    ):
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp) / "w"
            _make_local_harbor_task(workdir)
            jobs = Path(tmp) / "jobs"
            for current_adapter in (
                "pi_vanilla",
                "pi_devstack",
                "pi_devstack_superpowers",
                "pi_superpowers",
                "little_coder",
            ):
                suite.run_harbor_job("t", "test/model", current_adapter, workdir, jobs, 1)

    assert seen["pi_vanilla"] == "harness.harbor_agents:PiVanillaHarborAgent"
    assert seen["pi_devstack"] == "harness.harbor_agents:PiDevstackHarborAgent"
    assert (
        seen["pi_devstack_superpowers"]
        == "harness.harbor_agents:PiDevstackSuperpowersHarborAgent"
    )
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
        "pi_devstack_superpowers",
        "pi_superpowers",
        "little_coder",
        "little_coder_superpowers",
    )
    with patch(
        "harness.suites.terminal_bench.run_command", side_effect=fake_run
    ), patch.dict(
        os.environ,
        {"CODING_EVAL_HARBOR_MODEL_BASE_URL": "http://model-relay:8013/v1"},
    ):
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp) / "w"
            _make_local_harbor_task(workdir)
            jobs = Path(tmp) / "jobs"
            for current_adapter in adapters:
                suite.run_harbor_job("t", "test/model", current_adapter, workdir, jobs, 1)

    assert set(seen) == set(adapters), seen
    assert len(set(seen.values())) == len(adapters), seen
    assert all(":" in agent for agent in seen.values()), seen
    assert "pi" not in seen.values(), seen
    assert "aider" not in seen.values(), seen


def test_run_harbor_job_mounts_runtime_for_all_and_profile_only_for_devstack():
    """Every Harbor arm gets pi offline; only devstack gets package mounts."""
    suite = TerminalBenchSuite()
    commands = {}

    def fake_run(cmd, **kwargs):
        import subprocess as sp
        if cmd[:2] == ["harbor", "run"]:
            commands[current_adapter] = list(cmd)
        return sp.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        runtime = tmp / "runtime"
        (runtime / "bin").mkdir(parents=True)
        for executable in ("node", "pi", "little-coder"):
            (runtime / "bin" / executable).write_text("#!/bin/sh\n")
        compat_node = tmp / "compat-node"
        (compat_node / "bin").mkdir(parents=True)
        (compat_node / "bin" / "node").write_text("#!/bin/sh\n")
        profile = tmp / "profile"
        (profile / "npm").mkdir(parents=True)
        (profile / "git").mkdir()
        (profile / "settings.json").write_text(json.dumps({
            "packages": ["npm:pi-context-prune@1.2.0"],
        }))
        workdir = tmp / "workdir"
        _make_local_harbor_task(workdir)

        with patch.dict(
            os.environ,
            {
                "CODING_EVAL_DEVSTACK_PROFILE_DIR": str(profile),
                "CODING_EVAL_PI_RUNTIME_DIR": str(runtime),
                "CODING_EVAL_PI_COMPAT_NODE_DIR": str(compat_node),
                "CODING_EVAL_HARBOR_MODEL_BASE_URL": (
                    "http://model-relay:8013/v1"
                ),
            },
        ), patch(
            "harness.suites.terminal_bench.run_command",
            side_effect=fake_run,
        ):
            for current_adapter in (
                "pi_vanilla",
                "pi_devstack",
                "pi_devstack_superpowers",
            ):
                suite.run_harbor_job(
                    "hello-world",
                    "test/model",
                    current_adapter,
                    workdir,
                    tmp / "jobs",
                    1,
                )

    runtime_mount = {
        "type": "bind",
        "source": str(runtime.resolve()),
        "target": "/opt/coding-eval-pi-runtime",
        "read_only": True,
    }
    compat_mount = {
        "type": "bind",
        "source": str(compat_node.resolve()),
        "target": "/opt/coding-eval-node-compat",
        "read_only": True,
    }
    vanilla = commands["pi_vanilla"]
    assert json.loads(vanilla[vanilla.index("--mounts") + 1]) == [
        runtime_mount,
        compat_mount,
    ]
    for adapter in ("pi_devstack", "pi_devstack_superpowers"):
        cmd = commands[adapter]
        assert "--mounts" in cmd, cmd
        mounts = json.loads(cmd[cmd.index("--mounts") + 1])
        assert mounts == [
            runtime_mount,
            compat_mount,
            {
                "type": "bind",
                "source": str(profile.resolve() / "npm"),
                "target": "/opt/coding-eval-devstack/npm",
                "read_only": True,
            },
            {
                "type": "bind",
                "source": str(profile.resolve() / "git"),
                "target": "/opt/coding-eval-devstack/git",
                "read_only": True,
            },
            {
                "type": "bind",
                "source": str(profile.resolve() / "settings.json"),
                "target": "/opt/coding-eval-devstack/settings.json",
                "read_only": True,
            },
        ]


def test_default_harbor_devstack_profile_disables_headless_unsafe_packages(tmp_path):
    """No-network containers must not initialize browser/TUI-only extensions."""
    home = tmp_path / "home"
    profile = home / ".pi" / "agent"
    (profile / "npm").mkdir(parents=True)
    (profile / "git").mkdir()
    original_settings = {
        "defaultProvider": "local",
        "packages": [
            "npm:pi-context-prune",
            "npm:@the-forge-flow/camoufox-pi@0.2.1",
            "https://github.com/lhl/pi-zentui",
        ],
    }
    (profile / "settings.json").write_text(json.dumps(original_settings))

    with patch.dict(
        os.environ, {"CODING_EVAL_DEVSTACK_PROFILE_DIR": ""}
    ), patch("harness.suites.terminal_bench.Path.home", return_value=home):
        mounts = TerminalBenchSuite()._devstack_mounts("pi_devstack")

    settings_mount = next(
        mount
        for mount in mounts
        if mount["target"] == "/opt/coding-eval-devstack/settings.json"
    )
    assert settings_mount["source"] != str(profile / "settings.json")
    sanitized = json.loads(Path(settings_mount["source"]).read_text())
    assert sanitized["defaultProvider"] == "local"
    assert sanitized["packages"][0] == "npm:pi-context-prune"
    for entry in sanitized["packages"][1:]:
        assert entry["extensions"] == []
        assert entry["skills"] == []
        assert entry["prompts"] == []
        assert entry["themes"] == []


def test_run_harbor_job_sets_pythonpath_for_custom_agent_import():
    """The Harbor subprocess must be able to import harness.* custom agents."""
    suite = TerminalBenchSuite()
    captured = {}

    def fake_run(cmd, **kwargs):
        import subprocess as sp
        captured["env"] = kwargs.get("env", {})
        return sp.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    with patch(
        "harness.suites.terminal_bench.run_command", side_effect=fake_run
    ), patch.dict(
        os.environ,
        {"CODING_EVAL_HARBOR_MODEL_BASE_URL": "http://model-relay:8013/v1"},
    ):
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp) / "w"
            _make_local_harbor_task(workdir)
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


def test_harbor_env_exports_host_pi_provider_for_container_agent():
    """Terminal-Bench containers need the selected host pi provider config."""
    suite = TerminalBenchSuite()

    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp) / "home"
        models_json = home / ".pi" / "agent" / "models.json"
        models_json.parent.mkdir(parents=True)
        models_json.write_text(json.dumps({
            "providers": {
                "hf": {
                    "baseUrl": "http://127.0.0.1:8000/v1",
                    "apiKeyEnv": "HF_API_KEY",
                    "api": "openai-completions",
                    "models": [
                        {
                            "id": "Qwen/Qwen2.5-Coder-7B-Instruct",
                            "name": "Qwen Coder",
                        }
                    ],
                }
            }
        }))

        with patch("harness.suites.terminal_bench.Path.home", return_value=home), \
             patch.dict(os.environ, {"HF_API_KEY": "secret-key"}):
            env = suite._harbor_env("hf/Qwen/Qwen2.5-Coder-7B-Instruct")

    assert env["CODING_EVAL_PI_PROVIDER_NAME"] == "hf"
    assert env["CODING_EVAL_PI_PROVIDER_BASE_URL"] == "http://127.0.0.1:8000/v1"
    assert env["CODING_EVAL_PI_PROVIDER_API_KEY"] == "secret-key"
    assert env["CODING_EVAL_PI_PROVIDER_API"] == "openai-completions"
    assert env["CODING_EVAL_PI_PROVIDER_MODEL_ID"] == "Qwen/Qwen2.5-Coder-7B-Instruct"
    assert env["CODING_EVAL_PI_PROVIDER_MODEL_NAME"] == "Qwen Coder"


def test_run_harbor_job_exports_thinking_to_container_agent_env():
    """Pinned thinking must reach the Harbor subprocess that imports the agent."""
    suite = TerminalBenchSuite()
    captured = {}

    def fake_run(cmd, **kwargs):
        import subprocess as sp
        if cmd[:2] == ["harbor", "run"]:
            captured["env"] = kwargs.get("env", {})
        return sp.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    with patch(
        "harness.suites.terminal_bench.run_command", side_effect=fake_run
    ), patch.dict(
        os.environ,
        {"CODING_EVAL_HARBOR_MODEL_BASE_URL": "http://model-relay:8013/v1"},
    ):
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp) / "w"
            _make_local_harbor_task(workdir)
            suite.run_harbor_job(
                "hello-world",
                "test/model",
                "pi_vanilla",
                workdir,
                Path(tmp) / "jobs",
                1,
                thinking="high",
            )

    assert captured["env"]["CODING_EVAL_THINKING"] == "high"
    assert captured["env"]["CODING_EVAL_REASONING_EFFORT"] == "high"


def test_harbor_env_exports_repo_sampling_profile(tmp_path):
    """Container pi config must use the same profile recorded by the runner."""
    home = tmp_path / "home"
    models_dir = home / ".pi" / "agent"
    models_dir.mkdir(parents=True)
    (models_dir / "models.json").write_text(json.dumps({
        "providers": {
            "local": {
                "baseUrl": "http://model-relay:8013/v1",
                "models": [{
                    "id": "Qwen3.8-27B",
                    "name": "Qwen 3.8 27B",
                    "thinkingLevelMap": {
                        "high": None,
                        "low": "low",
                        "medium": "medium",
                        "minimal": None,
                        "off": "none",
                        "xhigh": "xhigh",
                    },
                    "compat": {
                        "supportsDeveloperRole": False,
                        "supportsReasoningEffort": True,
                        "maxTokensField": "max_tokens",
                    },
                }],
            }
        }
    }))

    with patch("harness.suites.terminal_bench.Path.home", return_value=home):
        env = TerminalBenchSuite()._harbor_env("local/qwen3.8-27b")

    assert json.loads(env["CODING_EVAL_PI_SAMPLING_PARAMS"]) == {
        "temperature": 1.0,
        "top_p": 0.95,
        "top_k": 20,
        "min_p": 0.0,
        "presence_penalty": 0.0,
        "repetition_penalty": 1.0,
    }
    assert env["CODING_EVAL_PI_CONTEXT_WINDOW"] == "262144"
    assert env["CODING_EVAL_PI_MAX_TOKENS"] == "131072"
    assert json.loads(env["CODING_EVAL_PI_THINKING_LEVEL_MAP"]) == {
        "high": None,
        "low": "low",
        "medium": "medium",
        "minimal": None,
        "off": "none",
        "xhigh": "xhigh",
    }
    assert json.loads(env["CODING_EVAL_PI_COMPAT"]) == {
        "supportsDeveloperRole": False,
        "supportsReasoningEffort": True,
        "maxTokensField": "max_tokens",
    }


def _import_harbor_agents_with_fake_native_harbor(monkeypatch):
    """Import the modern Harbor agent branch without Harbor installed."""
    for name in list(sys.modules):
        if name == "harness.harbor_agents" or name.startswith("harbor"):
            monkeypatch.delitem(sys.modules, name, raising=False)

    class FakeBaseInstalledAgent:
        def __init__(self, model_name, *args, **kwargs):
            self.model_name = model_name
            self.root_commands = []
            self.agent_commands = []

        def version(self):
            return None

        async def exec_as_root(self, environment, *, command, env=None):
            self.root_commands.append(command)

        async def exec_as_agent(self, environment, *, command, env=None):
            self.agent_commands.append(command)

    module_names = (
        "harbor",
        "harbor.agents",
        "harbor.agents.installed",
        "harbor.environments",
        "harbor.models",
        "harbor.models.agent",
    )
    for name in module_names:
        monkeypatch.setitem(sys.modules, name, types.ModuleType(name))

    base_mod = types.ModuleType("harbor.agents.installed.base")
    base_mod.BaseInstalledAgent = FakeBaseInstalledAgent
    environment_mod = types.ModuleType("harbor.environments.base")
    environment_mod.BaseEnvironment = object
    context_mod = types.ModuleType("harbor.models.agent.context")
    context_mod.AgentContext = object
    monkeypatch.setitem(sys.modules, "harbor.agents.installed.base", base_mod)
    monkeypatch.setitem(sys.modules, "harbor.environments.base", environment_mod)
    monkeypatch.setitem(sys.modules, "harbor.models.agent.context", context_mod)

    return importlib.import_module("harness.harbor_agents")


def test_native_harbor_agent_bootstrap_supports_non_debian_images(monkeypatch):
    """Agent setup must not unconditionally invoke apt-get on Amazon Linux."""
    harbor_agents = _import_harbor_agents_with_fake_native_harbor(monkeypatch)
    agent = harbor_agents.PiVanillaHarborAgent("local/muse-glimmer-30b")

    with patch.dict(os.environ, {
        "CODING_EVAL_PI_PROVIDER_BASE_URL": "http://model-relay:8013/v1",
        "CODING_EVAL_PI_SAMPLING_PARAMS": json.dumps({
            "temperature": 1.0,
            "top_p": 0.95,
            "top_k": 64,
        }),
        "CODING_EVAL_PI_THINKING_LEVEL_MAP": json.dumps({
            "high": "high",
            "xhigh": "xhigh",
        }),
        "CODING_EVAL_PI_COMPAT": json.dumps({
            "supportsReasoningEffort": True,
        }),
    }):
        asyncio.run(agent.install(object()))

    dependency_command = agent.root_commands[0]
    assert "command -v curl" in dependency_command
    assert "command -v apt-get" in dependency_command
    assert "command -v dnf" in dependency_command
    assert "command -v apk" in dependency_command
    install_command = agent.agent_commands[0]
    assert 'nvm_dir="${NVM_DIR:-$HOME/.nvm}"' in install_command
    assert '. "$nvm_dir/nvm.sh"' in install_command
    assert "/opt/coding-eval-pi-runtime/bin/pi" in install_command
    assert "/opt/coding-eval-node-compat/bin/node" in install_command
    config_command = agent.agent_commands[-1]
    assert "CODING_EVAL_PI_SAMPLING_PARAMS" in config_command
    assert "samplingParams" in config_command
    assert "CODING_EVAL_PI_THINKING_LEVEL_MAP" in config_command
    assert "thinkingLevelMap" in config_command
    assert "CODING_EVAL_PI_COMPAT" in config_command

    asyncio.run(agent.run("fix it", object(), object()))
    run_command = agent.agent_commands[-1]
    assert '. "${NVM_DIR:-$HOME/.nvm}/nvm.sh"' in run_command
    assert "nvm use 22" in run_command
    assert "/opt/coding-eval-pi-runtime/bin/pi" in run_command


def test_legacy_harbor_agent_bootstrap_supports_non_debian_images():
    """The legacy setup template must retain the same package portability."""
    template = (PROJECT_ROOT / "harness" / "harbor-agent-setup.sh.j2").read_text()

    assert "command -v curl" in template
    assert "command -v apt-get" in template
    assert "command -v dnf" in template
    assert "command -v apk" in template
    assert 'nvm_dir="${NVM_DIR:-$HOME/.nvm}"' in template
    assert '. "$nvm_dir/nvm.sh"' in template


def test_setup_pins_legacy_glibc_node_runtime():
    setup = (PROJECT_ROOT / "scripts" / "setup.sh").read_text()

    assert "node-v22.14.0-linux-x64-glibc-217.tar.xz" in setup
    assert "b7446cee2e84cfadd33a1d73949056084daa344502234729f5757615f356de01" in setup
    assert "cospa-node-v22.14.0-glibc217" in setup


def _import_harbor_agents_with_fake_terminal_bench(monkeypatch):
    """Import harbor_agents without requiring Terminal-Bench's full deps."""
    for name in list(sys.modules):
        if name == "harness.harbor_agents" or name.startswith("terminal_bench"):
            monkeypatch.delitem(sys.modules, name, raising=False)

    class FakeAbstractInstalledAgent:
        def __init__(self, *args, **kwargs):
            self._version = kwargs.get("version", "latest")

        @property
        def version(self):
            return self._version

        def _get_templated_script_path(self, template_name="setup.sh.j2"):
            return Path(template_name)

    class FakeTerminalCommand:
        def __init__(
            self,
            *,
            command,
            min_timeout_sec,
            max_timeout_sec,
            block,
            append_enter,
        ):
            self.command = command
            self.min_timeout_sec = min_timeout_sec
            self.max_timeout_sec = max_timeout_sec
            self.block = block
            self.append_enter = append_enter

    terminal_bench = types.ModuleType("terminal_bench")
    agents = types.ModuleType("terminal_bench.agents")
    installed_agents = types.ModuleType("terminal_bench.agents.installed_agents")
    abstract_mod = types.ModuleType(
        "terminal_bench.agents.installed_agents.abstract_installed_agent"
    )
    abstract_mod.AbstractInstalledAgent = FakeAbstractInstalledAgent
    terminal = types.ModuleType("terminal_bench.terminal")
    models_mod = types.ModuleType("terminal_bench.terminal.models")
    models_mod.TerminalCommand = FakeTerminalCommand

    monkeypatch.setitem(sys.modules, "terminal_bench", terminal_bench)
    monkeypatch.setitem(sys.modules, "terminal_bench.agents", agents)
    monkeypatch.setitem(
        sys.modules,
        "terminal_bench.agents.installed_agents",
        installed_agents,
    )
    monkeypatch.setitem(
        sys.modules,
        "terminal_bench.agents.installed_agents.abstract_installed_agent",
        abstract_mod,
    )
    monkeypatch.setitem(sys.modules, "terminal_bench.terminal", terminal)
    monkeypatch.setitem(sys.modules, "terminal_bench.terminal.models", models_mod)

    return importlib.import_module("harness.harbor_agents")


def test_harbor_devstack_agents_install_mounted_profile(monkeypatch):
    """Devstack labels must install the mounted profile in the task container."""
    harbor_agents = _import_harbor_agents_with_fake_terminal_bench(monkeypatch)

    assert harbor_agents.PiVanillaHarborAgent.include_devstack_profile is False
    assert harbor_agents.PiDevstackHarborAgent.include_devstack_profile is True
    assert (
        harbor_agents.PiDevstackSuperpowersHarborAgent.include_devstack_profile
        is True
    )
    command = harbor_agents._devstack_profile_install_command()
    assert "profile_root=/opt/coding-eval-devstack" in command
    assert 'test -d "$profile_root/npm"' in command
    assert 'test -d "$profile_root/git"' in command
    assert 'test -f "$profile_root/settings.json"' in command
    assert 'ln -s "$profile_root/npm" "$agent_dir/npm"' in command
    assert 'ln -s "$profile_root/git" "$agent_dir/git"' in command
    assert 'cp "$profile_root/settings.json" "$agent_dir/settings.json"' in command
    assert "pi list" in command


def test_harbor_agent_cli_forwards_configured_thinking(monkeypatch):
    """The custom container agents must pass --thinking to pi/little-coder."""
    harbor_agents = _import_harbor_agents_with_fake_terminal_bench(monkeypatch)

    with patch.dict(os.environ, {"CODING_EVAL_THINKING": "high"}):
        agent = harbor_agents.PiDevstackHarborAgent("local/ornith-1.0-35b")
        command = agent._run_agent_commands("solve it")[0].command

    assert "--thinking high" in command, command
    assert '. "${NVM_DIR:-$HOME/.nvm}/nvm.sh"' in command
    assert "nvm use 22" in command


def test_harbor_agent_cli_exports_pi_session_traces(monkeypatch):
    """Terminal-Bench agents must persist pi JSONL traces as Harbor artifacts."""
    harbor_agents = _import_harbor_agents_with_fake_terminal_bench(monkeypatch)

    agent = harbor_agents.PiDevstackHarborAgent("local/ornith-1.0-35b")
    command = agent._run_agent_commands("solve it")[0].command

    assert "$HOME/.pi/agent/sessions" in command, command
    assert "/logs/artifacts/pi-sessions" in command, command
    assert "find" in command and "*.jsonl" in command, command


def test_harbor_agent_cli_omits_thinking_when_unset(monkeypatch):
    """Default effort must remain provider/model default unless pinned."""
    harbor_agents = _import_harbor_agents_with_fake_terminal_bench(monkeypatch)

    with patch.dict(os.environ, {}, clear=True):
        agent = harbor_agents.PiDevstackHarborAgent("local/ornith-1.0-35b")
        command = agent._run_agent_commands("solve it")[0].command

    assert "--thinking" not in command, command


def test_get_task_ids_uses_only_terminal_bench_core_0_1_1_subset():
    """Discovery must use Core 0.1.1, never the mutable head entry."""
    suite = TerminalBenchSuite()
    with tempfile.TemporaryDirectory() as tmp:
        vendor = Path(tmp) / "vendor"
        tb_dir = vendor / "terminal-bench"
        (tb_dir / "tasks" / "pinned-one").mkdir(parents=True)
        (tb_dir / "tasks" / "pinned-two").mkdir(parents=True)
        (tb_dir / "original-tasks" / "head-only").mkdir(parents=True)
        manifest_path = Path(tmp) / "terminal-bench-core-0.1.1.json"
        manifest_path.write_text(json.dumps({
            "name": "terminal-bench-core",
            "version": "0.1.1",
            "dataset_path": "tasks",
            "commit_hash": "91e10457b5410f16c44364da1a34cb6de8c488a5",
            "task_ids": ["pinned-two", "pinned-one"],
        }))
        suite.manifest_path = manifest_path

        task_ids = suite.get_task_ids(vendor)

    assert suite.version == "0.1.1"
    assert task_ids == ["pinned-one", "pinned-two"]
    assert "head-only" not in task_ids


def test_get_terminal_bench_pin_reads_0_1_1_commit_hash():
    """The manifest pin must match Core 0.1.1, even when head comes first."""
    from harness.runner import get_terminal_bench_pin
    with tempfile.TemporaryDirectory() as tmp:
        vendor = Path(tmp) / "vendor"
        pin = get_terminal_bench_pin(vendor)
    assert pin == "91e10457b5410f16c44364da1a34cb6de8c488a5", pin


def test_runner_delegates_terminal_bench_to_harbor():
    """For suite=terminal_bench, run_trial must call run_harbor_job, not adapter.run."""
    from harness.runner import run_trial
    from harness.adapters.pi_vanilla import PiVanillaAdapter

    suite = TerminalBenchSuite()
    adapter = PiVanillaAdapter()

    harbor_calls = []
    adapter_calls = []

    def fake_harbor(self, task_id, model_id, adapter_name, workdir, jobs_dir,
                    n_attempts=1, vendor_dir=None, thinking=None):
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


def test_runner_treats_harbor_agent_exception_as_infrastructure():
    """A Harbor command exit 0 must not hide a failed agent phase."""
    from harness.adapters.pi_vanilla import PiVanillaAdapter
    from harness.runner import run_trial

    suite = TerminalBenchSuite()
    adapter = PiVanillaAdapter()

    def fake_harbor(
        self,
        task_id,
        model_id,
        adapter_name,
        workdir,
        jobs_dir,
        n_attempts=1,
        vendor_dir=None,
        thinking=None,
    ):
        trial_dir = Path(jobs_dir) / "job" / "trial"
        trial_dir.mkdir(parents=True)
        (trial_dir / "result.json").write_text(json.dumps({
            "task_name": task_id,
            "agent_result": None,
            "verifier_result": {"rewards": {"reward": 0.0}},
            "exception_info": {
                "exception_type": "NonZeroAgentExitCodeError",
                "exception_message": "pi: command not found",
            },
        }))
        return {"returncode": 0, "stdout": "", "stderr": ""}

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        vendor_dir = tmp_path / "vendor"
        _make_task_yaml_task(vendor_dir, "hello-world")
        with patch.object(TerminalBenchSuite, "run_harbor_job", fake_harbor), \
             patch.object(suite, "verify") as verify:
            verify.return_value = {"passed": True, "test_count": 1, "exit_code": 0}
            manifest, verdict = run_trial(
                suite,
                adapter,
                "local/muse-glimmer-30b",
                "hello-world",
                1,
                tmp_path / "results",
                vendor_dir,
            )

    verify.assert_not_called()
    assert manifest["exit_code"] == -1
    assert "pi: command not found" in manifest["error"]
    assert verdict["adapter_failed"] is True


def test_runner_rejects_observed_thinking_level_mismatch():
    """A requested xhigh run must not be scored when pi silently uses high."""
    from harness.adapters.pi_vanilla import PiVanillaAdapter
    from harness.runner import run_trial

    suite = TerminalBenchSuite()
    adapter = PiVanillaAdapter()

    def fake_harbor(
        self,
        task_id,
        model_id,
        adapter_name,
        workdir,
        jobs_dir,
        n_attempts=1,
        vendor_dir=None,
        thinking=None,
    ):
        trial_dir = Path(jobs_dir) / "job" / "trial"
        session_path = trial_dir / "artifacts" / "pi-sessions" / "session.jsonl"
        _write_pi_session_trace(session_path)
        events = [json.loads(line) for line in session_path.read_text().splitlines()]
        events.insert(1, {
            "type": "thinking_level_change",
            "timestamp": "2026-07-05T10:00:00Z",
            "thinkingLevel": "high",
        })
        session_path.write_text(
            "\n".join(json.dumps(event) for event in events) + "\n"
        )
        (trial_dir / "result.json").write_text(json.dumps({
            "task_name": task_id,
            "agent_result": {"output": "done"},
            "verifier_result": {"rewards": {"reward": 1.0}},
            "exception_info": None,
        }))
        return {"returncode": 0, "stdout": "", "stderr": ""}

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        vendor_dir = tmp_path / "vendor"
        _make_task_yaml_task(vendor_dir, "hello-world")
        with patch.object(TerminalBenchSuite, "run_harbor_job", fake_harbor), \
             patch.object(suite, "verify") as verify:
            verify.return_value = {"passed": True, "test_count": 1, "exit_code": 0}
            manifest, verdict = run_trial(
                suite,
                adapter,
                "local/muse-glimmer-30b",
                "hello-world",
                1,
                tmp_path / "results",
                vendor_dir,
                thinking="xhigh",
            )

    verify.assert_not_called()
    assert manifest["exit_code"] == -1
    assert manifest["thinking_mismatch"] == {
        "requested": "xhigh",
        "observed": "high",
    }
    assert verdict["adapter_failed"] is True
    assert "thinking level mismatch" in verdict["grader_output"].lower()


def test_runner_records_terminal_bench_harbor_usage_trace():
    """Terminal-Bench trials should summarize pi traces exported by Harbor."""
    from harness.runner import run_trial
    from harness.adapters.pi_vanilla import PiVanillaAdapter

    suite = TerminalBenchSuite()
    adapter = PiVanillaAdapter()

    def fake_harbor(self, task_id, model_id, adapter_name, workdir, jobs_dir,
                    n_attempts=1, vendor_dir=None, thinking=None):
        trial_dir = (
            Path(jobs_dir)
            / "2026-07-05__10-00-00"
            / "hello-world__abc123"
        )
        _write_pi_session_trace(
            trial_dir / "artifacts" / "pi-sessions" / "session.jsonl"
        )
        (trial_dir / "result.json").write_text(json.dumps({
            "task_name": "hello-world",
            "agent_result": {"output": "done"},
            "verifier_result": {"rewards": {"reward": 1.0}},
            "exception_info": None,
        }))
        return {"returncode": 0, "stdout": "", "stderr": ""}

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        vendor_dir = tmp / "vendor"
        _make_task_yaml_task(vendor_dir, "hello-world")
        results_dir = tmp / "results"

        with patch.object(TerminalBenchSuite, "run_harbor_job", fake_harbor):
            manifest, verdict = run_trial(
                suite,
                adapter,
                "local/ornith-1.0-35b",
                "hello-world",
                1,
                results_dir,
                vendor_dir,
            )

    assert verdict["passed"] is True
    usage = manifest["token_usage"]
    assert usage["status"] == "observed"
    assert usage["prompt_tokens"] == 700
    assert usage["completion_tokens"] == 80
    assert usage["cost_usd"] == 0.007
    assert usage["trace_files"] == ["out/pi_session.jsonl"]
    behavior = manifest["behavior"]
    assert behavior["status"] == "observed"
    assert behavior["tool_calls"] == 1
    assert behavior["tool_counts"] == {"bash": 1}
    assert behavior["tool_seconds"] == 3.0
    assert behavior["inference_seconds"] == 4.0


def test_runner_delegates_terminal_bench_thinking_to_harbor():
    """Runner --thinking must reach Harbor-backed Terminal-Bench trials."""
    from harness.runner import run_trial
    from harness.adapters.pi_vanilla import PiVanillaAdapter

    suite = TerminalBenchSuite()
    adapter = PiVanillaAdapter()
    thinking_values = []

    def fake_harbor(self, task_id, model_id, adapter_name, workdir, jobs_dir,
                    n_attempts=1, vendor_dir=None, thinking=None):
        thinking_values.append(thinking)
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
                1,
                tmp / "results",
                vendor_dir,
                thinking="high",
            )

    assert thinking_values == ["high"], thinking_values


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
                    n_attempts=1, vendor_dir=None, thinking=None):
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
