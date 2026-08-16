"""Controlled OpenCode baseline and Superpowers benchmark adapters."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Optional
from urllib.parse import urlparse
from uuid import UUID, uuid4

from harness.adapters.session_utils import with_no_network_hint
from harness.behavior import classify_tool_call
from harness.skill_profiles import (
    BENCH_SKILLS_ROOT,
    load_superpowers_profile,
)
from harness.subprocess_utils import agent_sandbox_cwd, run_command
from harness.telemetry import load_model_metadata


OPENCODE_VERSION = "1.18.8"
_TOOL_SURFACE = ("bash", "edit", "read", "write")
_ALLOWED_SAMPLING_PARAMS = frozenset({"temperature", "top_p", "top_k"})


def load_opencode_connection(
    model_id: str,
    *,
    models_json_path: Path | str | None = None,
) -> dict[str, str]:
    """Resolve one Pi provider entry without changing its proxy topology."""
    provider_name, separator, requested_model = model_id.partition("/")
    if not separator or not provider_name or not requested_model:
        raise ValueError(f"Model id must include a provider: {model_id!r}")
    if models_json_path is None:
        override = os.environ.get("CODING_EVAL_PI_MODELS_JSON")
        models_json_path = (
            Path(override)
            if override
            else Path.home() / ".pi" / "agent" / "models.json"
        )
    config_path = Path(models_json_path)
    try:
        data = json.loads(config_path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Cannot load Pi model config {config_path}: {error}") from error
    providers = data.get("providers", data) if isinstance(data, dict) else {}
    provider = providers.get(provider_name) if isinstance(providers, dict) else None
    if not isinstance(provider, dict):
        raise ValueError(f"Unknown provider {provider_name!r} in {config_path}")

    base_url = provider.get("baseUrl") or provider.get("base_url")
    endpoint = urlparse(str(base_url or ""))
    if endpoint.scheme not in {"http", "https"} or not endpoint.hostname:
        raise ValueError(f"Provider {provider_name!r} has no safe HTTP base URL")

    api_key = provider.get("apiKey") or provider.get("api_key") or ""
    api_key_env = (
        provider.get("apiKeyEnv")
        or provider.get("api_key_env")
        or provider.get("apiKeyEnvVar")
        or provider.get("api_key_env_var")
    )
    if api_key_env and os.environ.get(str(api_key_env)) is not None:
        api_key = os.environ[str(api_key_env)]

    served_model = requested_model
    models = provider.get("models", [])
    if isinstance(models, list):
        for model in models:
            candidate = model.get("id") if isinstance(model, dict) else model
            if candidate in {model_id, requested_model}:
                served_model = str(candidate)
                break

    return {
        "base_url": str(base_url),
        "api_key": str(api_key),
        "api": str(
            provider.get("api")
            or provider.get("api_type")
            or "openai-completions"
        ),
        "model": served_model,
    }


def build_opencode_config(
    task_data: dict,
    connection: dict,
    *,
    skills_enabled: bool,
) -> dict:
    """Build the fail-closed OpenCode profile for one benchmark trial."""
    if connection.get("api") != "openai-completions":
        raise ValueError(
            "OpenCode profile supports only qualified OpenAI-compatible "
            "chat-completions routes"
        )
    thinking = task_data.get("thinking")
    if thinking not in (None, "", "not_applicable"):
        raise ValueError(
            "OpenCode reasoning variant is unqualified; refusing to translate "
            f"Pi thinking level {thinking!r}"
        )

    sampling = task_data.get("sampling_params") or {}
    if not isinstance(sampling, dict):
        raise ValueError("OpenCode sampling_params must be a mapping")
    unsupported = sorted(set(sampling) - _ALLOWED_SAMPLING_PARAMS)
    if unsupported:
        raise ValueError(f"OpenCode sampling parameters are unqualified: {unsupported}")

    context_window = int(task_data.get("context_window") or 0)
    max_tokens = int(task_data.get("max_tokens") or 0)
    if context_window <= 0 or max_tokens <= 0:
        raise ValueError("OpenCode requires positive context_window and max_tokens")

    served_model = str(connection.get("model") or "")
    base_url = str(connection.get("base_url") or "")
    if not served_model or not base_url:
        raise ValueError("OpenCode provider connection lacks model or base URL")
    client_session_id = str(task_data.get("client_session_id") or "")
    try:
        parsed_session_id = UUID(client_session_id)
    except ValueError as error:
        raise ValueError("OpenCode client_session_id must be a UUID") from error
    if str(parsed_session_id) != client_session_id.lower():
        raise ValueError("OpenCode client_session_id must use canonical UUID form")

    skill_names: list[str] = []
    if skills_enabled:
        profile = load_superpowers_profile()
        skill_names = [str(skill["name"]) for skill in profile["skills"]]

    tools = {
        "*": False,
        "bash": True,
        "edit": True,
        "read": True,
        "write": True,
        "skill": skills_enabled,
    }
    permission: dict = {
        "*": "deny",
        "bash": "allow",
        "edit": "allow",
        "read": "allow",
        "doom_loop": "allow",
        "external_directory": "deny",
        "task": "deny",
        "todowrite": "deny",
        "question": "deny",
        "webfetch": "deny",
        "websearch": "deny",
        "lsp": "deny",
        "skill": (
            {"*": "deny", **{name: "allow" for name in skill_names}}
            if skills_enabled
            else "deny"
        ),
    }
    model_ref = f"cospa/{served_model}"
    build_agent: dict = {"model": model_ref}
    if "temperature" in sampling:
        build_agent["temperature"] = sampling["temperature"]
    if "top_p" in sampling:
        build_agent["top_p"] = sampling["top_p"]
    if "top_k" in sampling:
        build_agent["options"] = {"top_k": sampling["top_k"]}

    session_headers = {
        # Match OpenCode's exact key casing so object spread replaces rather
        # than duplicates the default before Fetch normalizes header names.
        "X-Session-Id": client_session_id,
        "x-session-affinity": client_session_id,
    }
    model_config: dict = {
        "name": str(task_data.get("model_name") or served_model),
        "reasoning": bool(task_data.get("reasoning")),
        "tool_call": True,
        "temperature": "temperature" in sampling,
        "limit": {"context": context_window, "output": max_tokens},
        # Model-level headers override OpenCode's per-session ``ses_...``
        # headers in 1.18.8's request preparation order.
        "headers": session_headers,
    }
    if model_config["reasoning"]:
        model_config["interleaved"] = {"field": "reasoning_content"}

    config = {
        "enabled_providers": ["cospa"],
        "model": model_ref,
        "small_model": model_ref,
        "default_agent": "build",
        "share": "disabled",
        "autoupdate": False,
        "snapshot": False,
        "lsp": False,
        "formatter": False,
        "mcp": {},
        "plugin": [],
        "instructions": [],
        "subagent_depth": 0,
        "compaction": {"auto": False, "prune": False},
        "tools": tools,
        "permission": permission,
        "agent": {
            "build": build_agent,
            "title": {"disable": True},
            "summary": {"disable": True},
            "compaction": {"disable": True},
            "plan": {"disable": True},
            "general": {"disable": True},
            "explore": {"disable": True},
        },
        "provider": {
            "cospa": {
                "npm": "@ai-sdk/openai-compatible",
                "name": "Cospa benchmark route",
                "options": {
                    "baseURL": base_url,
                    "apiKey": str(connection.get("api_key") or ""),
                    # OpenCode otherwise injects its internal ``ses_...`` ID.
                    # codex-pool correctly rejects that non-UUID session key.
                    "headers": session_headers,
                    "timeout": int(float(task_data.get("timeout", 600)) * 1000),
                },
                "models": {served_model: model_config},
            }
        },
    }
    if skills_enabled:
        config["skills"] = {"paths": [str(BENCH_SKILLS_ROOT.resolve())]}
    return config


def validate_opencode_runtime() -> None:
    """Fail closed if the installed CLI differs from the qualified runtime."""
    executable = shutil.which("opencode")
    if executable is None:
        raise RuntimeError("Pinned OpenCode runtime is not installed")
    result = subprocess.run(
        [executable, "--version"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    observed = result.stdout.strip()
    if result.returncode != 0 or observed != OPENCODE_VERSION:
        raise RuntimeError(
            f"OpenCode runtime mismatch: expected {OPENCODE_VERSION}, "
            f"observed {observed or f'exit {result.returncode}'}"
        )


def _union_seconds(intervals: list[tuple[float, float]]) -> float:
    if not intervals:
        return 0.0
    total = 0.0
    start, end = sorted(intervals)[0]
    for next_start, next_end in sorted(intervals)[1:]:
        if next_start <= end:
            end = max(end, next_end)
        else:
            total += end - start
            start, end = next_start, next_end
    return total + end - start


def summarize_opencode_events(trace_file: Path | str) -> tuple[object, dict[str, Any]]:
    """Summarize OpenCode's documented ``run --format json`` event stream."""
    trace_file = Path(trace_file)
    events: list[dict[str, Any]] = []
    for line_number, line in enumerate(trace_file.read_text().splitlines(), 1):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError(
                f"Invalid OpenCode JSON event at line {line_number}: {error}"
            ) from error
        if not isinstance(event, dict):
            raise ValueError(f"Invalid OpenCode event at line {line_number}")
        events.append(event)

    finishes = [event for event in events if event.get("type") == "step_finish"]
    if not finishes:
        raise ValueError("OpenCode JSON trace has no completed provider request")
    token_totals = {
        "input": 0,
        "output": 0,
        "total": 0,
        "cache_read": 0,
        "cache_write": 0,
        "reasoning": 0,
    }
    for event in finishes:
        part = event.get("part")
        tokens = part.get("tokens") if isinstance(part, dict) else None
        if not isinstance(tokens, dict):
            raise ValueError("OpenCode step_finish event has no token usage")
        for key in ("input", "output", "total"):
            value = tokens.get(key)
            if not isinstance(value, (int, float)):
                raise ValueError(f"OpenCode token usage lacks numeric {key}")
            token_totals[key] += int(value)
        cache = tokens.get("cache") or {}
        if not isinstance(cache, dict):
            raise ValueError("OpenCode token cache usage must be a mapping")
        for source_key, total_key in (("read", "cache_read"), ("write", "cache_write")):
            value = cache.get(source_key, 0)
            if not isinstance(value, (int, float)):
                raise ValueError(f"OpenCode cache usage lacks numeric {source_key}")
            token_totals[total_key] += int(value)
        reasoning = tokens.get("reasoning", 0)
        if not isinstance(reasoning, (int, float)):
            raise ValueError("OpenCode token usage lacks numeric reasoning")
        token_totals["reasoning"] += int(reasoning)

    usage = SimpleNamespace(
        prompt_tokens=token_totals["input"],
        completion_tokens=token_totals["output"],
        total_tokens=token_totals["total"],
        cache_read_tokens=token_totals["cache_read"],
        cache_write_tokens=token_totals["cache_write"],
        reasoning_tokens=token_totals["reasoning"],
    )
    session_ids = {
        str(event["sessionID"])
        for event in events
        if isinstance(event.get("sessionID"), str) and event["sessionID"]
    }
    if len(session_ids) != 1:
        raise ValueError(f"OpenCode trace has ambiguous session IDs: {session_ids}")

    tool_counts: dict[str, int] = defaultdict(int)
    category_counts: dict[str, int] = defaultdict(int)
    tool_intervals: list[tuple[float, float]] = []
    tool_seconds_by_name: dict[str, float] = defaultdict(float)
    tool_errors = 0
    incomplete = 0
    long_tools = 0
    details: list[dict[str, Any]] = []
    for event in events:
        if event.get("type") != "tool_use":
            continue
        part = event.get("part")
        if not isinstance(part, dict):
            raise ValueError("OpenCode tool event has no part")
        state = part.get("state")
        if not isinstance(state, dict):
            raise ValueError("OpenCode tool event has no state")
        name = str(part.get("tool") or "unknown")
        arguments = state.get("input") if isinstance(state.get("input"), dict) else {}
        category = classify_tool_call(name, arguments)
        status = str(state.get("status") or "")
        is_error = status == "error"
        complete = status in {"completed", "error"}
        if is_error:
            tool_errors += 1
        if not complete:
            incomplete += 1
        duration = 0.0
        timing = state.get("time")
        if isinstance(timing, dict):
            start = timing.get("start")
            end = timing.get("end")
            if isinstance(start, (int, float)) and isinstance(end, (int, float)):
                interval = (float(start) / 1000, float(end) / 1000)
                if interval[1] >= interval[0]:
                    tool_intervals.append(interval)
                    duration = interval[1] - interval[0]
                    tool_seconds_by_name[name] += duration
        if duration >= 30:
            long_tools += 1
        tool_counts[name] += 1
        category_counts[category] += 1
        details.append(
            {
                "tool_call_id": str(part.get("callID") or ""),
                "tool_name": name,
                "category": category,
                "seconds": round(duration, 6),
                "complete": complete,
                "is_error": is_error,
            }
        )

    details.sort(key=lambda item: item["seconds"], reverse=True)
    behavior = {
        "schema_version": 1,
        "runtime": "opencode",
        "status": "partial" if incomplete else "observed",
        "timing_available": False,
        "trace_file": str(trace_file),
        "session_id": next(iter(session_ids)),
        "turn_count": len(finishes),
        "provider_requests": len(finishes),
        "tool_calls": sum(tool_counts.values()),
        "tool_errors": tool_errors,
        "incomplete_tool_calls": incomplete,
        "long_tool_calls": long_tools,
        "tool_seconds": round(_union_seconds(tool_intervals), 6),
        "tool_worker_seconds": round(sum(end - start for start, end in tool_intervals), 6),
        "tool_counts": dict(sorted(tool_counts.items())),
        "category_counts": dict(sorted(category_counts.items())),
        "tool_seconds_by_name": {
            name: round(seconds, 6)
            for name, seconds in sorted(tool_seconds_by_name.items())
        },
        "search_calls": sum(
            count
            for category, count in category_counts.items()
            if category in {"search", "external_lookup"}
        ),
        "external_lookup_calls": category_counts.get("external_lookup", 0),
        "longest_tools": details[:5],
    }
    return usage, behavior


def _run_configured_opencode(
    *,
    config: dict,
    effective_task: dict,
    connection: dict[str, str],
    skills_enabled: bool,
    workdir: Path,
    log_file: Path,
    stderr_file: Path,
) -> subprocess.CompletedProcess:
    """Execute one trial while keeping credential-bearing config ephemeral."""
    out_dir = Path(log_file).resolve().parent
    state_root = out_dir / "opencode-state"
    for name in ("home", "config", "data", "cache", "state"):
        (state_root / name).mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="cospa-opencode-profile-") as temp_dir:
        profile_dir = Path(temp_dir)
        config_path = profile_dir / "opencode.json"
        config_path.write_text(json.dumps(config, indent=2, sort_keys=True) + "\n")

        env = os.environ.copy()
        env.update(
            {
                "HOME": str(state_root / "home"),
                "XDG_CONFIG_HOME": str(state_root / "config"),
                "XDG_DATA_HOME": str(state_root / "data"),
                "XDG_CACHE_HOME": str(state_root / "cache"),
                "XDG_STATE_HOME": str(state_root / "state"),
                "OPENCODE_CONFIG": str(config_path),
                "OPENCODE_PURE": "1",
                "OPENCODE_CLIENT": "cospa",
                "OPENCODE_DISABLE_AUTOUPDATE": "1",
                "OPENCODE_DISABLE_DEFAULT_PLUGINS": "1",
                "OPENCODE_DISABLE_LSP_DOWNLOAD": "1",
                "OPENCODE_DISABLE_MODELS_FETCH": "1",
                "OPENCODE_DISABLE_PROJECT_CONFIG": "1",
                "OPENCODE_DISABLE_CLAUDE_CODE": "1",
                "OPENCODE_DISABLE_EXTERNAL_SKILLS": "1",
                "OPENCODE_DISABLE_AUTOCOMPACT": "1",
                "OPENCODE_DISABLE_PRUNE": "1",
                "OPENCODE_EXPERIMENTAL_OUTPUT_TOKEN_MAX": str(
                    effective_task["max_tokens"]
                ),
            }
        )
        virtual_workdir = agent_sandbox_cwd(
            workdir, effective_task.get("problem")
        )
        cmd = [
            "opencode",
            "run",
            "--pure",
            "--format",
            "json",
            "--agent",
            "build",
            "--model",
            f"cospa/{connection['model']}",
            "--dir",
            str(virtual_workdir),
        ]
        readonly_paths = [profile_dir]
        if skills_enabled:
            readonly_paths.append(BENCH_SKILLS_ROOT.resolve())

        with open(log_file, "w") as log_f, open(stderr_file, "w") as stderr_f:
            return run_command(
                cmd,
                input=with_no_network_hint(effective_task.get("prompt", "")),
                cwd=str(workdir),
                stdout=log_f,
                stderr=stderr_f,
                text=True,
                env=env,
                timeout=effective_task.get("timeout", 600),
                sandbox_workdir=workdir,
                sandbox_name=effective_task.get("problem"),
                sandbox_model_url=connection["base_url"],
                sandbox_readonly_paths=readonly_paths,
                sandbox_writable_paths=[state_root],
            )


@dataclass
class AdapterResult:
    returncode: int
    usage: Optional[object] = None
    error: Optional[str] = None
    behavior: Optional[dict[str, Any]] = None
    budget_exhausted: bool = False


class _OpenCodeAdapter:
    """Shared metadata for the pinned OpenCode ablation arms."""

    version = f"opencode-{OPENCODE_VERSION}-four-tool-v1"
    tool_call_parser = f"opencode-{OPENCODE_VERSION}-ai-sdk-openai-compatible"
    uses_workspace_sandbox = True
    uses_pi_session = False
    supports_harbor_execution = False
    skills_enabled = False

    @classmethod
    def manifest_metadata(cls) -> dict:
        metadata = {
            "runtime": {"name": "opencode", "version": OPENCODE_VERSION},
            "tool_surface": list(_TOOL_SURFACE),
            "skill_loading": "disabled",
            "comparability_limits": [
                "OpenCode and Pi retain their native system prompts and tool descriptions.",
                "OpenCode auxiliary agents and subagents are disabled for this profile.",
            ],
        }
        if cls.skills_enabled:
            metadata["skill_loading"] = "native-on-demand"
            metadata["capability_profile"] = load_superpowers_profile()
        return metadata

    def run(
        self,
        task_data: dict,
        workdir: Path,
        log_file: Path,
        stderr_file: Path,
    ) -> AdapterResult:
        """Run the pinned OpenCode profile through Cospa's model-only sandbox."""
        try:
            validate_opencode_runtime()
            connection = load_opencode_connection(str(task_data.get("model_id") or ""))
            declared_url = task_data.get("model_base_url")
            if declared_url and str(declared_url) != connection["base_url"]:
                raise ValueError(
                    "OpenCode provider route differs from the runner-selected BaseURL: "
                    f"{connection['base_url']!r} != {declared_url!r}"
                )

            effective_task = dict(task_data)
            effective_task.setdefault("client_session_id", str(uuid4()))
            metadata = load_model_metadata(str(task_data.get("model_id") or ""))
            for key in ("context_window", "max_tokens", "reasoning", "name"):
                task_key = "model_name" if key == "name" else key
                if effective_task.get(task_key) is None and metadata.get(key) is not None:
                    effective_task[task_key] = metadata[key]
            config = build_opencode_config(
                effective_task,
                connection,
                skills_enabled=self.skills_enabled,
            )

            result = _run_configured_opencode(
                config=config,
                effective_task=effective_task,
                connection=connection,
                skills_enabled=self.skills_enabled,
                workdir=workdir,
                log_file=log_file,
                stderr_file=stderr_file,
            )
            if result.returncode != 0:
                return AdapterResult(returncode=result.returncode)
            usage, behavior = summarize_opencode_events(log_file)
            return AdapterResult(
                returncode=0,
                usage=usage,
                behavior=behavior,
            )
        except subprocess.TimeoutExpired:
            return AdapterResult(
                returncode=-1,
                error="OpenCode agent capability budget exhausted",
                budget_exhausted=True,
            )
        except Exception as error:
            return AdapterResult(returncode=-1, error=str(error))


class OpenCodeVanillaAdapter(_OpenCodeAdapter):
    """OpenCode Build constrained to the same four tool classes as vanilla Pi."""

    name = "opencode_vanilla"


class OpenCodeSuperpowersAdapter(_OpenCodeAdapter):
    """The controlled OpenCode baseline plus the pinned Superpowers profile."""

    name = "opencode_superpowers"
    skills_enabled = True
