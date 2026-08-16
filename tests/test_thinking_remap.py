"""Thinking-level verification must honor provider thinkingLevelMap remaps."""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from harness.runner import _thinking_level_check


def test_provider_remapped_level_is_observed_not_failed(monkeypatch):
    """A provider map translating high->None (server default) is legitimate.

    Qwen3.8 remaps Pi 'high' to no explicit effort; the server then reports
    its native default (xhigh). The check must record the observation
    instead of failing the trial.
    """
    import harness.runner as runner_mod

    monkeypatch.setattr(
        runner_mod,
        "pi_thinking_level_map",
        lambda model_id: {"high": None, "xhigh": "xhigh"},
    )

    result = _thinking_level_check(
        "local/qwen3.8-27b", requested="high", observed="xhigh"
    )

    assert result == {
        "status": "observed",
        "thinking_observed": "xhigh",
    }


def test_explicit_map_translation_mismatch_still_fails(monkeypatch):
    """If the map says high->high but the session reports xhigh, that is a
    real mismatch and must still fail closed."""
    import harness.runner as runner_mod

    monkeypatch.setattr(
        runner_mod,
        "pi_thinking_level_map",
        lambda model_id: {"high": "high"},
    )

    result = _thinking_level_check(
        "local/test-model", requested="high", observed="xhigh"
    )

    assert result["status"] == "mismatch"
    assert result["thinking_mismatch"] == {
        "requested": "high",
        "observed": "xhigh",
    }
    assert "provider-mapped" in result["error"]


def test_no_map_exact_match_and_default_pass(monkeypatch):
    import harness.runner as runner_mod

    monkeypatch.setattr(
        runner_mod, "pi_thinking_level_map", lambda model_id: {}
    )

    assert (
        _thinking_level_check("m/x", requested="high", observed="high")[
            "status"
        ]
        == "ok"
    )
    assert (
        _thinking_level_check("m/x", requested=None, observed="high")["status"]
        == "ok"
    )
    assert (
        _thinking_level_check(
            "m/x", requested="default", observed="whatever"
        )["status"]
        == "ok"
    )


def test_map_translation_to_matching_native_level_passes(monkeypatch):
    """A map translating high->xhigh with the session observing xhigh is a
    legitimate translated match (documented Qwen3.8 fallback behavior)."""
    import harness.runner as runner_mod

    monkeypatch.setattr(
        runner_mod,
        "pi_thinking_level_map",
        lambda model_id: {"high": "xhigh"},
    )

    result = _thinking_level_check(
        "local/qwen3.8-27b", requested="high", observed="xhigh"
    )

    assert result == {"status": "ok"}


def test_pi_thinking_level_map_loads_qwen_from_real_registry(monkeypatch):
    """The real ~/.pi/agent/models.json qwen entry must expose its map."""
    import harness.telemetry as telemetry_mod

    level_map = telemetry_mod.pi_thinking_level_map("local/qwen3.8-27b")
    assert isinstance(level_map, dict)
    assert level_map.get("high") is None  # provider-managed per MODEL-MAPPINGS
