"""Non-agentic OpenAI-compatible generator for BigCodeBench Instruct.

This adapter intentionally does not invoke pi's coding-agent loop. BigCodeBench
Instruct is a one-message, one-generation benchmark: no system prompt, tools,
workspace context, or retries based on verifier feedback.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Optional


@dataclass
class AdapterResult:
    returncode: int
    usage: Optional[object] = None
    error: Optional[str] = None
    inference_seconds: Optional[float] = None
    behavior: Optional[dict[str, Any]] = None


class InvalidCompletionError(ValueError):
    """Provider replied successfully but did not produce a scoreable sample."""


def load_provider_connection(model_id: str) -> dict[str, str]:
    """Resolve one pi model entry into an OpenAI-compatible connection."""
    if "/" not in model_id:
        raise ValueError(f"Model id must include a provider: {model_id!r}")
    provider_name, requested_model = model_id.split("/", 1)
    config_path = Path.home() / ".pi" / "agent" / "models.json"
    data = json.loads(config_path.read_text())
    providers = data.get("providers", data)
    provider = providers.get(provider_name) if isinstance(providers, dict) else None
    if not isinstance(provider, dict):
        raise ValueError(f"Unknown provider {provider_name!r} in {config_path}")

    base_url = provider.get("baseUrl") or provider.get("base_url")
    if not isinstance(base_url, str) or not base_url:
        raise ValueError(f"Provider {provider_name!r} has no base URL")

    api_key = provider.get("apiKey") or provider.get("api_key") or ""
    api_key_env = (
        provider.get("apiKeyEnv")
        or provider.get("api_key_env")
        or provider.get("apiKeyEnvVar")
        or provider.get("api_key_env_var")
    )
    if api_key_env:
        api_key = os.environ.get(str(api_key_env), api_key)

    served_model = requested_model

    def _norm(value: str) -> str:
        import re as _re

        return _re.sub(r"[^a-z0-9]", "", value.lower())

    wanted = {_norm(model_id), _norm(requested_model)}
    for model in provider.get("models", []):
        candidate = model.get("id") if isinstance(model, dict) else model
        if candidate in (model_id, requested_model):
            served_model = str(candidate)
            break
        aliases = (
            [str(a) for a in (model.get("aliases") or [])]
            if isinstance(model, dict)
            else []
        )
        if _norm(str(candidate)) in wanted or any(
            _norm(a) in wanted for a in aliases
        ):
            served_model = str(candidate)
            break

    return {
        "base_url": base_url.rstrip("/"),
        "api_key": str(api_key),
        "model": served_model,
    }


def build_chat_request(task_data: dict[str, Any], model: str) -> dict[str, Any]:
    """Build the pinned upstream one-message BigCodeBench request."""
    request = {
        "model": model,
        "messages": [{"role": "user", "content": task_data["prompt"]}],
        "n": 1,
        "temperature": task_data["temperature"],
        "top_p": task_data["top_p"],
        "max_completion_tokens": task_data["max_tokens"],
    }
    request_overrides = task_data.get("request_overrides")
    if isinstance(request_overrides, dict):
        reasoning_effort = request_overrides.get("reasoning_effort")
        if isinstance(reasoning_effort, str) and reasoning_effort:
            request["reasoning_effort"] = reasoning_effort
    return request


def _usage_object(response: dict[str, Any]) -> object | None:
    usage = response.get("usage")
    if not isinstance(usage, dict):
        return None
    return SimpleNamespace(
        prompt_tokens=usage.get("prompt_tokens"),
        completion_tokens=usage.get("completion_tokens"),
        total_tokens=usage.get("total_tokens"),
    )


class BigCodeBenchOpenAIAdapter:
    """Exact no-tool chat-generation arm for BigCodeBench-Hard Instruct."""

    name = "bigcodebench_openai"
    version = "0.1"
    uses_workspace_sandbox = False
    uses_pi_session = False

    def run(
        self,
        task_data: dict[str, Any],
        workdir: Path,
        log_file: Path,
        stderr_file: Path,
    ) -> AdapterResult:
        workdir = Path(workdir)
        workdir.mkdir(parents=True, exist_ok=True)
        log_file = Path(log_file)
        stderr_file = Path(stderr_file)
        connection = load_provider_connection(str(task_data["model_id"]))
        payload = build_chat_request(task_data, connection["model"])
        headers = {"Content-Type": "application/json"}
        if connection["api_key"]:
            headers["Authorization"] = f"Bearer {connection['api_key']}"
        request = urllib.request.Request(
            f"{connection['base_url']}/chat/completions",
            data=json.dumps(payload).encode(),
            headers=headers,
            method="POST",
        )

        started = time.monotonic()
        decoded: dict[str, Any] | None = None
        try:
            with urllib.request.urlopen(
                request, timeout=float(task_data.get("timeout", 600))
            ) as response:
                raw = response.read()
            elapsed = time.monotonic() - started
            # Preserve even an invalid completion for protocol diagnosis. This
            # artifact contains only the public prompt response, never tests.
            (workdir / "raw-response.json").write_bytes(raw)
            decoded = json.loads(raw)
            choices = decoded.get("choices")
            if not isinstance(choices, list) or len(choices) != 1:
                raise InvalidCompletionError(
                    "Provider returned other than one completion"
                )
            message = choices[0].get("message")
            completion = message.get("content") if isinstance(message, dict) else None
            if not isinstance(completion, str) or not completion.strip():
                raise InvalidCompletionError("Provider returned no textual completion")

            (workdir / "raw-response.json").write_text(
                json.dumps(decoded, indent=2) + "\n"
            )
            (workdir / "raw-completion.txt").write_text(completion)
            (workdir / "raw-sample.jsonl").write_text(
                json.dumps(
                    {
                        "task_id": task_data["task_id"],
                        "raw_solution": completion,
                    }
                )
                + "\n"
            )
            log_file.write_text(
                json.dumps(
                    {
                        "protocol": "bigcodebench_instruct_single_generation",
                        "response_id": decoded.get("id"),
                        "served_model": decoded.get("model"),
                        "finish_reason": choices[0].get("finish_reason"),
                        "inference_seconds": elapsed,
                    },
                    indent=2,
                )
                + "\n"
            )
            stderr_file.write_text("")
            return AdapterResult(
                returncode=0,
                usage=_usage_object(decoded),
                inference_seconds=elapsed,
                behavior={
                    "telemetry_status": "observed_nonagentic",
                    "total_tool_calls": 0,
                    "tool_errors": 0,
                    "tool_counts": {},
                    "tool_type_counts": {},
                    "search_calls": 0,
                },
            )
        except Exception as exc:
            elapsed = time.monotonic() - started
            detail = str(exc)
            if isinstance(exc, urllib.error.HTTPError):
                try:
                    body = exc.read().decode(errors="replace")
                    detail = f"HTTP {exc.code}: {body[:2000]}"
                except Exception:
                    detail = f"HTTP {exc.code}"
            stderr_file.write_text(detail + "\n")
            return AdapterResult(
                returncode=2 if isinstance(exc, InvalidCompletionError) else -1,
                usage=_usage_object(decoded) if isinstance(decoded, dict) else None,
                error=detail,
                inference_seconds=elapsed,
                behavior={
                    "telemetry_status": "observed_nonagentic",
                    "total_tool_calls": 0,
                    "tool_errors": 0,
                    "tool_counts": {},
                    "tool_type_counts": {},
                    "search_calls": 0,
                },
            )
