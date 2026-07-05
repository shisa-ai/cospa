"""Subprocess helpers for eval tools that spawn their own child trees."""

from __future__ import annotations

import atexit
import ctypes
import os
import signal
import subprocess
import threading
from collections.abc import Sequence
from typing import Any


_ACTIVE_PROCESS_GROUPS: set[int] = set()
_ACTIVE_LOCK = threading.Lock()


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
) -> subprocess.CompletedProcess:
    """Run a command in its own process group and clean up on timeout.

    Python's `subprocess.run(..., timeout=...)` only guarantees cleanup of the
    immediate child. Eval adapters launch tools that launch package managers,
    browsers, compilers, and test binaries; those must be terminated as one
    process group when a trial times out or the runner exits cleanly.
    """
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
