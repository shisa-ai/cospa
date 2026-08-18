"""Failure-classifier tests.

The provider/adapter substring rules (``403``/``forbidden``, ``usage limit``,
``connection error``, ...) must read ONLY the manifest error surface. Task and
test output — which routinely contains test names like
``Test_detectDeviceFlow/403_forbidden`` and prose like "forbidden", "context"
or "timeout" — must never feed them. These regressions came from real trials:
gh-cli grader output (auth_forbidden false positive), the sympy adapter
failure whose embedded command contains the task prompt's "forbidden"
black_links, and the pytorch-lightning Harbor timeout that should be
budget_exhausted.
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from harness.failure_classify import classify_failure  # noqa: E402

COMMAND_NOISE = (
    "NonZeroAgentExitCodeError: Command failed (exit 1): bash -lc 'pi --print "
    "# Task: fix the maximum context length issue in prettier ... usage limit "
    "discussion ...' 2>&1 | tee /logs/x.txt\n"
)


def _verdict(grader: str = "", **kw):
    base = {"passed": False, "test_count": 0, "grader_output": grader}
    base.update(kw)
    return base


def test_grader_go_test_output_is_not_auth_forbidden():
    # Real gh-cli grader output: the Go test binary emits test-case names like
    # Test_detectDeviceFlow/403_forbidden and an internal/authflow package. A
    # genuine wrong answer, not a provider 403.
    grader = (
        "=== RUN   Test_detectDeviceFlow/success\n"
        "=== RUN   Test_detectDeviceFlow/403_forbidden\n"
        "=== RUN   Test_detectDeviceFlow/404_not_found\n"
        "--- FAIL: Test_detectDeviceFlow/403_forbidden (0.00s)\n"
        "    authflow: response status 403\n"
    )
    verdict = _verdict(grader=grader)  # no adapter failure: verifier ran
    assert classify_failure(verdict, {}) == "incorrect"


def test_manifest_command_with_task_prompt_is_connection_error():
    # Real sympy adapter failure: the manifest error embeds the whole agent
    # command, including the task prompt's "You are forbidden to access ..."
    # black_links prose. Only the trailing stdout segment is the real surface:
    # a provider connection error.
    error = (
        "NonZeroAgentExitCodeError: Command failed (exit 1): bash -lc 'pi --print "
        "--thinking high # Benchmark execution context ... You are forbidden to "
        "access the following URLs: black_links ...' 2>&1 | tee /logs/x.txt\n"
        "stdout: Connection error.\n"
        "stderr: None"
    )
    verdict = _verdict(adapter_failed=True)
    assert classify_failure(verdict, {"error": error}) == "connection_error"


def test_agent_timeout_in_manifest_error_is_budget_exhausted():
    # Real pytorch-lightning Harbor timeout: the manifest error carries the
    # exception type even when grader_output is empty.
    manifest = {
        "error": "AgentTimeoutError: Agent execution timed out after 3600.0 seconds"
    }
    assert classify_failure(_verdict(), manifest) == "budget_exhausted"
    assert classify_failure(_verdict(adapter_failed=True), manifest) == "budget_exhausted"


def test_provider_rules_read_manifest_surface_only():
    cases = [
        (
            COMMAND_NOISE + "agent stuff\nstdout: Codex error: The usage limit has been reached\n",
            "usage_limit",
        ),
        (
            COMMAND_NOISE + "stdout: HTTP 429 Too Many Requests; retry-after: 5\n",
            "usage_limit",
        ),
        (
            COMMAND_NOISE + "stdout: HTTP 502: upstream 403 Forbidden\n",
            "auth_forbidden",
        ),
        (
            COMMAND_NOISE + "stdout: Error: maximum context length exceeded: 128000 tokens\n",
            "context_limit",
        ),
        (
            COMMAND_NOISE + "stdout: Connection error.\n",
            "connection_error",
        ),
        (
            COMMAND_NOISE + "stdout: 502 Bad Gateway from upstream\n",
            "http_error",
        ),
    ]
    for error, expected in cases:
        verdict = _verdict(adapter_failed=True)
        assert classify_failure(verdict, {"error": error}) == expected, error[:60]


def test_provider_words_in_test_output_are_not_provider_failures():
    # A verifier-graded wrong answer whose test output mentions "usage limit"
    # and "forbidden" as prose must stay "incorrect", not become a capacity class.
    grader = (
        "test_pricing: usage limit discussion in docs\n"
        "forbidden: expected no access, got 200\n"
        "some test timed out after 30s\n"
    )
    verdict = _verdict(grader=grader)
    assert classify_failure(verdict, {}) == "incorrect"


def test_structural_outcomes_from_exception_shape():
    assert (
        classify_failure(
            _verdict(failure_class="budget_exhausted"),
            {},
        )
        == "budget_exhausted"
    )
    assert (
        classify_failure(
            _verdict(grader="AgentTimeoutError: agent timed out after 600.0 seconds"),
            {},
        )
        == "budget_exhausted"
    )
    assert (
        classify_failure(
            _verdict(verifier_failed=True, grader="Verifier blew up"),
            {},
        )
        == "verifier_timeout"
    )
    assert (
        classify_failure(
            _verdict(grader="RuntimeError: Docker compose command failed for env x"),
            {},
        )
        == "compose_failure"
    )


def test_empty_manifest_surface_falls_back_to_adapter_or_incorrect():
    assert classify_failure(_verdict(), {}) == "incorrect"
    assert classify_failure(_verdict(adapter_failed=True), {}) == "adapter_error_other"


def test_classifier_prefers_manifest_error_field():
    verdict = _verdict(grader="Adapter failed with exit code -1: noisy output")
    manifest = {"error": "Codex error: The usage limit has been reached"}
    assert classify_failure(verdict, manifest) == "usage_limit"
