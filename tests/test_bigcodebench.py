import hashlib
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

from harness.adapters.bigcodebench_openai import BigCodeBenchOpenAIAdapter
from harness.runner import run_trial, validate_required_adapter
from harness.suites.bigcodebench import (
    BigCodeBenchHardInstructSuite,
    evaluation_counts,
    groundtruth_pass_rate,
    VERIFY_SCRIPT,
)


ROOT = Path(__file__).parents[1]


class FakeHTTPResponse:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode()
        self.status = 200

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self.payload


def test_public_pilot_specs_match_frozen_ids_without_hidden_artifacts():
    suite = BigCodeBenchHardInstructSuite()
    pilot = json.loads((ROOT / "configs" / "ornith_runtime_pilot_v1.json").read_text())
    pilot_suite = pilot["suites"]["bigcodebench_hard_instruct"]
    expected = [task["id"] for task in pilot_suite["tasks"]]
    assert pilot_suite["status"] == "ready_smoke"
    assert pilot_suite["protocol_spec"] == (
        "configs/bigcodebench_hard_instruct_pilot15.json"
    )
    assert pilot_suite["validity_status"] == {
        "selected_gold_passed": "15/15",
        "selected_null_failed": "15/15",
        "groundtruth_pass_rate": 1.0,
        "representative_task": "BigCodeBench/15",
        "representative_clean_repeats": 3,
        "model_runs": 0,
    }
    specs = json.loads(
        (ROOT / "configs" / "bigcodebench_hard_instruct_pilot15.json").read_text()
    )

    assert suite.get_task_ids(ROOT / "vendor") == expected
    assert [task["task_id"] for task in specs["tasks"]] == expected
    assert specs["source_harness"] == pilot_suite["source"]
    assert specs["protocol"] == {
        "split": "instruct",
        "subset": "hard",
        "samples_per_task": 1,
        "temperature": 0,
        "top_p": 0.95,
        "max_completion_tokens": 1280,
        "instruction_prefix": (
            "Please provide a self-contained Python script that solves the "
            "following problem in a markdown code block:"
        ),
        "calibrated": True,
        "tools": False,
        "system_prompt": None,
    }
    pilot_tasks = {task["id"]: task for task in pilot_suite["tasks"]}
    for task in specs["tasks"]:
        assert set(task) == {
            "task_id",
            "entry_point",
            "instruct_prompt",
            "instruct_prompt_sha256",
        }
        assert hashlib.sha256(task["instruct_prompt"].encode()).hexdigest() == (
            task["instruct_prompt_sha256"]
        )
        assert len(task["instruct_prompt"].encode()) == pilot_tasks[
            task["task_id"]
        ]["prompt_bytes"]
        assert "canonical_solution" not in task
        assert "test" not in task


def test_materialize_exposes_only_the_public_instruct_prompt(tmp_path):
    suite = BigCodeBenchHardInstructSuite()
    task = suite.materialize_task(
        "BigCodeBench/15", tmp_path / "work", ROOT / "vendor"
    )

    assert task["required_adapter"] == "bigcodebench_openai"
    assert task["tool_call_parser"] == "not_applicable_no_tools"
    assert task["temperature"] == 0
    assert task["top_p"] == 0.95
    assert task["max_tokens"] == 1280
    assert task["top_k"] == "not_sent"
    assert task["thinking_policy"] == "not_applicable"
    assert task["sampling_source"] == "bigcodebench_hard_instruct_protocol"
    assert task["prompt"].startswith(
        "Please provide a self-contained Python script that solves the following "
        "problem in a markdown code block:\n"
    )
    assert "Execute a list of shell commands" in task["prompt"]
    assert list((tmp_path / "work").iterdir()) == [tmp_path / "work" / "prompt.txt"]
    assert "canonical_solution" not in task
    assert "test" not in task


def test_bigcodebench_adapter_sends_one_no_tool_chat_request(tmp_path):
    adapter = BigCodeBenchOpenAIAdapter()
    workdir = tmp_path / "work"
    workdir.mkdir()
    response = {
        "id": "chatcmpl-test",
        "model": "ornith-35b-fp8-block",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": "```python\ndef task_func():\n    return 1\n```",
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 10,
            "completion_tokens": 12,
            "total_tokens": 22,
        },
    }
    task = {
        "task_id": "BigCodeBench/15",
        "prompt": "public prompt",
        "model_id": "shisa/ornith-35b-fp8-block",
        "temperature": 0,
        "top_p": 0.95,
        "max_tokens": 1280,
        "timeout": 30,
    }

    with (
        mock.patch(
            "harness.adapters.bigcodebench_openai.load_provider_connection",
            return_value={
                "base_url": "http://model.local/v1",
                "api_key": "secret",
                "model": "ornith-35b-fp8-block",
            },
        ),
        mock.patch(
            "harness.adapters.bigcodebench_openai.urllib.request.urlopen",
            return_value=FakeHTTPResponse(response),
        ) as urlopen,
    ):
        result = adapter.run(
            task,
            workdir,
            tmp_path / "session.log",
            tmp_path / "stderr.log",
        )

    request = urlopen.call_args.args[0]
    payload = json.loads(request.data)
    assert request.full_url == "http://model.local/v1/chat/completions"
    assert request.headers["Authorization"] == "Bearer secret"
    assert payload == {
        "model": "ornith-35b-fp8-block",
        "messages": [{"role": "user", "content": "public prompt"}],
        "n": 1,
        "temperature": 0,
        "top_p": 0.95,
        "max_completion_tokens": 1280,
    }
    assert "tools" not in payload
    assert result.returncode == 0
    assert result.usage.total_tokens == 22
    assert result.behavior["total_tool_calls"] == 0
    sample = json.loads((workdir / "raw-sample.jsonl").read_text())
    assert sample == {
        "task_id": "BigCodeBench/15",
        "raw_solution": "```python\ndef task_func():\n    return 1\n```",
    }
    assert "secret" not in (tmp_path / "session.log").read_text()


def test_bigcodebench_verifier_uses_pinned_offline_container(tmp_path):
    suite = BigCodeBenchHardInstructSuite()
    workdir = tmp_path / "work"
    workdir.mkdir()
    (workdir / "raw-sample.jsonl").write_text(
        json.dumps(
            {
                "task_id": "BigCodeBench/15",
                "raw_solution": "def task_func():\n    return 1",
            }
        )
        + "\n"
    )
    task = suite.materialize_task(
        "BigCodeBench/15", workdir, ROOT / "vendor"
    )

    def fake_run(command, **kwargs):
        (workdir / "dataset.jsonl").write_text("simulated stale hidden data\n")
        (workdir / "sample-sanitized_eval_results.json").write_text(
            json.dumps(
                {
                    "eval": {
                        "BigCodeBench/15": [
                            {
                                "task_id": "BigCodeBench/15",
                                "status": "pass",
                                "details": [True, True, True],
                            }
                        ]
                    }
                }
            )
        )
        return subprocess.CompletedProcess(
            command, 0, "Groundtruth pass rate: 1.000\n", ""
        )

    with mock.patch(
        "harness.suites.bigcodebench.subprocess.run", side_effect=fake_run
    ) as run:
        verdict = suite.verify(task, workdir)

    assert verdict["passed"] is True
    assert verdict["test_count"] == 3
    assert verdict["failure_class"] == "resolved"
    assert not (workdir / "dataset.jsonl").exists()
    run.assert_called_once()
    command = run.call_args.args[0]
    assert command[:3] == ["docker", "run", "--rm"]
    assert "--network" in command and "none" in command
    assert "--cpus" in command and "2" in command
    assert "--memory" in command and "8g" in command
    assert any(value.endswith(":/input/dataset.parquet:ro") for value in command)
    assert suite.verifier_image in command
    assert command[command.index("--entrypoint") + 1] == "python"
    assert "BigCodeBench/15" in command
    assert "pass_k=[1]" in VERIFY_SCRIPT
    assert not any(
        value == "BIGCODEBENCH_OVERRIDE_PATH=/work/dataset.jsonl"
        for value in command
    )


def test_upstream_failure_mapping_is_not_counted_as_passing_tests():
    assert evaluation_counts([True, False, True]) == {
        "test_count": 3,
        "tests_passed": 2,
    }
    assert evaluation_counts(
        {"test_one": "traceback one", "test_two": "traceback two"}
    ) == {
        "test_count": 0,
        "failed_test_count": 2,
    }
    assert groundtruth_pass_rate("Groundtruth pass rate: 1.000") == 1.0
    assert groundtruth_pass_rate("no groundtruth summary") is None


def test_runner_records_nonagentic_sampling_timing_and_zero_tools(tmp_path):
    suite = BigCodeBenchHardInstructSuite()

    class Adapter:
        name = "bigcodebench_openai"
        version = "test"
        uses_pi_session = False
        uses_workspace_sandbox = False

        def run(self, task_data, workdir, log_file, stderr_file):
            (workdir / "raw-sample.jsonl").write_text(
                json.dumps(
                    {
                        "task_id": task_data["task_id"],
                        "raw_solution": "def task_func():\n    return 1",
                    }
                )
                + "\n"
            )
            return SimpleNamespace(
                returncode=0,
                error=None,
                usage=SimpleNamespace(
                    prompt_tokens=10,
                    completion_tokens=20,
                    total_tokens=30,
                ),
                inference_seconds=1.25,
                behavior={
                    "telemetry_status": "observed_nonagentic",
                    "total_tool_calls": 0,
                },
            )

    with (
        mock.patch(
            "harness.runner.load_model_metadata",
            return_value={
                "max_tokens": 81920,
                "sampling_params": {
                    "temperature": 0.6,
                    "top_p": 0.95,
                    "top_k": 20,
                },
            },
        ),
        mock.patch.object(
            suite,
            "verify",
            return_value={"passed": True, "test_count": 1, "exit_code": 0},
        ),
    ):
        manifest, verdict = run_trial(
            suite,
            Adapter(),
            "shisa/ornith-35b-fp8-block",
            "BigCodeBench/15",
            1,
            tmp_path / "results",
            ROOT / "vendor",
            thinking="xhigh",
        )

    assert verdict["passed"] is True
    assert manifest["sampling"]["temperature"] == 0
    assert manifest["sampling"]["top_p"] == 0.95
    assert manifest["sampling"]["max_tokens"] == 1280
    assert manifest["sampling"]["top_k"] == "not_sent"
    assert manifest["sampling"]["thinking"] == "not_applicable"
    assert manifest["sampling"]["source"] == "bigcodebench_hard_instruct_protocol"
    assert manifest["tool_call_parser"] == "not_applicable_no_tools"
    assert manifest["behavior"]["total_tool_calls"] == 0
    assert manifest["timing"]["provider_inference_seconds"] == 1.25
    assert manifest["timing"]["agent_wall_seconds"] >= 0
    assert manifest["timing"]["verifier_seconds"] >= 0
    assert manifest["timing"]["total_wall_seconds"] >= 0
    assert manifest["suite"]["verifier_image"] == suite.verifier_image
    assert manifest["suite"]["source_revision"] == (
        "09dd993f46c3fbf3a799465bb96d524edcb0b199"
    )


def test_runner_rejects_wrong_adapter_for_nonagentic_protocol():
    task = {"required_adapter": "bigcodebench_openai"}
    validate_required_adapter(task, SimpleNamespace(name="bigcodebench_openai"))
    with pytest.raises(ValueError, match="requires adapter 'bigcodebench_openai'"):
        validate_required_adapter(task, SimpleNamespace(name="pi_devstack"))
