"""Per-trial cost pricing from models.yaml prices x pi usage (RUN-MANAGEMENT P5).

The manifest already records ``model.cost`` (prices from configs/models.yaml,
``usd_per_1m_tokens``) and ``token_usage`` (from the pi session). This module
derives ``manifest.cost`` at runtime and lets historical manifests be priced
retroactively.

Prices are per 1M tokens. Long-context tiers (e.g. codex) switch prices when
the prompt exceeds ``longContextInputThreshold`` tokens.
"""

from __future__ import annotations

from typing import Any

MILLION = 1_000_000


def _pick(value: dict, *keys) -> float | None:
    for key in keys:
        item = value.get(key)
        if isinstance(item, (int, float)) and not isinstance(item, bool):
            return float(item)
    return None


def price_table(cost: dict | None) -> dict[str, Any] | None:
    """Normalize a models.yaml ``cost`` dict.

    Returns ``{"standard": {...}, "long": {...}|None, "long_threshold": n|None}``
    with per-1M-token rates for input/output/cacheRead/cacheWrite.
    Returns None for a missing or non-dict cost entry.
    """
    if not isinstance(cost, dict):
        return None
    standard = {
        "input": _pick(cost, "input") or 0.0,
        "output": _pick(cost, "output") or 0.0,
        "cacheRead": _pick(cost, "cacheRead", "cache_read") or 0.0,
        "cacheWrite": _pick(cost, "cacheWrite", "cache_write") or 0.0,
    }
    threshold = _pick(
        cost, "longContextInputThreshold", "long_context_input_threshold"
    )
    long = None
    if threshold is not None:
        long = {
            "input": _pick(cost, "longContextInput", "long_context_input")
            or standard["input"],
            "output": _pick(cost, "longContextOutput", "long_context_output")
            or standard["output"],
            "cacheRead": _pick(
                cost, "longContextCacheRead", "long_context_cache_read"
            )
            or standard["cacheRead"],
            "cacheWrite": _pick(
                cost, "longContextCacheWrite", "long_context_cache_write"
            )
            or standard["cacheWrite"],
        }
    return {"standard": standard, "long": long, "long_threshold": threshold}


def compute_cost_usd(
    price: dict[str, Any],
    prompt_tokens,
    completion_tokens,
    cached_tokens=0,
    cache_creation_tokens=0,
) -> float:
    """USD cost for the given usage under a price table."""
    table = price["standard"]
    threshold = price.get("long_threshold")
    if (
        threshold is not None
        and price.get("long") is not None
        and (prompt_tokens or 0) > threshold
    ):
        table = price["long"]
    usd = (
        (prompt_tokens or 0) * table["input"]
        + (cached_tokens or 0) * table["cacheRead"]
        + (cache_creation_tokens or 0) * table["cacheWrite"]
        + (completion_tokens or 0) * table["output"]
    ) / MILLION
    return round(usd, 6)


def trial_cost(model_meta: dict | None, token_usage: dict | None) -> dict | None:
    """Priced cost record for one trial's usage, or None when unpriced.

    Works for both the full pi-session usage dict (status ``observed``, with
    cached/cache-creation counts) and the minimal adapter usage dict (just
    prompt/completion counts).
    """
    if not isinstance(token_usage, dict):
        return None
    if not (token_usage.get("prompt_tokens") or token_usage.get("completion_tokens")):
        return None
    cost_cfg = (model_meta or {}).get("cost") if isinstance(model_meta, dict) else None
    price = price_table(cost_cfg)
    if price is None:
        return None
    usd = compute_cost_usd(
        price,
        token_usage.get("prompt_tokens"),
        token_usage.get("completion_tokens"),
        cached_tokens=token_usage.get("cached_tokens"),
        cache_creation_tokens=token_usage.get("cache_creation_tokens"),
    )
    return {
        "usd": usd,
        "currency": "USD",
        "pricing_unit": "usd_per_1m_tokens",
        "source": "models-config",
        "tokens": {
            "prompt": token_usage.get("prompt_tokens"),
            "completion": token_usage.get("completion_tokens"),
            "cached": token_usage.get("cached_tokens"),
            "cache_creation": token_usage.get("cache_creation_tokens"),
        },
    }
