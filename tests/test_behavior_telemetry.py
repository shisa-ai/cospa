"""Behavioral telemetry rollups from timestamped pi boundary events."""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from harness.adapters.pi_vanilla import PiVanillaAdapter
from harness.backfill_usage import backfill_manifest
from harness.behavior import (
    classify_tool_call,
    summarize_behavior_events,
    summarize_pi_session_behavior,
)
from harness.runner import run_trial
from harness.suites.aider_polyglot import AiderPolyglotSuite


def _write_events(path: Path, events: list[dict]) -> Path:
    path.write_text("".join(json.dumps(event) + "\n" for event in events))
    return path


def _event(event: str, seconds: float, **data) -> dict:
    return {
        "schema_version": 1,
        "event": event,
        "monotonic_ns": str(int(seconds * 1_000_000_000)),
        "wall_time_ms": int(seconds * 1000),
        **data,
    }


def test_behavior_rollup_tracks_counts_types_and_parallel_safe_time(tmp_path):
    trace = _write_events(
        tmp_path / "behavior.jsonl",
        [
            _event("agent_start", 0),
            _event("turn_start", 0.5, turn_index=0),
            _event("provider_request_start", 1),
            _event("provider_response_headers", 2, status=200),
            _event("assistant_message_end", 5, output_tokens=100),
            _event(
                "tool_execution_start",
                5,
                tool_call_id="search-1",
                tool_name="bash",
                arguments={"command": 'grep -r "CircularBuffer" / | head'},
            ),
            _event(
                "tool_execution_start",
                5.25,
                tool_call_id="read-1",
                tool_name="read",
                arguments={"path": "circular_buffer.h"},
            ),
            _event(
                "tool_execution_end",
                6.25,
                tool_call_id="read-1",
                tool_name="read",
                is_error=True,
                result_chars=20,
            ),
            _event(
                "tool_execution_end",
                9,
                tool_call_id="search-1",
                tool_name="bash",
                is_error=False,
                result_chars=200,
            ),
            _event("turn_end", 9, turn_index=0),
            _event("turn_start", 9, turn_index=1),
            _event("provider_request_start", 9),
            _event("provider_response_headers", 10, status=200),
            _event("assistant_message_end", 12, output_tokens=50),
            _event("turn_end", 12, turn_index=1),
            _event("agent_end", 12.2),
        ],
    )

    summary = summarize_behavior_events(trace, trial_wall_seconds=13)

    assert summary["status"] == "observed"
    assert summary["turn_count"] == 2
    assert summary["provider_requests"] == 2
    assert summary["tool_calls"] == 2
    assert summary["tool_errors"] == 1
    assert summary["tool_counts"] == {"bash": 1, "read": 1}
    assert summary["category_counts"] == {"read": 1, "search": 1}
    assert summary["inference_seconds"] == pytest.approx(7.0)
    # Two tool calls overlap. Wall occupancy is 5->9 (4s), while worker time is
    # 4s + 1s = 5s. Viewer percentages must use the parallel-safe wall value.
    assert summary["tool_seconds"] == pytest.approx(4.0)
    assert summary["tool_worker_seconds"] == pytest.approx(5.0)
    assert summary["tool_seconds_by_name"] == pytest.approx({"bash": 4.0, "read": 1.0})
    assert summary["category_seconds"] == pytest.approx({"read": 1.0, "search": 4.0})
    assert summary["search_calls"] == 1
    assert summary["search_seconds"] == pytest.approx(4.0)
    assert summary["agent_seconds"] == pytest.approx(12.2)
    assert summary["other_seconds"] == pytest.approx(1.2)
    assert summary["harness_seconds"] == pytest.approx(0.8)
    assert summary["inference_percent"] == pytest.approx(7 / 12.2 * 100)
    assert summary["tool_percent"] == pytest.approx(4 / 12.2 * 100)
    assert summary["longest_tools"][0]["tool_name"] == "bash"
    assert "grep -r" in summary["longest_tools"][0]["arguments_preview"]


def test_run_trial_persists_behavior_rollup(make_polyglot_problem, tmp_path):
    vendor_dir = tmp_path / "vendor"
    make_polyglot_problem(
        vendor_dir,
        "python",
        "two-fer",
        instructions="Write a two-fer function",
        starter_name="two_fer",
        starter_content="def two_fer(name=None):\n    pass\n",
        test_content=(
            "from two_fer import two_fer\n"
            "def test_two_fer():\n"
            "    assert two_fer() == 'One for you, one for me.'\n"
        ),
    )

    def fake_agent(_cmd, **kwargs):
        trace = Path(kwargs["env"]["COSPA_BEHAVIOR_TRACE_FILE"])
        _write_events(
            trace,
            [
                _event("agent_start", 0),
                _event("provider_request_start", 1),
                _event("assistant_message_end", 3),
                _event("agent_end", 3.5),
            ],
        )
        return MagicMock(returncode=0, stdout="done", stderr="")

    with patch("harness.adapters.pi_vanilla.run_command", side_effect=fake_agent), patch(
        "harness.suites.aider_polyglot.run_command",
        return_value=MagicMock(returncode=0, stdout="1 passed", stderr=""),
    ):
        manifest, _ = run_trial(
            AiderPolyglotSuite(),
            PiVanillaAdapter(),
            "test/model",
            "python/two-fer",
            1,
            tmp_path / "results",
            vendor_dir,
        )

    behavior = manifest["behavior"]
    assert behavior["status"] == "observed"
    assert behavior["provider_requests"] == 1
    assert behavior["inference_seconds"] == pytest.approx(2.0)
    assert behavior["trace_file"].endswith("out/pi-sessions/behavior_events.jsonl")


def test_legacy_pi_session_recovers_counts_types_and_search_examples(tmp_path):
    session = tmp_path / "pi_session.jsonl"
    messages = [
        {"type": "session", "version": 3, "id": "x", "cwd": "/tmp"},
        {
            "type": "message",
            "message": {
                "role": "assistant",
                "content": [
                    {
                        "type": "toolCall",
                        "id": "search",
                        "name": "bash",
                        "arguments": {"command": "find / -type f | head"},
                    },
                    {
                        "type": "toolCall",
                        "id": "read",
                        "name": "read",
                        "arguments": {"path": "solution.py"},
                    },
                ],
            },
        },
        {
            "type": "message",
            "message": {
                "role": "toolResult",
                "toolCallId": "search",
                "toolName": "bash",
                "content": [{"type": "text", "text": ""}],
                "isError": False,
            },
        },
        {
            "type": "message",
            "message": {
                "role": "toolResult",
                "toolCallId": "read",
                "toolName": "read",
                "content": [{"type": "text", "text": "missing"}],
                "isError": True,
            },
        },
    ]
    session.write_text("".join(json.dumps(event) + "\n" for event in messages))

    summary = summarize_pi_session_behavior(session)

    assert summary["status"] == "counts_only"
    assert summary["timing_available"] is False
    assert summary["tool_calls"] == 2
    assert summary["tool_errors"] == 1
    assert summary["tool_counts"] == {"bash": 1, "read": 1}
    assert summary["category_counts"] == {"read": 1, "search": 1}
    assert summary["search_calls"] == 1
    assert "find /" in summary["search_examples"][0]["arguments_preview"]


def test_backfill_adds_counts_to_manifest_with_existing_usage(tmp_path):
    trial = tmp_path / "trial-1"
    out = trial / "out"
    out.mkdir(parents=True)
    manifest_path = trial / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "model": {"id": "test/model"},
                "sampling": {},
                "token_usage": {"status": "observed", "response_count": 1},
                "timing": {"wall_clock_seconds": 10},
            }
        )
    )
    (out / "pi_session.jsonl").write_text(
        json.dumps(
            {
                "type": "message",
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "toolCall",
                            "id": "x",
                            "name": "grep",
                            "arguments": {"pattern": "TODO"},
                        }
                    ],
                },
            }
        )
        + "\n"
    )

    result = backfill_manifest(manifest_path)
    updated = json.loads(manifest_path.read_text())

    assert result["updated"] is True
    assert updated["behavior"]["status"] == "counts_only"
    assert updated["behavior"]["tool_counts"] == {"grep": 1}


def test_behavior_rollup_marks_incomplete_calls_and_partial_trace(tmp_path):
    trace = _write_events(
        tmp_path / "partial.jsonl",
        [
            _event("agent_start", 0),
            _event("provider_request_start", 1),
            _event("assistant_message_end", 3),
            _event(
                "tool_execution_start",
                3,
                tool_call_id="hang",
                tool_name="bash",
                arguments={"command": "find / -type f"},
            ),
            # Process was killed while the command was active: no tool/agent end.
            _event("session_shutdown", 33, reason="quit"),
        ],
    )

    summary = summarize_behavior_events(trace, trial_wall_seconds=35)

    assert summary["status"] == "partial"
    assert summary["tool_calls"] == 1
    assert summary["incomplete_tool_calls"] == 1
    assert summary["search_calls"] == 1
    assert summary["tool_seconds"] == pytest.approx(30.0)
    assert summary["long_tool_calls"] == 1
    assert summary["longest_tools"][0]["complete"] is False


@pytest.mark.parametrize(
    ("tool_name", "arguments", "expected"),
    [
        ("read", {"path": "x.py"}, "read"),
        ("edit", {"path": "x.py"}, "edit"),
        ("write", {"path": "x.py"}, "write"),
        ("grep", {"pattern": "TODO"}, "search"),
        ("find", {"pattern": "*.py"}, "search"),
        ("tff-search_web", {"query": "tests"}, "external_lookup"),
        ("web_fetch", {"url": "https://example.com"}, "external_lookup"),
        ("bash", {"command": "curl https://example.com"}, "external_lookup"),
        ("bash", {"command": "pytest -q"}, "test"),
        ("bash", {"command": "go test ./..."}, "test"),
        ("bash", {"command": "cmake --build build"}, "build"),
        ("bash", {"command": 'grep -r "thing" /'}, "search"),
        ("bash", {"command": "pwd"}, "shell"),
        ("custom_tool", {}, "other"),
    ],
)
def test_tool_call_classification(tool_name, arguments, expected):
    assert classify_tool_call(tool_name, arguments) == expected
