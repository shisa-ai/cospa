"""Session-path helpers shared by pi-backed benchmark adapters."""

from pathlib import Path


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
