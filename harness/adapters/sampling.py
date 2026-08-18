"""Validate that pi's per-model request sampling matches benchmark profiles."""

import json
import os
import re
from pathlib import Path
from typing import Any


def _normalise_model_id(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def _find_pi_model(model_id: str, models_json_path: Path) -> dict[str, Any] | None:
    """Find the pi model entry matching a provider-qualified benchmark ID."""
    provider, _, requested_id = model_id.partition("/")
    if not provider or not requested_id:
        return None
    try:
        data = json.loads(models_json_path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    providers = data.get("providers", {})
    provider_config = providers.get(provider) if isinstance(providers, dict) else None
    models = provider_config.get("models", []) if isinstance(provider_config, dict) else []
    wanted = _normalise_model_id(requested_id)
    for model in models:
        if not isinstance(model, dict):
            continue
        if _normalise_model_id(str(model.get("id", ""))) == wanted:
            return model
        # Optional aliases let multiple benchmark ids resolve to one wire name
        # (e.g. quant-variant labels pointing at a single registered model).
        for alias in model.get("aliases", []) or []:
            if _normalise_model_id(str(alias)) == wanted:
                return model
    return None


def validate_pi_sampling_params(
    model_id: str,
    expected: dict[str, int | float],
    *,
    models_json_path: Path | str | None = None,
) -> None:
    """Raise if pi would send sampling values different from ``expected``.

    pi merges a model entry's ``samplingParams`` into every OpenAI completion
    request. Failing closed here prevents a benchmark manifest from claiming a
    recommended profile while pi silently uses server defaults.
    """
    if not expected:
        return
    if models_json_path is None:
        override = os.environ.get("CODING_EVAL_PI_MODELS_JSON")
        models_json_path = Path(override) if override else Path.home() / ".pi" / "agent" / "models.json"
    model = _find_pi_model(model_id, Path(models_json_path))
    if model is None:
        raise RuntimeError(f"pi model config not found for {model_id}")
    actual = model.get("samplingParams")
    if not isinstance(actual, dict):
        raise RuntimeError(f"pi model {model_id} has no samplingParams")
    mismatches = {
        key: {"expected": value, "actual": actual.get(key)}
        for key, value in expected.items()
        if actual.get(key) != value
    }
    if mismatches:
        raise RuntimeError(f"pi samplingParams mismatch for {model_id}: {mismatches}")
