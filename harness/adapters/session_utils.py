"""Session-path helpers shared by pi-backed benchmark adapters."""

from pathlib import Path


# Single-line hint attached to every eval task prompt. The eval sandbox has no
# network and hides reference files (e.g. hidden test files), so agents that try
# to fetch or search online burn their whole budget on requests that can never
# succeed. This line steers them to write the solution from what is provided.
NO_NETWORK_HINT = (
    "Note: This sandbox has NO network access. Do not try to fetch, search for, "
    "or look up any files, tests, or references online — write the solution "
    "entirely from the provided files and the problem statement."
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
