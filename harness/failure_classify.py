"""Failure classification shared by the failure audit and verdict backfill.

Two distinct evidence surfaces feed classification:

- **Structural outcomes** (budget exhaustion, verifier timeout, compose
  failure) are signalled by exception/verifier shape — an exception type name
  or a structured flag — and are safe to read from any output.
- **Provider/adapter substring rules** (``403``/``forbidden``, ``usage limit``,
  ``connection error``, ...) read ONLY the manifest ``error`` field. Task and
  test output (the verdict's ``grader_output``) legitimately contains words
  like "forbidden", "403", "context" or "timeout" as test-case names and
  prose, so it must never feed these rules. The manifest ``error`` itself may
  embed the whole agent command (including the task prompt); only the
  trailing ``stdout:`` segment is the real error surface.
"""

from __future__ import annotations

from typing import Any


def manifest_surface(manifest: dict) -> str:
    """Clean manifest error text: only the meaningful trailing segment.

    Adapter failures may record the full agent command, which includes the
    task prompt whose prose routinely contains words like "forbidden",
    "context" or "timeout". Those must not feed the substring rules; the
    ``stdout:`` tail (e.g. ``Connection error.``) is the real error surface.
    Returns an empty string when the manifest has no error text.
    """
    error = manifest.get("error")
    if not isinstance(error, str) or not error.strip():
        return ""
    if "stdout:" in error:
        return error.rsplit("stdout:", 1)[-1].strip()
    return error.strip()


def classify_failure(verdict: dict, manifest: dict) -> str:
    """Classify one failed trial from its real error surface."""
    grader = str(verdict.get("grader_output") or "")
    manifest_error = str(manifest.get("error") or "")

    # Structural outcomes: exception/verifier shape, not prose.
    if verdict.get("failure_class") == "budget_exhausted" or (
        "AgentTimeoutError" in manifest_error or "AgentTimeoutError" in grader
    ):
        return "budget_exhausted"
    if verdict.get("verifier_failed") or "VerifierTimeoutError" in grader:
        return "verifier_timeout"
    if "Docker compose command failed" in grader:
        return "compose_failure"

    # Provider/adapter substring rules read only the manifest error surface.
    surface = manifest_surface(manifest).lower()
    if not surface:
        return "adapter_error_other" if verdict.get("adapter_failed") else "incorrect"

    if "usage limit" in surface or "rate limit" in surface:
        return "usage_limit"
    if "403" in surface or "forbidden" in surface:
        return "auth_forbidden"
    if (
        "maximum context" in surface
        or "context length" in surface
        or "context window" in surface
    ):
        return "context_limit"
    if "connection error" in surface or "connection failed" in surface:
        return "connection_error"
    if "http 5" in surface or "bad gateway" in surface or "502" in surface:
        return "http_error"
    if "timed out" in surface or "timeout" in surface:
        return "timeout_other"
    return "adapter_error_other" if verdict.get("adapter_failed") else "incorrect"
