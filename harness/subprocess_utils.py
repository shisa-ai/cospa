"""Subprocess helpers for eval tools that spawn their own child trees."""

from __future__ import annotations

import atexit
import ctypes
import hashlib
import os
import re
import signal
import subprocess
import threading
from collections.abc import Sequence
from pathlib import Path
from typing import Any


_ACTIVE_PROCESS_GROUPS: set[int] = set()
_ACTIVE_LOCK = threading.Lock()
_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def agent_sandbox_cwd(
    workdir: str | os.PathLike[str], task_name: str | None = None
) -> Path:
    """Return the stable virtual cwd used for one isolated trial."""
    digest = hashlib.sha256(str(Path(workdir).resolve()).encode()).hexdigest()[:16]
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "-", task_name or "workspace")
    safe_name = safe_name.strip(".-") or "workspace"
    return Path("/mnt") / f"cospa-{digest}" / safe_name


def _sandbox_agent_command(
    cmd: Sequence[str],
    workdir: str | os.PathLike[str],
    task_name: str | None = None,
) -> list[str]:
    """Confine an agent to its trial while preserving tools and networking.

    The host filesystem is read-only, the active trial is writable at /mnt,
    and the shared benchmark dataset and prior result trees are hidden.
    Existing pi configuration uses a private overlay, prior sessions are hidden,
    and only the current trial's session directory is writable for telemetry.
    """
    workdir = Path(workdir).resolve()
    sandbox_cwd = agent_sandbox_cwd(workdir, task_name)
    sandbox_parent = sandbox_cwd.parent
    pi_home = Path.home() / ".pi"
    sessions_root = pi_home / "agent" / "sessions"
    encoded_cwd = str(sandbox_cwd).strip("/").replace("/", "-")
    trial_session_dir = sessions_root / f"--{encoded_cwd}--"
    trial_session_dir.mkdir(parents=True, exist_ok=True)
    wrapped = [
        "bwrap",
        "--die-with-parent",
        "--unshare-pid",
        "--ro-bind",
        "/",
        "/",
    ]
    if pi_home.is_dir():
        wrapped.extend(
            ["--overlay-src", str(pi_home), "--tmp-overlay", str(pi_home)]
        )
    cache_dir = Path.home() / ".cache"
    if cache_dir.is_dir():
        wrapped.extend(
            ["--overlay-src", str(cache_dir), "--tmp-overlay", str(cache_dir)]
        )
    wrapped.extend(
        [
            "--tmpfs",
            str(sessions_root),
            "--dir",
            str(trial_session_dir),
            "--bind",
            str(trial_session_dir),
            str(trial_session_dir),
        ]
    )
    wrapped.extend(
        [
            "--tmpfs",
            str(_PROJECT_ROOT / "vendor"),
            "--tmpfs",
            str(_PROJECT_ROOT / "results"),
            "--tmpfs",
            "/tmp",
            "--tmpfs",
            "/mnt",
            "--dir",
            str(sandbox_parent),
            "--dir",
            str(sandbox_cwd),
            "--bind",
            str(workdir),
            str(sandbox_cwd),
            "--dev",
            "/dev",
            "--proc",
            "/proc",
            "--chdir",
            str(sandbox_cwd),
            *cmd,
        ]
    )
    return wrapped


def _set_parent_death_signal(signum: int = signal.SIGTERM) -> None:
    """Ask Linux to signal the direct child when this runner dies."""
    try:
        libc = ctypes.CDLL(None)
        pr_set_pdeathsig = 1
        libc.prctl(pr_set_pdeathsig, signum)
    except Exception:
        return


def _configure_child_process() -> None:
    os.setsid()
    _set_parent_death_signal(signal.SIGTERM)
    if os.getppid() == 1:
        os.kill(os.getpid(), signal.SIGTERM)


def _remember_process_group(pgid: int) -> None:
    with _ACTIVE_LOCK:
        _ACTIVE_PROCESS_GROUPS.add(pgid)


def _forget_process_group(pgid: int) -> None:
    with _ACTIVE_LOCK:
        _ACTIVE_PROCESS_GROUPS.discard(pgid)


def terminate_process_group(pgid: int) -> None:
    """Send SIGTERM to a process group if it still exists."""
    try:
        os.killpg(pgid, signal.SIGTERM)
    except ProcessLookupError:
        return
    except OSError:
        return


def terminate_active_process_groups() -> None:
    """Best-effort cleanup for adapter/verifier child process groups."""
    with _ACTIVE_LOCK:
        pgids = list(_ACTIVE_PROCESS_GROUPS)
    for pgid in pgids:
        terminate_process_group(pgid)


atexit.register(terminate_active_process_groups)


def _termination_signal_handler(signum, frame) -> None:
    terminate_active_process_groups()
    signal.signal(signum, signal.SIG_DFL)
    os.kill(os.getpid(), signum)


for _signum in (signal.SIGHUP, signal.SIGTERM):
    try:
        if signal.getsignal(_signum) != signal.SIG_IGN:
            signal.signal(_signum, _termination_signal_handler)
    except (ValueError, OSError):
        pass


def run_command(
    cmd: Sequence[str],
    *,
    input: str | bytes | None = None,
    cwd: str | os.PathLike[str] | None = None,
    stdout: Any = None,
    stderr: Any = None,
    capture_output: bool = False,
    text: bool = False,
    timeout: float | None = None,
    env: dict[str, str] | None = None,
    sandbox_workdir: str | os.PathLike[str] | None = None,
    sandbox_name: str | None = None,
) -> subprocess.CompletedProcess:
    """Run a command in its own process group and clean up on timeout.

    Python's `subprocess.run(..., timeout=...)` only guarantees cleanup of the
    immediate child. Eval adapters launch tools that launch package managers,
    browsers, compilers, and test binaries; those must be terminated as one
    process group when a trial times out or the runner exits cleanly.
    """
    if sandbox_workdir is not None:
        cmd = _sandbox_agent_command(cmd, sandbox_workdir, sandbox_name)

    if capture_output:
        if stdout is not None or stderr is not None:
            raise ValueError("stdout/stderr arguments may not be used with capture_output")
        stdout = subprocess.PIPE
        stderr = subprocess.PIPE

    proc = subprocess.Popen(
        list(cmd),
        stdin=subprocess.PIPE if input is not None else None,
        stdout=stdout,
        stderr=stderr,
        cwd=cwd,
        text=text,
        env=env,
        preexec_fn=_configure_child_process if os.name == "posix" else None,
    )
    pgid = proc.pid
    _remember_process_group(pgid)
    try:
        try:
            out, err = proc.communicate(input=input, timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            terminate_process_group(pgid)
            try:
                out, err = proc.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(pgid, signal.SIGKILL)
                except OSError:
                    pass
                out, err = proc.communicate()
            exc.output = out
            exc.stderr = err
            raise exc
        return subprocess.CompletedProcess(
            args=list(cmd),
            returncode=proc.returncode,
            stdout=out,
            stderr=err,
        )
    finally:
        _forget_process_group(pgid)
