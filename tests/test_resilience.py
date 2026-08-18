"""Resilience helpers: structured provider errors, retry backoff, circuit breaker."""

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from harness.resilience import (  # noqa: E402
    CircuitBreaker,
    agent_produced_output,
    extract_http_status,
    extract_retry_after,
    provider_error_from,
    provider_outage,
    retry_delay,
    trial_is_outage,
    write_paused_marker,
)


def _verdict(grader: str = "", **kw):
    base = {"passed": False, "test_count": 0, "grader_output": grader}
    base.update(kw)
    return base


def _manifest(error: str | None, **kw):
    m = {"error": error, "model_id": "codex/gpt-5.6-luna"}
    m.update(kw)
    return m


# --- HTTP status / Retry-After extraction ---


def test_extract_http_status():
    assert extract_http_status("HTTP 429 Too Many Requests") == 429
    assert extract_http_status("502 Bad Gateway from upstream") == 502
    assert extract_http_status("upstream 403 Forbidden") == 403
    assert extract_http_status("The usage limit has been reached") is None
    assert extract_http_status("") is None


def test_extract_retry_after():
    assert extract_retry_after("retry-after: 30") == 30
    assert extract_retry_after("Retry-After: 45") == 45
    assert extract_retry_after("please retry after 10 seconds") == 10
    assert extract_retry_after("Connection error.") is None


# --- structured provider error ---


def test_provider_error_connection():
    m = _manifest("Command failed\nstdout: Connection error.\nstderr: None")
    v = _verdict(adapter_failed=True)
    pe = provider_error_from(m, v)
    assert pe["kind"] == "connection_error"
    assert pe["status"] is None
    assert pe["retry_after"] is None
    assert pe["provider"] == "codex"


def test_provider_error_usage_limit_with_status_and_retry_after():
    m = _manifest(
        "Command failed\nstdout: HTTP 429 Too Many Requests; retry-after: 5\n"
    )
    v = _verdict(adapter_failed=True)
    pe = provider_error_from(m, v)
    assert pe["kind"] == "usage_limit"
    assert pe["status"] == 429
    assert pe["retry_after"] == 5


def test_provider_error_not_for_capability_or_eval_failures():
    # Wrong answer: no provider error record.
    assert provider_error_from(_manifest(None), _verdict()) is None
    # Budget exhaustion: no provider error record.
    m = _manifest("AgentTimeoutError: timed out after 3600.0 seconds")
    v = _verdict(failure_class="budget_exhausted")
    assert provider_error_from(m, v) is None
    # Eval-side compose failure: no provider error record.
    v = _verdict(grader="RuntimeError: Docker compose command failed for env x")
    assert provider_error_from(_manifest(None), v) is None


# --- retry backoff ---


def test_retry_delay_exponential_and_cap():
    assert retry_delay(None, attempt=1, jitter_ratio=0) == 2.0
    assert retry_delay(None, attempt=2, jitter_ratio=0) == 4.0
    assert retry_delay(None, attempt=3, jitter_ratio=0) == 8.0
    assert retry_delay(None, attempt=10, jitter_ratio=0) == 120.0  # capped


def test_retry_delay_honors_retry_after_and_wait_class():
    pe = {"kind": "usage_limit", "retry_after": 30, "status": 429}
    assert retry_delay(pe, attempt=1, jitter_ratio=0) == 30.0
    pe_nora = {"kind": "usage_limit", "retry_after": None, "status": 429}
    assert retry_delay(pe_nora, attempt=1, jitter_ratio=0) == 8.0
    pe_conn = {"kind": "connection_error", "retry_after": None, "status": None}
    assert retry_delay(pe_conn, attempt=1, jitter_ratio=0) == 2.0


def test_retry_delay_jitter_stays_within_band():
    for _ in range(50):
        d = retry_delay(None, attempt=1, jitter_ratio=0.2)
        assert 2.0 * 0.8 <= d <= 2.0 * 1.2


# --- provider outage (circuit-breaker input) ---


def test_provider_outage_classification():
    assert provider_outage(
        _manifest("stdout: Connection error."),
        _verdict(adapter_failed=True),
        agent_produced_output=False,
    ) is True
    assert provider_outage(
        _manifest("stdout: HTTP 502 Bad Gateway"),
        _verdict(adapter_failed=True),
        agent_produced_output=False,
    ) is True
    # Hung budget exhaustion with no agent output counts as outage.
    assert provider_outage(
        _manifest("AgentTimeoutError: timed out after 3600.0 seconds"),
        _verdict(failure_class="budget_exhausted"),
        agent_produced_output=False,
    ) is True
    # Budget exhaustion after real work is not an outage.
    assert provider_outage(
        _manifest("AgentTimeoutError: timed out after 3600.0 seconds"),
        _verdict(failure_class="budget_exhausted"),
        agent_produced_output=True,
    ) is False
    # A wrong answer is never an outage.
    assert provider_outage(_manifest(None), _verdict(), True) is False


# --- circuit breaker ---


def test_breaker_opens_at_threshold_and_resets_on_pass():
    b = CircuitBreaker(threshold=3)
    b.record(True)
    b.record(True)
    assert b.open() is False
    b.record(True)
    assert b.open() is True
    assert b.snapshot()["consecutive_outages"] == 3
    b.record(False)  # a pass resets
    assert b.open() is False
    assert b.consecutive_outages == 0


def test_breaker_disabled_never_opens():
    b = CircuitBreaker(threshold=2, enabled=False)
    for _ in range(10):
        b.record(True)
    assert b.open() is False


# --- agent-output detection / outage decision / pause marker ---


def test_agent_produced_output(tmp_path):
    # No session at all -> no output.
    assert agent_produced_output(tmp_path) is False
    out = tmp_path / "out"
    out.mkdir(parents=True)
    session = out / "pi_session.jsonl"
    # A real session with a model response -> output produced.
    session.write_text(
        json.dumps(
            {
                "type": "event",
                "message": {
                    "role": "assistant",
                    "content": "I solved it",
                    "usage": {"input": 10, "output": 5, "total": 15},
                },
            }
        )
        + "\n"
    )
    assert agent_produced_output(tmp_path) is True
    # A session with only a header (hung trial) -> no output.
    session.write_text(json.dumps({"type": "session", "id": "s1"}) + "\n")
    assert agent_produced_output(tmp_path) is False


def test_trial_is_outage(tmp_path):
    m = _manifest("AgentTimeoutError: timed out after 3600.0 seconds")
    v = _verdict(failure_class="budget_exhausted")
    # Hung budget exhaustion with no agent output -> outage.
    assert trial_is_outage(m, v, tmp_path) is True
    # Same classification but the agent did real work -> not an outage.
    out = tmp_path / "out"
    out.mkdir(parents=True)
    (out / "pi_session.jsonl").write_text(
        json.dumps(
            {
                "type": "event",
                "message": {
                    "role": "assistant",
                    "content": "work",
                    "usage": {"input": 1, "output": 1, "total": 2},
                },
            }
        )
        + "\n"
    )
    assert trial_is_outage(m, v, tmp_path) is False
    # Unambiguous endpoint class counts regardless of output.
    mc = _manifest("stdout: Connection error.")
    vc = _verdict(adapter_failed=True)
    assert trial_is_outage(mc, vc, tmp_path) is True
    # Capability outcome never counts.
    assert trial_is_outage(_manifest(None), _verdict(), tmp_path) is False


def test_write_paused_marker(tmp_path):
    b = CircuitBreaker(threshold=3)
    b.record(True)
    b.record(True)
    b.record(True)
    path = write_paused_marker(
        tmp_path,
        b,
        model="kimi/kimi-k3",
        adapter="pi_vanilla",
        suite="featurebench_lite",
        run_id="r1",
        last_trial=("t1", 2),
    )
    assert path.name == ".cell-paused.json"
    data = json.loads(path.read_text())
    assert data["state"] == "paused"
    assert data["reason"] == "circuit_breaker"
    assert data["breaker"]["open"] is True
    assert data["breaker"]["consecutive_outages"] == 3
    assert data["last_trial"] == ["t1", 2]
    assert data["paused_at"]
