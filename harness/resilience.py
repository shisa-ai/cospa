"""Resilience helpers for long-running evals: structured provider errors,
retry backoff, and the mid-run circuit breaker (RUN-MANAGEMENT P1-P3).

- ``provider_error_from`` records a failed trial's provider failure mode as
  data (``kind``, HTTP ``status``, ``retry_after``, ``provider``) so retry,
  resume, and analysis are not substring-based.
- ``retry_delay`` computes how long to wait before the next attempt, honoring
  ``Retry-After`` when the provider sends one and otherwise using exponential
  backoff with jitter.
- ``CircuitBreaker`` pauses a cell after a run of consecutive provider
  outages so a dead endpoint does not burn the remaining budget.
"""

from __future__ import annotations

import json
import random
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from harness.failure_classify import classify_failure, manifest_surface

# Provider/endpoint failure classes: the endpoint did not serve us. Eval-side
# classes (``compose_failure``, ``verifier_timeout``) and capability outcomes
# (``budget_exhausted``, ``incorrect``) are deliberately excluded.
PROVIDER_ERROR_CLASSES = frozenset(
    {
        "connection_error",
        "http_error",
        "usage_limit",
        "auth_forbidden",
        "context_limit",
        "timeout_other",
    }
)

# Provider outage classes: a run of these in a row means "the endpoint is
# down", not "the model answered poorly".
PROVIDER_OUTAGE_CLASSES = frozenset(
    {"connection_error", "http_error", "usage_limit", "auth_forbidden"}
)

# Classes that should wait (back off harder / honor Retry-After): throttling.
RETRY_WAIT_CLASSES = frozenset({"usage_limit"})

RETRY_BACKOFF_BASE_SECONDS = 2.0
RETRY_BACKOFF_CAP_SECONDS = 120.0
RETRY_AFTER_CAP_SECONDS = 600.0

_HTTP_STATUS_RE = re.compile(r"\b([45]\d{2})\b")
_RETRY_AFTER_RE = re.compile(
    r"retry[-\s]after\s*[:\s=]+\s*(\d+)", re.IGNORECASE
)


def extract_http_status(surface: str) -> int | None:
    """Return an HTTP status code mentioned in the error surface, if any."""
    match = _HTTP_STATUS_RE.search(surface or "")
    return int(match.group(1)) if match else None


def extract_retry_after(surface: str) -> int | None:
    """Return a numeric ``Retry-After`` (seconds) from the error surface."""
    match = _RETRY_AFTER_RE.search(surface or "")
    return int(match.group(1)) if match else None


def provider_error_from(manifest: dict, verdict: dict) -> dict[str, Any] | None:
    """Structured provider failure record for a failed trial, or None.

    Only fires for provider/endpoint-shaped failures (see
    ``PROVIDER_ERROR_CLASSES``). Returns ``None`` for wrong answers,
    budget exhaustion, and eval-side failures so retry logic can ignore them.
    """
    cls = classify_failure(verdict, manifest)
    if cls not in PROVIDER_ERROR_CLASSES:
        return None
    surface = manifest_surface(manifest)
    model = manifest.get("model") or {}
    provider = model.get("provider") or (
        str(manifest.get("model_id") or "").split("/", 1)[0] or None
    )
    return {
        "kind": cls,
        "status": extract_http_status(surface),
        "retry_after": extract_retry_after(surface),
        "provider": provider,
    }


def retry_delay(
    provider_error: dict[str, Any] | None,
    attempt: int,
    *,
    jitter_ratio: float = 0.2,
) -> float:
    """Seconds to wait before the next retry attempt.

    Honors ``Retry-After`` when present; otherwise exponential backoff
    (``2 ** attempt`` seconds), with the ``usage_limit`` class starting higher.
    Pass ``jitter_ratio=0`` for deterministic tests.
    """
    attempt = max(1, int(attempt))
    wait = (provider_error or {}).get("retry_after")
    if isinstance(wait, (int, float)) and wait > 0:
        base = float(min(wait, RETRY_AFTER_CAP_SECONDS))
    elif provider_error and provider_error.get("kind") in RETRY_WAIT_CLASSES:
        base = min(
            RETRY_BACKOFF_BASE_SECONDS * (2 ** (attempt + 1)),
            RETRY_BACKOFF_CAP_SECONDS,
        )
    else:
        base = min(
            RETRY_BACKOFF_BASE_SECONDS * (2 ** (attempt - 1)),
            RETRY_BACKOFF_CAP_SECONDS,
        )
    if jitter_ratio:
        base = base * (1 - jitter_ratio + 2 * jitter_ratio * random.random())
    return base


def provider_outage(
    manifest: dict,
    verdict: dict,
    agent_produced_output: bool,
) -> bool:
    """True when a failed trial signals the provider/endpoint is down.

    Unambiguous endpoint classes count directly. A ``budget_exhausted`` trial
    counts as an outage only when the agent produced no output at all (it
    hung waiting for a response the endpoint never delivered).
    """
    cls = classify_failure(verdict, manifest)
    if cls in PROVIDER_OUTAGE_CLASSES:
        return True
    if cls == "budget_exhausted" and not agent_produced_output:
        return True
    return False


class CircuitBreaker:
    """Pauses a cell after consecutive provider outages (RUN-MANAGEMENT P1).

    Records trial outcomes with :meth:`record`. Once the consecutive outage
    streak reaches ``threshold``, the breaker opens and the caller should stop
    scheduling new trials (and typically write a ``paused`` marker). A pass
    resets the streak.
    """

    def __init__(
        self,
        threshold: int = 3,
        *,
        enabled: bool = True,
    ) -> None:
        self.threshold = max(1, int(threshold))
        self.enabled = bool(enabled)
        self.consecutive_outages = 0

    def record(self, outage: bool) -> None:
        """Record one trial outcome (True = provider outage)."""
        if not self.enabled:
            return
        if outage:
            self.consecutive_outages += 1
        else:
            self.consecutive_outages = 0

    def open(self) -> bool:
        """True when the streak reached the threshold and scheduling should stop."""
        return self.enabled and self.consecutive_outages >= self.threshold

    def snapshot(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "threshold": self.threshold,
            "consecutive_outages": self.consecutive_outages,
            "open": self.open(),
        }


def agent_produced_output(trial_dir) -> bool:
    """True when any pi session in the trial produced model responses.

    Used to tell a hung ``budget_exhausted`` trial (no responses — the
    endpoint never answered) apart from one that did real work and hit its
    budget. Reads the usage-captured session copies in ``out/`` first, then
    falls back to Harbor job artifacts.
    """
    from harness.telemetry import summarize_pi_session

    trial_dir = Path(trial_dir)
    candidates: list[Path] = []
    single = trial_dir / "out" / "pi_session.jsonl"
    multi = trial_dir / "out" / "pi_sessions"
    if single.exists():
        candidates.append(single)
    if multi.is_dir():
        candidates += sorted(multi.glob("*.jsonl"))
    if not candidates:
        for p in trial_dir.rglob("*.jsonl"):
            if "pi-sessions" in p.parts:
                candidates.append(p)
    for path in candidates:
        try:
            summary = summarize_pi_session(path)
        except OSError:
            continue
        if summary.get("response_count", 0) > 0:
            return True
    return False


def trial_is_outage(manifest: dict, verdict: dict, trial_dir) -> bool:
    """Provider outage signal for this trial (lazily checks agent output).

    Unambiguous endpoint classes count directly. A ``budget_exhausted``
    trial counts only when the agent produced no output (it hung). Capability
    and eval-side outcomes never count.
    """
    cls = classify_failure(verdict, manifest)
    if cls not in PROVIDER_OUTAGE_CLASSES and cls != "budget_exhausted":
        return False
    agent_produced = True
    if cls == "budget_exhausted":
        agent_produced = agent_produced_output(trial_dir)
    return provider_outage(manifest, verdict, agent_produced)


def write_paused_marker(
    cell_dir,
    breaker: CircuitBreaker,
    *,
    model: str,
    adapter: str,
    suite: str,
    run_id: str | None,
    last_trial: tuple[str, int],
) -> Path:
    """Write a durable ``.cell-paused.json`` marker for a tripped breaker.

    A matrix orchestrator (RUN-MANAGEMENT P4) skips a paused cell until it is
    re-armed; a standalone runner exits with a distinct code after writing it.
    """
    cell_dir = Path(cell_dir)
    cell_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "state": "paused",
        "reason": "circuit_breaker",
        "breaker": breaker.snapshot(),
        "model": model,
        "adapter": adapter,
        "suite": suite,
        "run_id": run_id,
        "last_trial": [last_trial[0], last_trial[1]],
        "paused_at": datetime.now(timezone.utc).isoformat(),
    }
    path = cell_dir / ".cell-paused.json"
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n")
    tmp.replace(path)
    return path


def sleep_seconds(seconds: float) -> None:
    """Sleep that tests can replace with a recorder."""
    time.sleep(max(0.0, seconds))
