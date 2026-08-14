"""Session-path and telemetry helpers shared by pi-backed adapters."""

import os
from pathlib import Path


# Single-line hint attached to every eval task prompt. The eval sandbox has no
# network and intentionally withholds reference tests/solutions, so agents that
# try to fetch or search for them burn their budget on unavailable information.
NO_NETWORK_HINT = (
    "NOTE: Network access, hidden test files, and reference solutions are "
    "unavailable. Solve the task directly from the problem statement and visible "
    "workspace."
)


def with_no_network_hint(prompt: str, *, at_top: bool = True) -> str:
    """Return ``prompt`` with the single-line no-network hint attached.

    Prepended by default so agents read it before exploring the workdir, which
    prevents futile web/searches when reference files are hidden.
    """
    if not prompt:
        return prompt
    if at_top:
        return NO_NETWORK_HINT + "\n\n" + prompt
    return prompt.rstrip() + "\n\n" + NO_NETWORK_HINT


def trial_session_dir(log_file: Path | str) -> Path:
    """Return a short-component session directory local to one trial.

    Pi's default session directory flattens the full workdir path into one
    filename component. Deep result roots can exceed Linux NAME_MAX (255
    bytes), so benchmark adapters always select an explicit directory instead.
    """
    return Path(log_file).resolve().parent / "pi-sessions"


def trial_session_args(log_file: Path | str) -> list[str]:
    """Return pi CLI arguments for trial-local session persistence."""
    return ["--session-dir", str(trial_session_dir(log_file))]


def behavior_trace_file(log_file: Path | str) -> Path:
    """Return the compact pi lifecycle-event trace path for this trial."""
    return trial_session_dir(log_file) / "behavior_events.jsonl"


def behavior_trace_args(log_file: Path | str) -> list[str]:
    """Return CLI args that load cospa's telemetry-only pi extension."""
    extension = Path(__file__).with_name("behavior_trace_extension.ts").resolve()
    return ["--extension", str(extension)]


def behavior_trace_env(log_file: Path | str) -> dict[str, str]:
    """Prepare a fresh trace and return the child environment pointing to it."""
    trace_file = behavior_trace_file(log_file)
    trace_file.parent.mkdir(parents=True, exist_ok=True)
    trace_file.unlink(missing_ok=True)
    env = os.environ.copy()
    env["COSPA_BEHAVIOR_TRACE_FILE"] = str(trace_file.resolve())
    return env
