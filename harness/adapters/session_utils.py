"""Session-path helpers shared by pi-backed benchmark adapters."""

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
    return Path(log_file).parent / "pi-sessions"


def trial_session_args(log_file: Path | str) -> list[str]:
    """Return pi CLI arguments for trial-local session persistence."""
    return ["--session-dir", str(trial_session_dir(log_file))]
