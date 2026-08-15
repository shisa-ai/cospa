"""Sampling-profile tests for agentic model runs.

Profiles in configs/models.yaml are the benchmark source of truth. Pi must send
those exact fields via its per-model ``samplingParams`` rather than silently
falling back to server defaults.
"""

import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from harness.adapters.sampling import validate_pi_sampling_params
from harness.runner import _manifest_sampling
from harness.telemetry import load_model_metadata


@pytest.mark.parametrize(
    ("model_id", "expected"),
    [
        ("local/deepseek-v4-flash-0731", {"temperature": 1.0, "top_p": 1.0}),
        (
            "local/qwen3.8-27b",
            {
                "temperature": 1.0,
                "top_p": 0.95,
                "top_k": 20,
                "min_p": 0.0,
                "presence_penalty": 0.0,
                "repetition_penalty": 1.0,
            },
        ),
        (
            "shisa/ornith-35b-fp8-block",
            {"temperature": 0.6, "top_p": 0.95, "top_k": 20},
        ),
    ],
)
def test_model_cards_have_explicit_sampling_profiles(model_id, expected):
    """Active agentic models must not use unrecorded server defaults."""
    metadata = load_model_metadata(model_id)
    assert metadata["sampling_params"] == expected
    assert metadata["sampling_source"]


@pytest.mark.parametrize(
    "model_id",
    [
        "codex/gpt-5.6-luna",
        "codex/gpt-5.6-terra",
        "codex/gpt-5.6-sol",
        "zai/glm-5.3",
    ],
)
def test_proprietary_campaign_models_have_explicit_limits(model_id):
    metadata = load_model_metadata(model_id)
    assert metadata["reasoning"] is True
    assert metadata["context_window"] >= 372000
    assert metadata["max_tokens"] == 128000
    assert metadata["reasoning_effort_source"]


def test_manifest_records_configured_profile_not_server_default():
    metadata = {
        "sampling_params": {"temperature": 1.0, "top_p": 0.95, "top_k": 64},
        "sampling_source": "model-card",
    }
    sampling = _manifest_sampling({}, model_metadata=metadata)
    assert sampling["temperature"] == 1.0
    assert sampling["top_p"] == 0.95
    assert sampling["top_k"] == 64
    assert sampling["max_tokens"] == "server-default"
    assert sampling["source"] == "model-card"
    assert _manifest_sampling({"max_tokens": 65536}, model_metadata=metadata)["max_tokens"] == 65536


def test_pi_sampling_params_must_match_profile(tmp_path):
    """Fail before a run if pi would silently use different parameters."""
    models_json = tmp_path / "models.json"
    models_json.write_text(
        json.dumps(
            {
                "providers": {
                    "local": {
                        "models": [
                            {
                                "id": "Qwen3.8-27B",
                                "samplingParams": {
                                    "temperature": 1.0,
                                    "top_p": 0.95,
                                    "top_k": 20,
                                    "min_p": 0.0,
                                    "presence_penalty": 0.0,
                                    "repetition_penalty": 1.0,
                                },
                            }
                        ]
                    }
                }
            }
        )
    )
    expected = {
        "temperature": 1.0,
        "top_p": 0.95,
        "top_k": 20,
        "min_p": 0.0,
        "presence_penalty": 0.0,
        "repetition_penalty": 1.0,
    }
    validate_pi_sampling_params(
        "local/qwen3.8-27b", expected, models_json_path=models_json
    )

    models_json.write_text(
        json.dumps(
            {
                "providers": {
                    "local": {
                        "models": [
                            {
                                "id": "Qwen3.8-27B",
                                "samplingParams": {"temperature": 1.0, "top_p": 1.0},
                            }
                        ]
                    }
                }
            }
        )
    )
    with pytest.raises(RuntimeError, match="samplingParams mismatch"):
        validate_pi_sampling_params(
            "local/qwen3.8-27b", expected, models_json_path=models_json
        )
