"""Telemetry helpers for model metadata and pi JSONL usage traces."""

from __future__ import annotations

import json
import os
import shutil
from datetime import datetime, timezone
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


def thinking_token_budget(thinking: str | None) -> int | None:
    """Return the local thinking-token budget for a named effort level."""
    if not thinking or thinking == "default":
        return None
    return THINKING_TOKEN_BUDGETS.get(str(thinking))


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
            continue
        if stripped.startswith("- "):
            current = {"id": _parse_simple_yaml_scalar(stripped[2:])}
            models.append(current)
            nested_key = None
            continue
        if current is None or ":" not in stripped:
            continue

        key, raw_value = stripped.split(":", 1)
        key = key.strip()
        raw_value = raw_value.strip()
        if indent >= 6 and nested_key:
            nested = current.setdefault(nested_key, {})
            if isinstance(nested, dict):
                nested[key] = _parse_simple_yaml_scalar(raw_value)
            continue
        if raw_value:
            current[key] = _parse_simple_yaml_scalar(raw_value)
            nested_key = None
        else:
            current[key] = {}
            nested_key = key

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


def _match_model_entry(models: list[Any], model_id: str) -> dict | None:
    targets = _model_targets(model_id)
    for item in models:
        if not isinstance(item, dict):
            continue
        for value in _candidate_model_values(item):
            if value in targets or _normalize_model_id(value) in targets:
                return item
    return None


def load_model_metadata(
    model_id: str,
    *,
    models_json_path: Path | str | None = None,
    models_config_path: Path | str | None = None,
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
    config_model = _match_model_entry(_read_models_config(models_config_path), model_id)
    if config_model is not None:
        config_metadata = _safe_model_metadata(config_model)
        if (
            config_model.get("id") == model_id
            and "model" not in config_model
            and "modelId" not in config_model
        ):
            config_metadata.pop("provider_config_model_id", None)
        metadata.update(config_metadata)

    return metadata


def _safe_model_metadata(model: dict) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    field_map = {
        "provider_config_model_id": ("id", "model", "modelId"),
        "name": ("name",),
        "context_window": ("contextWindow", "context_window"),
        "max_tokens": ("maxTokens", "max_tokens"),
        "reasoning": ("reasoning",),
    }
    for output_key, input_keys in field_map.items():
        for input_key in input_keys:
            if input_key in model:
                metadata[output_key] = model[input_key]
                break

    input_modalities = model.get("input") or model.get("input_modalities")
    if isinstance(input_modalities, list):
        metadata["input_modalities"] = input_modalities

    cost = model.get("cost") or model.get("pricing")
    if isinstance(cost, dict):
        metadata["cost"] = {
            key: value
            for key, value in cost.items()
            if key in {"input", "output", "cacheRead", "cacheWrite"}
            and isinstance(value, (int, float))
            and not isinstance(value, bool)
        }
        metadata["pricing_unit"] = "usd_per_1m_tokens"

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
    start_time: float | None = None,
    end_time: float | None = None,
) -> Path | None:
    """Find the pi JSONL session trace for a trial workdir."""
    cwd_path = Path(cwd)
    session_dir = pi_session_dir_for_cwd(cwd_path, sessions_root=sessions_root)
    if not session_dir.exists():
        return None

    matches: list[tuple[float, Path]] = []
    fallback: list[tuple[float, Path]] = []
    for session_file in session_dir.glob("*.jsonl"):
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
                totals["cost_usd"] += _numeric(cost, "total", "cost_usd", "total_cost_usd")
            else:
                totals["cost_usd"] += _numeric(usage, "cost_usd", "total_cost_usd", "cost")

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
        "response_ids": response_ids,
        "response_models": response_models,
        "models": models,
        "providers": providers,
        "original_session_path": str(session_file),
    }
    if thinking:
        summary["thinking"] = thinking
    return summary


def collect_pi_session_usage(
    workdir: Path | str,
    out_dir: Path | str,
    *,
    sessions_root: Path | str | None = None,
    start_time: float | None = None,
    end_time: float | None = None,
) -> dict:
    """Copy the raw pi trace into out/ and return aggregate token usage."""
    workdir = Path(workdir)
    out_dir = Path(out_dir)
    session_file = find_pi_session_file(
        workdir,
        sessions_root=sessions_root,
        start_time=start_time,
        end_time=end_time,
    )
    if session_file is None:
        return {
            "source": "pi-session-jsonl",
            "status": "unavailable",
            "reason": "no matching pi session trace found",
        }

    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / "pi_session.jsonl"
    if session_file.resolve() != target.resolve():
        shutil.copy2(session_file, target)

    summary = summarize_pi_session(session_file)
    summary["trace_files"] = ["out/pi_session.jsonl"]
    return summary
