"""Telemetry helpers for model metadata and pi JSONL usage traces."""

from __future__ import annotations

import json
import os
import shutil
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]

THINKING_TOKEN_BUDGETS = {
    "off": 0,
    "minimal": 256,
    "low": 1024,
    "medium": 4096,
    "high": 8192,
    "xhigh": 12000,
}

MODEL_COST_KEYS = {
    "input",
    "output",
    "cacheRead",
    "cacheWrite",
    "longContextInputThreshold",
    "longContextInput",
    "longContextCacheRead",
    "longContextCacheWrite",
    "longContextOutput",
    "long_context_input_threshold",
    "long_context_input",
    "long_context_cache_read",
    "long_context_cache_write",
    "long_context_output",
}

OPENAI_REASONING_EFFORT_PROVIDERS = {"codex", "openai"}


def thinking_token_budget(thinking: str | None) -> int | None:
    """Return the local thinking-token budget for a named effort level."""
    if not thinking or thinking == "default":
        return None
    return THINKING_TOKEN_BUDGETS.get(str(thinking))


def uses_openai_reasoning_effort(
    model_id: str | None,
    model_metadata: dict[str, Any] | None = None,
) -> bool:
    """Return whether `thinking` maps to OpenAI symbolic reasoning effort."""
    if isinstance(model_metadata, dict):
        source = model_metadata.get("reasoning_effort_source")
        if source == "openai":
            return True
        if source:
            return False

    if not model_id:
        return False
    provider = _provider_for_model(model_id)
    return provider in OPENAI_REASONING_EFFORT_PROVIDERS


def thinking_sampling_metadata(
    thinking: str | None,
    *,
    model_id: str | None = None,
    model_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return manifest sampling fields for a thinking/effort setting."""
    level = str(thinking) if thinking else "default"
    metadata: dict[str, Any] = {"thinking": level}
    if level == "default":
        return metadata

    if uses_openai_reasoning_effort(model_id, model_metadata):
        metadata["reasoning_effort"] = level
        metadata["reasoning_effort_source"] = "openai"
        return metadata

    budget = thinking_token_budget(level)
    if budget is not None:
        metadata["thinking_token_budget"] = budget
        metadata["thinking_token_budget_source"] = "coding-eval"
    return metadata


def _normalize_model_id(value: str) -> str:
    return "".join(ch.lower() for ch in value if ch.isalnum())


def _model_targets(model_id: str) -> set[str]:
    tail = model_id.split("/", 1)[1] if "/" in model_id else model_id
    return {model_id, tail, _normalize_model_id(model_id), _normalize_model_id(tail)}


def _provider_for_model(model_id: str) -> str | None:
    return model_id.split("/", 1)[0] if "/" in model_id else None


def _read_json(path: Path) -> dict | None:
    try:
        with open(path) as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def _parse_simple_yaml_scalar(value: str) -> Any:
    value = value.strip()
    if value in {"true", "True"}:
        return True
    if value in {"false", "False"}:
        return False
    if value in {"null", "Null", "NULL", "~"}:
        return None
    if (
        (value.startswith('"') and value.endswith('"'))
        or (value.startswith("'") and value.endswith("'"))
    ):
        return value[1:-1]
    try:
        if "." in value:
            return float(value)
        return int(value)
    except ValueError:
        return value


def _parse_models_yaml_fallback(text: str) -> list[dict]:
    """Parse the simple configs/models.yaml shape without a YAML dependency."""
    models: list[dict] = []
    current: dict | None = None
    nested_key: str | None = None
    nested_profile: str | None = None

    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        stripped = line.strip()
        indent = len(line) - len(line.lstrip())

        if stripped.startswith("- id:"):
            current = {"id": _parse_simple_yaml_scalar(stripped.split(":", 1)[1])}
            models.append(current)
            nested_key = None
            nested_profile = None
            continue
        if stripped.startswith("- "):
            current = {"id": _parse_simple_yaml_scalar(stripped[2:])}
            models.append(current)
            nested_key = None
            nested_profile = None
            continue
        if current is None or ":" not in stripped:
            continue

        key, raw_value = stripped.split(":", 1)
        key = key.strip()
        raw_value = raw_value.strip()
        if indent >= 8 and nested_key == "cost_profiles" and nested_profile:
            profiles = current.setdefault(nested_key, {})
            if isinstance(profiles, dict):
                profile = profiles.setdefault(nested_profile, {})
                if isinstance(profile, dict):
                    profile[key] = _parse_simple_yaml_scalar(raw_value)
            continue
        if indent >= 6 and nested_key == "cost_profiles":
            profiles = current.setdefault(nested_key, {})
            if isinstance(profiles, dict):
                if raw_value:
                    profiles[key] = _parse_simple_yaml_scalar(raw_value)
                    nested_profile = None
                else:
                    profiles[key] = {}
                    nested_profile = key
            continue
        if indent >= 6 and nested_key:
            nested = current.setdefault(nested_key, {})
            if isinstance(nested, dict):
                nested[key] = _parse_simple_yaml_scalar(raw_value)
            continue
        if raw_value:
            current[key] = _parse_simple_yaml_scalar(raw_value)
            nested_key = None
            nested_profile = None
        else:
            current[key] = {}
            nested_key = key
            nested_profile = None

    return models


def _read_models_config(path: Path) -> list[dict]:
    try:
        text = path.read_text()
    except OSError:
        return []

    try:
        import yaml  # type: ignore

        data = yaml.safe_load(text) or {}
        raw_models = data.get("models", []) if isinstance(data, dict) else data
        if isinstance(raw_models, list):
            models = []
            for item in raw_models:
                if isinstance(item, dict):
                    models.append(item)
                elif isinstance(item, str):
                    models.append({"id": item})
            return models
    except ImportError:
        pass
    except Exception:
        return []

    return _parse_models_yaml_fallback(text)


def _candidate_model_values(model: dict) -> list[str]:
    values: list[str] = []
    for key in ("id", "name", "model", "modelId"):
        value = model.get(key)
        if isinstance(value, str):
            values.append(value)
    aliases = model.get("aliases") or model.get("alias")
    if isinstance(aliases, str):
        values.append(aliases)
    elif isinstance(aliases, list):
        values.extend(value for value in aliases if isinstance(value, str))
    return values


def _match_model_entry(
    models: list[Any],
    model_id: str,
    *,
    strict: bool = False,
) -> dict | None:
    targets = _model_targets(model_id)
    for item in models:
        if not isinstance(item, dict):
            continue
        for value in _candidate_model_values(item):
            if strict and value == model_id:
                return item
            if strict:
                continue
            if value in targets or _normalize_model_id(value) in targets:
                return item
    return None


@lru_cache(maxsize=32)
def pi_thinking_level_map(model_id: str) -> dict:
    """Return the model's provider ``thinkingLevelMap`` from pi models.json.

    The map translates a requested Pi thinking level to the value sent
    upstream. A ``None``/null value means the provider manages that level
    itself (no explicit effort is sent), so the server's reported default is
    the legitimate observation. Returns an empty dict when no map exists.
    """
    override = os.environ.get("CODING_EVAL_PI_MODELS_JSON")
    models_json_path = Path(override) if override else Path.home() / ".pi" / "agent" / "models.json"
    data = _read_json(Path(models_json_path))
    if not data:
        return {}
    providers = data.get("providers") or {}
    if model_id.startswith("local/"):
        provider_names = ["local"]
    elif "/" in model_id:
        provider_names = [model_id.split("/", 1)[0]]
    else:
        provider_names = list(providers)
    bare_id = model_id.split("/", 1)[-1] if "/" in model_id else model_id
    for provider_name in provider_names:
        provider = providers.get(provider_name) or {}
        for lookup_id in (model_id, bare_id):
            entry = _match_model_entry(
                provider.get("models") or [], lookup_id
            )
            if entry is not None:
                level_map = entry.get("thinkingLevelMap")
                if isinstance(level_map, dict):
                    return level_map
    return {}


def load_model_metadata(
    model_id: str,
    *,
    models_json_path: Path | str | None = None,
    models_config_path: Path | str | None = None,
    pricing_profile: str | None = None,
    strict_config_id: bool = False,
) -> dict:
    """Load safe model metadata from pi's models.json.

    Only benchmark-relevant fields are returned. Provider secrets, base URLs,
    and auth metadata are deliberately omitted from the manifest.
    """
    if models_json_path is None:
        override = os.environ.get("CODING_EVAL_PI_MODELS_JSON")
        models_json_path = Path(override) if override else Path.home() / ".pi" / "agent" / "models.json"
    models_json_path = Path(models_json_path)

    metadata: dict[str, Any] = {}

    data = _read_json(models_json_path)
    if data:
        provider = _provider_for_model(model_id)
        providers = data.get("providers") if isinstance(data.get("providers"), dict) else data
        provider_cfg = providers.get(provider) if provider and isinstance(providers, dict) else None
        if isinstance(provider_cfg, dict):
            raw_models = provider_cfg.get("models", [])
            if isinstance(raw_models, list):
                model = _match_model_entry(raw_models, model_id)
                if model is not None:
                    metadata.update(_safe_model_metadata(model))

    if models_config_path is None:
        models_config_path = PROJECT_ROOT / "configs" / "models.yaml"
    models_config_path = Path(models_config_path)
    config_model = _match_model_entry(
        _read_models_config(models_config_path),
        model_id,
        strict=strict_config_id,
    )
    if config_model is not None:
        config_metadata = _safe_model_metadata(
            config_model,
            pricing_profile=pricing_profile,
        )
        if (
            config_model.get("id") == model_id
            and "model" not in config_model
            and "modelId" not in config_model
        ):
            config_metadata.pop("provider_config_model_id", None)
        metadata.update(config_metadata)

    return metadata


def _safe_model_metadata(
    model: dict,
    *,
    pricing_profile: str | None = None,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    field_map = {
        "provider_config_model_id": ("id", "model", "modelId"),
        "name": ("name",),
        "context_window": ("contextWindow", "context_window"),
        "max_tokens": ("maxTokens", "max_tokens"),
        "reasoning": ("reasoning",),
        "reasoning_effort_source": ("reasoning_effort_source",),
    }
    for output_key, input_keys in field_map.items():
        for input_key in input_keys:
            if input_key in model:
                metadata[output_key] = model[input_key]
                break

    input_modalities = model.get("input") or model.get("input_modalities")
    if isinstance(input_modalities, list):
        metadata["input_modalities"] = input_modalities

    sampling = model.get("sampling") or model.get("sampling_params")
    if isinstance(sampling, dict):
        safe_sampling = {
            key: value
            for key, value in sampling.items()
            if key in {
                "temperature",
                "top_p",
                "top_k",
                "min_p",
                "presence_penalty",
                "repetition_penalty",
            }
            and isinstance(value, (int, float))
            and not isinstance(value, bool)
        }
        if safe_sampling:
            metadata["sampling_params"] = safe_sampling
    for key in ("sampling_source", "sampling_rationale"):
        value = model.get(key)
        if isinstance(value, str) and value:
            metadata[key] = value

    raw_overrides = model.get("protocol_overrides")
    if isinstance(raw_overrides, dict):
        safe_overrides: dict[str, Any] = {}
        bcb = raw_overrides.get("bigcodebench_hard_instruct")
        if isinstance(bcb, dict):
            raw_request = bcb.get("request_overrides")
            if isinstance(raw_request, dict):
                reasoning_effort = raw_request.get("reasoning_effort")
                if reasoning_effort in {
                    "none",
                    "minimal",
                    "low",
                    "medium",
                    "high",
                    "xhigh",
                }:
                    safe_overrides["bigcodebench_hard_instruct"] = {
                        "request_overrides": {
                            "reasoning_effort": reasoning_effort
                        }
                    }
        if safe_overrides:
            metadata["protocol_overrides"] = safe_overrides

    selected_profile = None
    cost = None
    if pricing_profile:
        profiles = model.get("cost_profiles") or model.get("pricing_profiles")
        if isinstance(profiles, dict):
            profile_cost = profiles.get(pricing_profile)
            if isinstance(profile_cost, dict):
                cost = profile_cost
                selected_profile = pricing_profile
    if cost is None:
        cost = model.get("cost") or model.get("pricing")
    if isinstance(cost, dict):
        metadata["cost"] = {
            key: value
            for key, value in cost.items()
            if key in MODEL_COST_KEYS
            and isinstance(value, (int, float))
            and not isinstance(value, bool)
        }
        metadata["pricing_unit"] = "usd_per_1m_tokens"
        if selected_profile:
            metadata["pricing_profile"] = selected_profile

    return metadata


def _sessions_root(sessions_root: Path | str | None = None) -> Path:
    if sessions_root is not None:
        return Path(sessions_root)
    override = os.environ.get("CODING_EVAL_PI_SESSIONS_DIR")
    if override:
        return Path(override)
    return Path.home() / ".pi" / "agent" / "sessions"


def pi_session_dir_for_cwd(
    cwd: Path | str,
    *,
    sessions_root: Path | str | None = None,
) -> Path:
    """Return pi's session directory for a working directory."""
    cwd_text = str(Path(cwd))
    encoded_cwd = cwd_text.strip("/").replace("/", "-")
    return _sessions_root(sessions_root) / f"--{encoded_cwd}--"


def _parse_timestamp(value: str | None) -> float | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except ValueError:
        return None


def _session_header(path: Path) -> dict | None:
    try:
        with open(path) as f:
            first_line = f.readline()
        event = json.loads(first_line)
        return event if isinstance(event, dict) and event.get("type") == "session" else None
    except (OSError, json.JSONDecodeError):
        return None


def find_pi_session_file(
    cwd: Path | str,
    *,
    sessions_root: Path | str | None = None,
    session_dir: Path | str | None = None,
    start_time: float | None = None,
    end_time: float | None = None,
) -> Path | None:
    """Find the pi JSONL session trace for a trial workdir.

    ``session_dir`` is the explicit directory passed to pi's ``--session-dir``.
    When omitted, preserve compatibility with pi's default encoded-cwd layout.
    """
    cwd_path = Path(cwd)
    resolved_session_dir = (
        Path(session_dir)
        if session_dir is not None
        else pi_session_dir_for_cwd(cwd_path, sessions_root=sessions_root)
    )
    if not resolved_session_dir.exists():
        return None

    matches: list[tuple[float, Path]] = []
    fallback: list[tuple[float, Path]] = []
    for session_file in resolved_session_dir.glob("*.jsonl"):
        header = _session_header(session_file)
        if not header or header.get("cwd") != str(cwd_path):
            continue
        session_ts = _parse_timestamp(header.get("timestamp"))
        mtime = session_file.stat().st_mtime
        sort_ts = session_ts if session_ts is not None else mtime
        fallback.append((sort_ts, session_file))
        if start_time is not None and session_ts is not None and session_ts < start_time - 60:
            continue
        if end_time is not None and session_ts is not None and session_ts > end_time + 60:
            continue
        matches.append((sort_ts, session_file))

    candidates = matches or fallback
    if not candidates:
        return None
    return sorted(candidates)[-1][1]


def _numeric(data: dict, *keys: str) -> float:
    for key in keys:
        value = data.get(key)
        if value is None or isinstance(value, bool):
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return 0.0


def _int_token(data: dict, *keys: str) -> int:
    return int(_numeric(data, *keys))


def _append_unique(values: list[str], value: Any) -> None:
    if isinstance(value, str) and value not in values:
        values.append(value)


def summarize_pi_session(session_file: Path | str) -> dict:
    """Summarize token/cost usage from a pi JSONL session trace."""
    session_file = Path(session_file)
    totals = {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "cached_tokens": 0,
        "cache_creation_tokens": 0,
        "reasoning_tokens": 0,
        "total_tokens": 0,
        "cost_usd": 0.0,
        "cost_usd_pi": 0.0,
    }
    response_ids: list[str] = []
    response_models: list[str] = []
    models: list[str] = []
    providers: list[str] = []
    session_id = None
    thinking = None
    response_count = 0

    with open(session_file) as f:
        for line in f:
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict):
                continue

            event_type = event.get("type")
            if event_type == "session":
                session_id = event.get("id")
            elif event_type == "model_change":
                _append_unique(providers, event.get("provider"))
                _append_unique(models, event.get("modelId"))
            elif event_type == "thinking_level_change":
                if isinstance(event.get("thinkingLevel"), str):
                    thinking = event["thinkingLevel"]

            message = event.get("message")
            if not isinstance(message, dict):
                continue
            usage = message.get("usage")
            if not isinstance(usage, dict):
                continue

            response_count += 1
            _append_unique(providers, message.get("provider"))
            _append_unique(models, message.get("model"))
            _append_unique(response_ids, message.get("responseId"))
            _append_unique(response_models, message.get("responseModel"))

            input_tokens = _int_token(usage, "input", "input_tokens", "prompt_tokens")
            output_tokens = _int_token(usage, "output", "output_tokens", "completion_tokens")
            cache_read = _int_token(usage, "cacheRead", "cache_read_tokens", "cached_tokens")
            cache_write = _int_token(usage, "cacheWrite", "cache_creation_tokens", "cache_write_tokens")
            reasoning = _int_token(usage, "reasoning", "reasoning_tokens")
            total_tokens = _int_token(usage, "totalTokens", "total_tokens")
            if not total_tokens:
                total_tokens = input_tokens + output_tokens + cache_read + cache_write + reasoning

            totals["prompt_tokens"] += input_tokens
            totals["completion_tokens"] += output_tokens
            totals["cached_tokens"] += cache_read
            totals["cache_creation_tokens"] += cache_write
            totals["reasoning_tokens"] += reasoning
            totals["total_tokens"] += total_tokens

            cost = usage.get("cost")
            if isinstance(cost, dict):
                observed_cost = _numeric(cost, "total", "cost_usd", "total_cost_usd")
            else:
                observed_cost = _numeric(usage, "cost_usd", "total_cost_usd", "cost")
            totals["cost_usd"] += observed_cost
            totals["cost_usd_pi"] += observed_cost

    status = "observed" if response_count else "unavailable"
    summary = {
        "source": "pi-session-jsonl",
        "status": status,
        "session_id": session_id,
        "response_count": response_count,
        "prompt_tokens": totals["prompt_tokens"],
        "input_tokens": totals["prompt_tokens"],
        "completion_tokens": totals["completion_tokens"],
        "output_tokens": totals["completion_tokens"],
        "cached_tokens": totals["cached_tokens"],
        "cache_read_tokens": totals["cached_tokens"],
        "cache_creation_tokens": totals["cache_creation_tokens"],
        "cache_write_tokens": totals["cache_creation_tokens"],
        "reasoning_tokens": totals["reasoning_tokens"],
        "total_tokens": totals["total_tokens"],
        "cost_usd": totals["cost_usd"],
        "cost_usd_pi": totals["cost_usd_pi"],
        "response_ids": response_ids,
        "response_models": response_models,
        "models": models,
        "providers": providers,
        "original_session_path": str(session_file),
    }
    if thinking:
        summary["thinking"] = thinking
    return summary


def _relative_trace_file(target: Path, out_dir: Path) -> str:
    try:
        return str(target.relative_to(out_dir.parent))
    except ValueError:
        return str(target)


def _summarize_and_copy_pi_sessions(
    session_files: list[Path],
    out_dir: Path,
) -> dict:
    valid_sessions: list[tuple[Path, dict]] = []
    for session_file in session_files:
        try:
            summary = summarize_pi_session(session_file)
        except OSError:
            continue
        if summary.get("status") == "observed":
            valid_sessions.append((session_file, summary))

    if not valid_sessions:
        return {
            "source": "pi-session-jsonl",
            "status": "unavailable",
            "reason": "no pi session trace with usage found",
        }

    out_dir.mkdir(parents=True, exist_ok=True)
    trace_files: list[str] = []
    for index, (session_file, _) in enumerate(valid_sessions, start=1):
        if len(valid_sessions) == 1:
            target = out_dir / "pi_session.jsonl"
        else:
            target = out_dir / "pi_sessions" / f"pi_session_{index}.jsonl"
        target.parent.mkdir(parents=True, exist_ok=True)
        if session_file.resolve() != target.resolve():
            shutil.copy2(session_file, target)
        trace_files.append(_relative_trace_file(target, out_dir))

    totals = {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "cached_tokens": 0,
        "cache_creation_tokens": 0,
        "reasoning_tokens": 0,
        "total_tokens": 0,
        "cost_usd": 0.0,
        "cost_usd_pi": 0.0,
        "response_count": 0,
    }
    response_ids: list[str] = []
    response_models: list[str] = []
    models: list[str] = []
    providers: list[str] = []
    session_ids: list[str] = []
    thinking_levels: list[str] = []
    original_paths: list[str] = []

    for session_file, summary in valid_sessions:
        original_paths.append(str(session_file))
        _append_unique(session_ids, summary.get("session_id"))
        _append_unique(thinking_levels, summary.get("thinking"))
        for key in totals:
            totals[key] += summary.get(key, 0) or 0
        for value in summary.get("response_ids", []):
            _append_unique(response_ids, value)
        for value in summary.get("response_models", []):
            _append_unique(response_models, value)
        for value in summary.get("models", []):
            _append_unique(models, value)
        for value in summary.get("providers", []):
            _append_unique(providers, value)

    combined = {
        "source": "pi-session-jsonl",
        "status": "observed",
        "response_count": totals["response_count"],
        "prompt_tokens": totals["prompt_tokens"],
        "input_tokens": totals["prompt_tokens"],
        "completion_tokens": totals["completion_tokens"],
        "output_tokens": totals["completion_tokens"],
        "cached_tokens": totals["cached_tokens"],
        "cache_read_tokens": totals["cached_tokens"],
        "cache_creation_tokens": totals["cache_creation_tokens"],
        "cache_write_tokens": totals["cache_creation_tokens"],
        "reasoning_tokens": totals["reasoning_tokens"],
        "total_tokens": totals["total_tokens"],
        "cost_usd": totals["cost_usd"],
        "cost_usd_pi": totals["cost_usd_pi"],
        "response_ids": response_ids,
        "response_models": response_models,
        "models": models,
        "providers": providers,
        "session_ids": session_ids,
        "original_session_paths": original_paths,
        "trace_files": trace_files,
    }
    if len(session_ids) == 1:
        combined["session_id"] = session_ids[0]
    if len(thinking_levels) == 1:
        combined["thinking"] = thinking_levels[0]
    elif thinking_levels:
        combined["thinking_levels"] = thinking_levels
    return combined


def collect_pi_session_usage(
    workdir: Path | str,
    out_dir: Path | str,
    *,
    sessions_root: Path | str | None = None,
    session_dir: Path | str | None = None,
    start_time: float | None = None,
    end_time: float | None = None,
) -> dict:
    """Copy the raw pi trace into out/ and return aggregate token usage."""
    workdir = Path(workdir)
    out_dir = Path(out_dir)
    session_file = find_pi_session_file(
        workdir,
        sessions_root=sessions_root,
        session_dir=session_dir,
        start_time=start_time,
        end_time=end_time,
    )
    if session_file is None:
        return {
            "source": "pi-session-jsonl",
            "status": "unavailable",
            "reason": "no matching pi session trace found",
        }

    return _summarize_and_copy_pi_sessions([session_file], out_dir)


def find_harbor_pi_session_files(jobs_dir: Path | str) -> list[Path]:
    """Find pi JSONL traces exported by Harbor agents into job artifacts."""
    jobs_dir = Path(jobs_dir)
    if not jobs_dir.exists():
        return []

    matches: list[tuple[float, Path]] = []
    for session_file in jobs_dir.rglob("*.jsonl"):
        if "pi-sessions" not in session_file.parts:
            continue
        if _session_header(session_file):
            matches.append((session_file.stat().st_mtime, session_file))
    return [path for _, path in sorted(matches)]


def collect_harbor_pi_session_usage(
    jobs_dir: Path | str,
    out_dir: Path | str,
) -> dict:
    """Copy and summarize pi traces exported from Harbor job artifacts."""
    session_files = find_harbor_pi_session_files(jobs_dir)
    if not session_files:
        return {
            "source": "pi-session-jsonl",
            "status": "unavailable",
            "reason": "no Harbor pi session artifact found",
        }
    return _summarize_and_copy_pi_sessions(session_files, Path(out_dir))
