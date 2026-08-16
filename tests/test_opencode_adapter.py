"""Controlled OpenCode baseline/Superpowers adapter tests."""

import json
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import UUID

import pytest

from harness import runner
from harness.adapters import load_adapter
from harness.adapters import opencode
from harness.runner import _manifest_tool_call_parser
from harness.skill_profiles import BENCH_SKILLS_ROOT


def test_opencode_adapters_are_registered_and_distinct():
    """The 2x2 harness axis must not collapse its baseline and treatment."""
    vanilla = load_adapter("opencode_vanilla")
    superpowers = load_adapter("opencode_superpowers")

    assert vanilla.name == "opencode_vanilla"
    assert superpowers.name == "opencode_superpowers"
    assert vanilla.skills_enabled is False
    assert superpowers.skills_enabled is True
    assert vanilla.manifest_metadata() != superpowers.manifest_metadata()


@contextmanager
def _fake_openai_server():
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("content-length", "0"))
            payload = json.loads(self.rfile.read(length))
            requests.append(
                {
                    "path": self.path,
                    "authorization": self.headers.get("Authorization"),
                    "headers": dict(self.headers),
                    "payload": payload,
                }
            )
            chunk = {
                "id": "chatcmpl-test",
                "object": "chat.completion.chunk",
                "created": 1,
                "model": payload["model"],
                "choices": [
                    {
                        "index": 0,
                        "delta": {"role": "assistant", "content": "OK"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 11,
                    "completion_tokens": 2,
                    "total_tokens": 13,
                },
            }
            body = f"data: {json.dumps(chunk)}\n\ndata: [DONE]\n\n".encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address[1], requests
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


def _connection() -> dict:
    return {
        "base_url": "http://proxy.internal:8989/gateway/v1",
        "api_key": "test-secret",
        "api": "openai-completions",
        "model": "ornith-35b-fp8-block",
    }


def _task_data() -> dict:
    return {
        "model_id": "shisa/ornith-35b-fp8-block",
        "sampling_params": {"temperature": 0.6, "top_p": 0.95, "top_k": 20},
        "context_window": 262144,
        "max_tokens": 81920,
        "timeout": 600,
        "client_session_id": "123e4567-e89b-12d3-a456-426614174000",
    }


def test_opencode_fails_closed_for_unimplemented_harbor_protocol():
    """An OpenCode-labeled Harbor cell must never silently execute Pi."""

    class HarborSuite:
        def run_harbor_job(self):
            raise AssertionError("must not run")

    with pytest.raises(ValueError, match="no distinct Harbor agent"):
        runner.validate_suite_adapter_compatibility(
            HarborSuite(), load_adapter("opencode_vanilla")
        )


def test_opencode_manifest_records_its_real_tool_parser():
    adapter = load_adapter("opencode_vanilla")

    assert _manifest_tool_call_parser({}, adapter) == (
        "opencode-1.18.8-ai-sdk-openai-compatible"
    )


def test_opencode_connection_preserves_pi_proxy_topology(tmp_path, monkeypatch):
    """Provider translation must retain the existing proxy host, port, and path."""
    models_path = tmp_path / "models.json"
    models_path.write_text(
        """{
  "providers": {
    "shisa": {
      "baseUrl": "http://proxy.internal:8989/gateway/v1",
      "api": "openai-completions",
      "apiKey": "fallback",
      "apiKeyEnv": "SHISA_TEST_KEY",
      "models": [{"id": "ornith-35b-fp8-block"}]
    }
  }
}\n"""
    )
    monkeypatch.setenv("SHISA_TEST_KEY", "resolved-secret")

    connection = opencode.load_opencode_connection(
        "shisa/ornith-35b-fp8-block", models_json_path=models_path
    )

    assert connection == {
        "base_url": "http://proxy.internal:8989/gateway/v1",
        "api_key": "resolved-secret",
        "api": "openai-completions",
        "model": "ornith-35b-fp8-block",
    }


def test_opencode_config_pins_route_sampling_and_pi_comparable_tools():
    """The baseline must preserve the endpoint and expose only Pi-like tools."""
    config = opencode.build_opencode_config(
        _task_data(), _connection(), skills_enabled=False
    )

    provider = config["provider"]["cospa"]
    assert provider["npm"] == "@ai-sdk/openai-compatible"
    assert provider["options"]["baseURL"] == "http://proxy.internal:8989/gateway/v1"
    assert provider["options"]["apiKey"] == "test-secret"
    assert provider["options"]["headers"] == {
        "X-Session-Id": "123e4567-e89b-12d3-a456-426614174000",
        "x-session-affinity": "123e4567-e89b-12d3-a456-426614174000",
    }
    assert provider["models"]["ornith-35b-fp8-block"]["limit"] == {
        "context": 262144,
        "output": 81920,
    }
    assert provider["models"]["ornith-35b-fp8-block"]["headers"] == {
        "X-Session-Id": "123e4567-e89b-12d3-a456-426614174000",
        "x-session-affinity": "123e4567-e89b-12d3-a456-426614174000",
    }
    assert config["tools"] == {
        "*": False,
        "bash": True,
        "edit": True,
        "read": True,
        "write": True,
        "skill": False,
    }
    assert config["permission"]["external_directory"] == "deny"
    assert config["permission"]["task"] == "deny"
    assert config["permission"]["webfetch"] == "deny"
    assert config["permission"]["websearch"] == "deny"
    assert config["permission"]["skill"] == "deny"
    build = config["agent"]["build"]
    assert build["temperature"] == 0.6
    assert build["top_p"] == 0.95
    assert build["options"] == {"top_k": 20}
    assert config.get("skills") is None
    assert config["agent"]["title"]["disable"] is True
    assert config["agent"]["summary"]["disable"] is True
    assert config["agent"]["compaction"]["disable"] is True


def test_opencode_superpowers_config_exposes_only_pinned_profile():
    """The treatment may load the three reviewed skills and no sibling skill."""
    config = opencode.build_opencode_config(
        _task_data(), _connection(), skills_enabled=True
    )

    names = [
        skill["name"]
        for skill in load_adapter("opencode_superpowers")
        .manifest_metadata()["capability_profile"]["skills"]
    ]
    assert config["skills"] == {"paths": [str(BENCH_SKILLS_ROOT.resolve())]}
    assert config["tools"]["skill"] is True
    assert config["permission"]["skill"] == {
        "*": "deny",
        **{name: "allow" for name in names},
    }


def test_opencode_jsonl_summary_captures_usage_and_tool_trace(tmp_path):
    """Raw CLI events must produce durable cross-harness usage/tool evidence."""
    trace = tmp_path / "session.log"
    events = [
        {
            "type": "step_start",
            "timestamp": 1000,
            "sessionID": "ses_test",
            "part": {"type": "step-start"},
        },
        {
            "type": "tool_use",
            "timestamp": 1300,
            "sessionID": "ses_test",
            "part": {
                "type": "tool",
                "tool": "read",
                "callID": "call_1",
                "state": {
                    "status": "completed",
                    "input": {"filePath": "/mnt/task.py"},
                    "output": "contents",
                    "time": {"start": 1100, "end": 1250},
                },
            },
        },
        {
            "type": "step_finish",
            "timestamp": 1400,
            "sessionID": "ses_test",
            "part": {
                "type": "step-finish",
                "tokens": {
                    "total": 16,
                    "input": 10,
                    "output": 3,
                    "reasoning": 0,
                    "cache": {"read": 2, "write": 1},
                },
            },
        },
        {
            "type": "step_finish",
            "timestamp": 1800,
            "sessionID": "ses_test",
            "part": {
                "type": "step-finish",
                "tokens": {
                    "total": 28,
                    "input": 20,
                    "output": 2,
                    "reasoning": 1,
                    "cache": {"read": 5, "write": 0},
                },
            },
        },
    ]
    trace.write_text("".join(json.dumps(event) + "\n" for event in events))

    usage, behavior = opencode.summarize_opencode_events(trace)

    assert vars(usage) == {
        "prompt_tokens": 30,
        "completion_tokens": 5,
        "total_tokens": 44,
        "cache_read_tokens": 7,
        "cache_write_tokens": 1,
        "reasoning_tokens": 1,
    }
    assert behavior["status"] == "observed"
    assert behavior["session_id"] == "ses_test"
    assert behavior["provider_requests"] == 2
    assert behavior["tool_calls"] == 1
    assert behavior["tool_errors"] == 0
    assert behavior["tool_counts"] == {"read": 1}
    assert behavior["tool_seconds"] == 0.15
    assert behavior["trace_file"] == str(trace)


def test_opencode_jsonl_summary_classifies_shell_searches(tmp_path):
    trace = tmp_path / "session.log"
    trace.write_text(
        json.dumps(
            {
                "type": "tool_use",
                "sessionID": "ses_test",
                "part": {
                    "tool": "bash",
                    "callID": "call_search",
                    "state": {
                        "status": "completed",
                        "input": {"command": "rg TODO ."},
                        "time": {"start": 1000, "end": 1010},
                    },
                },
            }
        )
        + "\n"
        + json.dumps(
            {
                "type": "step_finish",
                "sessionID": "ses_test",
                "part": {"tokens": {"input": 1, "output": 1, "total": 2}},
            }
        )
        + "\n"
    )

    _, behavior = opencode.summarize_opencode_events(trace)

    assert behavior["category_counts"] == {"search": 1}
    assert behavior["search_calls"] == 1


def test_opencode_adapter_runs_with_isolated_profile_and_state(tmp_path):
    """The adapter must invoke real JSON mode through the model-only sandbox."""
    workdir = tmp_path / "work"
    out_dir = tmp_path / "out"
    workdir.mkdir()
    out_dir.mkdir()
    log_file = out_dir / "session.log"
    stderr_file = out_dir / "stderr.log"
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured.update(kwargs)
        captured["config_path"] = Path(kwargs["env"]["OPENCODE_CONFIG"])
        captured["config"] = json.loads(captured["config_path"].read_text())
        kwargs["stdout"].write(
            json.dumps(
                {
                    "type": "step_finish",
                    "timestamp": 1000,
                    "sessionID": "ses_test",
                    "part": {
                        "type": "step-finish",
                        "tokens": {"total": 7, "input": 5, "output": 2},
                    },
                }
            )
            + "\n"
        )
        kwargs["stdout"].flush()
        return SimpleNamespace(returncode=0)

    task_data = _task_data() | {
        "prompt": "Fix the bug.",
        "problem": "ornith-smoke",
        "model_base_url": _connection()["base_url"],
        "reasoning": True,
        "model_name": "Ornith",
    }
    with patch.object(
        opencode, "load_opencode_connection", return_value=_connection()
    ), patch.object(opencode, "validate_opencode_runtime"), patch.object(
        opencode, "run_command", side_effect=fake_run
    ):
        result = load_adapter("opencode_vanilla").run(
            task_data, workdir, log_file, stderr_file
        )

    assert result.returncode == 0
    assert vars(result.usage) == {
        "prompt_tokens": 5,
        "completion_tokens": 2,
        "total_tokens": 7,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
        "reasoning_tokens": 0,
    }
    assert result.behavior["provider_requests"] == 1
    assert captured["cmd"][:8] == [
        "opencode",
        "run",
        "--pure",
        "--format",
        "json",
        "--agent",
        "build",
        "--model",
    ]
    assert captured["cmd"][8] == "cospa/ornith-35b-fp8-block"
    assert captured["cmd"][9:11] == [
        "--dir",
        str(opencode.agent_sandbox_cwd(workdir, "ornith-smoke")),
    ]
    assert captured["input"].startswith("NOTE: Network access")
    assert captured["sandbox_workdir"] == workdir
    assert captured["sandbox_name"] == "ornith-smoke"
    assert captured["sandbox_model_url"] == "http://proxy.internal:8989/gateway/v1"
    assert len(captured["sandbox_readonly_paths"]) == 1
    assert len(captured["sandbox_writable_paths"]) == 1

    assert not captured["config_path"].exists()
    config = captured["config"]
    assert config["provider"]["cospa"]["options"]["baseURL"] == task_data["model_base_url"]
    assert config["tools"]["skill"] is False
    assert captured["env"]["OPENCODE_EXPERIMENTAL_OUTPUT_TOKEN_MAX"] == "81920"
    assert captured["env"]["OPENCODE_DISABLE_PROJECT_CONFIG"] == "1"
    assert captured["env"]["OPENCODE_DISABLE_EXTERNAL_SKILLS"] == "1"


@pytest.mark.parametrize(
    ("adapter_name", "skills_enabled"),
    [
        ("opencode_vanilla", False),
        ("opencode_superpowers", True),
    ],
)
def test_installed_opencode_sends_pinned_profile_through_real_sandbox(
    tmp_path, adapter_name, skills_enabled
):
    """Exercise the real CLI, skill loader, JSONL, and model-only relay."""
    workdir = tmp_path / "work"
    out_dir = tmp_path / "out"
    workdir.mkdir()
    out_dir.mkdir()
    (workdir / "task.py").write_text("value = 1\n")
    log_file = out_dir / "session.log"
    stderr_file = out_dir / "stderr.log"

    with _fake_openai_server() as (port, requests):
        base_url = f"http://127.0.0.1:{port}/v1"
        connection = _connection() | {"base_url": base_url}
        task_data = _task_data() | {
            "prompt": "Reply OK without using tools.",
            "problem": f"real-{adapter_name}",
            "model_base_url": base_url,
            "reasoning": True,
            "model_name": "Ornith",
        }
        with patch.object(
            opencode, "load_opencode_connection", return_value=connection
        ):
            result = load_adapter(adapter_name).run(
                task_data, workdir, log_file, stderr_file
            )

    assert result.returncode == 0, (result.error, stderr_file.read_text())
    retained_files = [path for path in out_dir.rglob("*") if path.is_file()]
    assert retained_files
    assert all(b"test-secret" not in path.read_bytes() for path in retained_files)
    assert vars(result.usage) == {
        "prompt_tokens": 11,
        "completion_tokens": 2,
        "total_tokens": 13,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
        "reasoning_tokens": 0,
    }
    assert len(requests) == 1
    request = requests[0]
    assert request["path"] == "/v1/chat/completions"
    assert request["authorization"] == "Bearer test-secret"
    session_id = request["headers"]["x-session-id"]
    UUID(session_id)
    assert request["headers"]["x-session-affinity"] == session_id
    payload = request["payload"]
    assert payload["model"] == "ornith-35b-fp8-block"
    assert payload["temperature"] == 0.6
    assert payload["top_p"] == 0.95
    assert payload["top_k"] == 20
    assert payload["max_tokens"] == 81920
    tools = {tool["function"]["name"]: tool["function"] for tool in payload["tools"]}
    expected = {"bash", "edit", "read", "write"}
    if skills_enabled:
        expected.add("skill")
    assert set(tools) == expected
    if skills_enabled:
        system_prompt = "\n".join(
            str(message.get("content", ""))
            for message in payload["messages"]
            if message.get("role") == "system"
        )
        for name in (
            "systematic-debugging",
            "test-driven-development",
            "verification-before-completion",
        ):
            assert f"<name>{name}</name>" in system_prompt
        assert "customize-opencode" not in system_prompt


def test_opencode_config_rejects_unqualified_reasoning_treatment():
    """Pi thinking labels must not be guessed into OpenCode provider variants."""
    task_data = _task_data() | {"thinking": "high"}

    with pytest.raises(ValueError, match="reasoning variant"):
        opencode.build_opencode_config(
            task_data, _connection(), skills_enabled=False
        )
