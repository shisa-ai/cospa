"""Cost pricing from models.yaml prices x usage (RUN-MANAGEMENT P5)."""

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from harness.cost import (  # noqa: E402
    compute_cost_usd,
    price_table,
    trial_cost,
)


def test_price_table_normalizes_keys():
    price = price_table(
        {"input": 5.0, "output": 30.0, "cacheRead": 0.5, "cacheWrite": 0}
    )
    assert price["standard"] == {
        "input": 5.0,
        "output": 30.0,
        "cacheRead": 0.5,
        "cacheWrite": 0.0,
    }
    assert price["long"] is None
    assert price["long_threshold"] is None
    assert price_table(None) is None
    assert price_table({}) is not None


def test_compute_cost_usd_basic():
    # input 5.0/1M, output 30.0/1M, cacheRead 0.5/1M
    price = price_table({"input": 5.0, "output": 30.0, "cacheRead": 0.5})
    # 1M prompt + 200k completion + 500k cached
    usd = compute_cost_usd(price, 1_000_000, 200_000, cached_tokens=500_000)
    assert usd == pytest.approx(5.0 + 6.0 + 0.25)


def test_compute_cost_usd_long_context_switch():
    price = price_table(
        {
            "input": 5.0,
            "output": 30.0,
            "longContextInputThreshold": 272000,
            "longContextInput": 10.0,
            "longContextOutput": 45.0,
        }
    )
    # Below threshold: standard rate.
    below = compute_cost_usd(price, 200_000, 100_000)
    assert below == pytest.approx((200_000 * 5.0 + 100_000 * 30.0) / 1e6)
    # Above threshold: long-context rate.
    above = compute_cost_usd(price, 300_000, 100_000)
    assert above == pytest.approx((300_000 * 10.0 + 100_000 * 45.0) / 1e6)


def test_trial_cost_from_session_usage():
    model = {"cost": {"input": 5.0, "output": 30.0, "cacheRead": 0.5}}
    usage = {
        "status": "observed",
        "prompt_tokens": 1_000_000,
        "completion_tokens": 200_000,
        "cached_tokens": 500_000,
        "cache_creation_tokens": 0,
        "total_tokens": 1_700_000,
    }
    cost = trial_cost(model, usage)
    assert cost is not None
    assert cost["usd"] == pytest.approx(5.0 + 6.0 + 0.25)
    assert cost["source"] == "models-config"
    assert cost["tokens"]["prompt"] == 1_000_000


def test_trial_cost_none_when_unpriced_or_no_usage():
    model = {"cost": {"input": 0, "output": 0}}
    usage = {
        "status": "observed",
        "prompt_tokens": 100,
        "completion_tokens": 50,
        "total_tokens": 150,
    }
    # Zero prices still yield a zero-cost record (priced, but free).
    assert trial_cost(model, usage) is not None
    # No cost table at all -> unpriced.
    assert trial_cost({"cost": None}, usage) is None
    # No usage -> unpriced.
    assert trial_cost(model, {}) is None
    assert trial_cost(model, None) is None
    # Zero-token usage -> unpriced.
    assert trial_cost(model, {"prompt_tokens": 0, "completion_tokens": 0}) is None


def test_trial_cost_minimal_adapter_usage():
    model = {"cost": {"input": 2.0, "output": 8.0}}
    usage = {"prompt_tokens": 500_000, "completion_tokens": 250_000}
    cost = trial_cost(model, usage)
    assert cost["usd"] == pytest.approx((500_000 * 2.0 + 250_000 * 8.0) / 1e6)
