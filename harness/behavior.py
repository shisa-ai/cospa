"""Post-hoc behavioral telemetry for pi-backed benchmark trials.

The compact event trace contains only lifecycle boundaries. Full tool arguments
and results remain available in pi's durable session JSONL; this module creates
a cheap manifest rollup for score-view refreshes and model comparisons.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable


_EXTERNAL_TOOLS = {
    "web_fetch",
    "batch_web_fetch",
    "tff-fetch_url",
    "tff-search_web",
}
_SEARCH_TOOLS = {"grep", "find"}
_DIRECT_CATEGORIES = {
    "read": "read",
    "ls": "read",
    "edit": "edit",
    "write": "write",
}
_EXTERNAL_COMMAND = re.compile(
    r"(?:^|[;&|]\s*|\s)(?:curl|wget)\b|\bgit\s+(?:clone|fetch|pull)\b",
    re.IGNORECASE,
)
_TEST_COMMAND = re.compile(
    r"\b(?:pytest|unittest|go\s+test|cargo\s+test|ctest|npm\s+test|pnpm\s+test|"
    r"yarn\s+test|gradle\w*\s+test|mvn\s+test)\b",
    re.IGNORECASE,
)
_BUILD_COMMAND = re.compile(
    r"\b(?:cmake\s+--build|make(?:\s|$)|ninja(?:\s|$)|cargo\s+build|"
    r"go\s+build|g\+\+|clang\+\+|javac|gradle\w*\s+build|mvn\s+package)\b",
    re.IGNORECASE,
)
_SEARCH_COMMAND = re.compile(
    r"(?:^|[;&|]\s*|\s)(?:grep|rg|find|fd|locate)\b",
    re.IGNORECASE,
)
_SEARCH_CATEGORIES = {"search", "external_lookup"}


def classify_tool_call(tool_name: str, arguments: dict[str, Any] | None) -> str:
    """Return a stable high-level behavior category for one tool call."""
    name = str(tool_name or "").lower()
    if name in _DIRECT_CATEGORIES:
        return _DIRECT_CATEGORIES[name]
    if name in _SEARCH_TOOLS:
        return "search"
    if name in _EXTERNAL_TOOLS:
        return "external_lookup"
    if name != "bash":
        return "other"

    command = ""
    if isinstance(arguments, dict):
        value = arguments.get("command")
        if isinstance(value, str):
            command = value
    if _EXTERNAL_COMMAND.search(command):
        return "external_lookup"
    if _TEST_COMMAND.search(command):
        return "test"
    if _BUILD_COMMAND.search(command):
        return "build"
    if _SEARCH_COMMAND.search(command):
        return "search"
    return "shell"


def _event_seconds(event: dict[str, Any]) -> float | None:
    value = event.get("monotonic_ns")
    try:
        return int(value) / 1_000_000_000
    except (TypeError, ValueError):
        return None


def _union_seconds(intervals: Iterable[tuple[float, float]]) -> float:
    ordered = sorted((start, end) for start, end in intervals if end >= start)
    if not ordered:
        return 0.0
    total = 0.0
    current_start, current_end = ordered[0]
    for start, end in ordered[1:]:
        if start <= current_end:
            current_end = max(current_end, end)
            continue
        total += current_end - current_start
        current_start, current_end = start, end
    return total + current_end - current_start


def _arguments_preview(arguments: Any, limit: int = 240) -> str:
    if isinstance(arguments, dict):
        preferred = arguments.get("command") or arguments.get("path")
        if isinstance(preferred, str):
            text = preferred
        else:
            text = json.dumps(arguments, sort_keys=True, ensure_ascii=False)
    else:
        text = str(arguments or "")
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _round_map(values: dict[str, float]) -> dict[str, float]:
    return {key: round(value, 6) for key, value in sorted(values.items())}


def summarize_pi_session_behavior(session_file: Path | str) -> dict[str, Any]:
    """Recover tool counts/types from legacy pi session JSONL without timing."""
    session_file = Path(session_file)
    try:
        lines = session_file.read_text().splitlines()
    except OSError:
        return {"schema_version": 1, "status": "unavailable"}

    calls: dict[str, dict[str, Any]] = {}
    call_order: list[str] = []
    turn_count = 0
    valid_events = 0
    for line in lines:
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        valid_events += 1
        if event.get("type") != "message":
            continue
        message = event.get("message")
        if not isinstance(message, dict):
            continue
        role = message.get("role")
        if role == "assistant":
            turn_count += 1
            content = message.get("content")
            if not isinstance(content, list):
                continue
            for block in content:
                if not isinstance(block, dict) or block.get("type") != "toolCall":
                    continue
                call_id = str(block.get("id") or "")
                if not call_id:
                    continue
                calls[call_id] = {
                    "tool_call_id": call_id,
                    "tool_name": str(block.get("name") or "unknown"),
                    "arguments": block.get("arguments") or {},
                    "complete": False,
                    "is_error": False,
                }
                call_order.append(call_id)
        elif role == "toolResult":
            call_id = str(message.get("toolCallId") or "")
            if call_id in calls:
                calls[call_id]["complete"] = True
                calls[call_id]["is_error"] = bool(message.get("isError"))

    if not valid_events:
        return {"schema_version": 1, "status": "unavailable"}

    tool_counts: dict[str, int] = defaultdict(int)
    category_counts: dict[str, int] = defaultdict(int)
    tool_errors = 0
    incomplete = 0
    examples: list[dict[str, Any]] = []
    for call_id in call_order:
        record = calls[call_id]
        name = record["tool_name"]
        category = classify_tool_call(name, record.get("arguments"))
        tool_counts[name] += 1
        category_counts[category] += 1
        if record["is_error"]:
            tool_errors += 1
        if not record["complete"]:
            incomplete += 1
        if category in _SEARCH_CATEGORIES and len(examples) < 5:
            examples.append(
                {
                    "tool_call_id": call_id,
                    "tool_name": name,
                    "category": category,
                    "complete": record["complete"],
                    "is_error": record["is_error"],
                    "arguments_preview": _arguments_preview(record.get("arguments")),
                }
            )

    return {
        "schema_version": 1,
        "status": "counts_only",
        "timing_available": False,
        "trace_file": str(session_file),
        "turn_count": turn_count,
        "tool_calls": len(call_order),
        "tool_errors": tool_errors,
        "incomplete_tool_calls": incomplete,
        "search_calls": sum(
            count
            for category, count in category_counts.items()
            if category in _SEARCH_CATEGORIES
        ),
        "external_lookup_calls": category_counts.get("external_lookup", 0),
        "long_tool_calls": 0,
        "tool_counts": dict(sorted(tool_counts.items())),
        "category_counts": dict(sorted(category_counts.items())),
        "search_examples": examples,
        "longest_tools": [],
    }


def summarize_behavior_events(
    event_file: Path | str,
    *,
    trial_wall_seconds: float | None = None,
    long_tool_seconds: float = 30.0,
) -> dict[str, Any]:
    """Summarize one compact pi behavior-boundary event trace.

    ``tool_seconds`` is the union of tool intervals, so parallel calls do not
    inflate viewer percentages. ``tool_worker_seconds`` is the raw sum and is
    useful for identifying parallelism. Interrupted calls are closed at the
    final observed event and make the summary ``partial``.
    """
    event_file = Path(event_file)
    try:
        lines = event_file.read_text().splitlines()
    except OSError:
        return {"schema_version": 1, "status": "unavailable"}

    events: list[tuple[float, dict[str, Any]]] = []
    for line in lines:
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        timestamp = _event_seconds(event)
        if timestamp is not None:
            events.append((timestamp, event))
    if not events:
        return {"schema_version": 1, "status": "unavailable"}

    events.sort(key=lambda item: item[0])
    first_ts = events[0][0]
    last_ts = events[-1][0]
    open_agent: float | None = None
    agent_intervals: list[tuple[float, float]] = []
    agent_ended = False
    active_request: dict[str, float] | None = None
    inference_intervals: list[tuple[float, float]] = []
    provider_header_intervals: list[tuple[float, float]] = []
    provider_requests = 0
    turn_count = 0
    open_tools: dict[str, dict[str, Any]] = {}
    tool_records: list[dict[str, Any]] = []

    for timestamp, event in events:
        event_name = event.get("event")
        if event_name == "agent_start":
            if open_agent is None:
                open_agent = timestamp
        elif event_name == "agent_end":
            if open_agent is not None:
                agent_intervals.append((open_agent, timestamp))
                open_agent = None
            agent_ended = True
        elif event_name == "turn_start":
            turn_count += 1
        elif event_name == "provider_request_start":
            # Provider requests are sequential inside one pi agent loop. If an
            # earlier request never closed, preserve it as partial to this point.
            if active_request is not None:
                inference_intervals.append((active_request["start"], timestamp))
            active_request = {"start": timestamp}
            provider_requests += 1
        elif event_name == "provider_response_headers":
            if active_request is not None and "headers" not in active_request:
                active_request["headers"] = timestamp
                provider_header_intervals.append(
                    (active_request["start"], timestamp)
                )
        elif event_name == "assistant_message_end":
            if active_request is not None:
                inference_intervals.append((active_request["start"], timestamp))
                active_request = None
        elif event_name == "tool_execution_start":
            call_id = str(event.get("tool_call_id") or "")
            if call_id:
                open_tools[call_id] = {
                    "start": timestamp,
                    "tool_call_id": call_id,
                    "tool_name": str(event.get("tool_name") or "unknown"),
                    "arguments": event.get("arguments") or {},
                }
        elif event_name == "tool_execution_end":
            call_id = str(event.get("tool_call_id") or "")
            started = open_tools.pop(call_id, None)
            if started is not None:
                started.update(
                    {
                        "end": timestamp,
                        "complete": True,
                        "is_error": bool(event.get("is_error")),
                        "result_chars": int(event.get("result_chars") or 0),
                    }
                )
                tool_records.append(started)

    partial = False
    if active_request is not None:
        inference_intervals.append((active_request["start"], last_ts))
        partial = True
    if open_agent is not None:
        agent_intervals.append((open_agent, last_ts))
        partial = True
    if not agent_ended:
        partial = True
    for started in open_tools.values():
        started.update(
            {
                "end": last_ts,
                "complete": False,
                "is_error": False,
                "result_chars": 0,
            }
        )
        tool_records.append(started)
        partial = True

    # Older/partially-written traces may miss agent_start. Bound the observed
    # timeline rather than losing otherwise-valid tool/request telemetry.
    if not agent_intervals:
        agent_intervals = [(first_ts, last_ts)]
        partial = True

    tool_intervals: list[tuple[float, float]] = []
    tool_counts: dict[str, int] = defaultdict(int)
    category_counts: dict[str, int] = defaultdict(int)
    tool_seconds_by_name: dict[str, float] = defaultdict(float)
    category_seconds: dict[str, float] = defaultdict(float)
    detailed_tools: list[dict[str, Any]] = []
    search_intervals: list[tuple[float, float]] = []
    external_intervals: list[tuple[float, float]] = []
    tool_errors = 0
    incomplete_tools = 0
    long_tools = 0

    for record in tool_records:
        start = float(record["start"])
        end = float(record["end"])
        duration = max(end - start, 0.0)
        name = str(record["tool_name"])
        category = classify_tool_call(name, record.get("arguments"))
        interval = (start, end)
        tool_intervals.append(interval)
        tool_counts[name] += 1
        category_counts[category] += 1
        tool_seconds_by_name[name] += duration
        category_seconds[category] += duration
        if category in _SEARCH_CATEGORIES:
            search_intervals.append(interval)
        if category == "external_lookup":
            external_intervals.append(interval)
        if record.get("is_error"):
            tool_errors += 1
        if not record.get("complete"):
            incomplete_tools += 1
        if duration >= long_tool_seconds:
            long_tools += 1
        detailed_tools.append(
            {
                "tool_call_id": record["tool_call_id"],
                "tool_name": name,
                "category": category,
                "seconds": round(duration, 6),
                "complete": bool(record.get("complete")),
                "is_error": bool(record.get("is_error")),
                "result_chars": int(record.get("result_chars") or 0),
                "arguments_preview": _arguments_preview(record.get("arguments")),
            }
        )

    detailed_tools.sort(key=lambda item: item["seconds"], reverse=True)
    inference_seconds = _union_seconds(inference_intervals)
    tool_seconds = _union_seconds(tool_intervals)
    tool_worker_seconds = sum(end - start for start, end in tool_intervals)
    agent_seconds = _union_seconds(agent_intervals)
    occupied_seconds = _union_seconds([*inference_intervals, *tool_intervals])
    other_seconds = max(agent_seconds - occupied_seconds, 0.0)
    harness_seconds = (
        max(float(trial_wall_seconds) - agent_seconds, 0.0)
        if trial_wall_seconds is not None
        else None
    )

    def percent(value: float) -> float | None:
        return value / agent_seconds * 100 if agent_seconds > 0 else None

    summary: dict[str, Any] = {
        "schema_version": 1,
        "status": "partial" if partial else "observed",
        "trace_file": str(event_file),
        "turn_count": turn_count,
        "provider_requests": provider_requests,
        "agent_seconds": round(agent_seconds, 6),
        "inference_seconds": round(inference_seconds, 6),
        "provider_headers_seconds": round(
            _union_seconds(provider_header_intervals), 6
        ),
        "tool_seconds": round(tool_seconds, 6),
        "tool_worker_seconds": round(tool_worker_seconds, 6),
        "other_seconds": round(other_seconds, 6),
        "inference_percent": percent(inference_seconds),
        "tool_percent": percent(tool_seconds),
        "other_percent": percent(other_seconds),
        "tool_calls": len(tool_records),
        "tool_errors": tool_errors,
        "incomplete_tool_calls": incomplete_tools,
        "long_tool_calls": long_tools,
        "search_calls": sum(
            count
            for category, count in category_counts.items()
            if category in _SEARCH_CATEGORIES
        ),
        "search_seconds": round(_union_seconds(search_intervals), 6),
        "external_lookup_calls": category_counts.get("external_lookup", 0),
        "external_lookup_seconds": round(_union_seconds(external_intervals), 6),
        "tool_counts": dict(sorted(tool_counts.items())),
        "category_counts": dict(sorted(category_counts.items())),
        "tool_seconds_by_name": _round_map(tool_seconds_by_name),
        "category_seconds": _round_map(category_seconds),
        "longest_tools": detailed_tools[:5],
        "search_examples": [
            item for item in detailed_tools if item["category"] in _SEARCH_CATEGORIES
        ][:5],
    }
    if harness_seconds is not None:
        summary["harness_seconds"] = round(harness_seconds, 6)
    return summary
