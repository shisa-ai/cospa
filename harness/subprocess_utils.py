"""Subprocess helpers for eval tools that spawn their own child trees."""

from __future__ import annotations

import atexit
import ctypes
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import tempfile
import threading
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


_ACTIVE_PROCESS_GROUPS: set[int] = set()
_ACTIVE_LOCK = threading.Lock()
_TERMINATION_CALLBACKS: set[Callable[[int], None]] = set()
_TERMINATION_CALLBACKS_LOCK = threading.Lock()
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_NVM_ROOT = Path.home() / ".local" / "share" / "nvm"


def agent_sandbox_cwd(
    workdir: str | os.PathLike[str], task_name: str | None = None
) -> Path:
    """Return the stable virtual cwd used for one isolated trial."""
    digest = hashlib.sha256(str(Path(workdir).resolve()).encode()).hexdigest()[:16]
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "-", task_name or "workspace")
    safe_name = safe_name.strip(".-") or "workspace"
    return Path("/mnt") / f"cospa-{digest}" / safe_name


def resolve_model_base_url(model_id: str) -> str | None:
    """Resolve a provider-prefixed model id to pi's configured base URL."""
    if "/" not in model_id:
        return None
    provider_name, _ = model_id.split("/", 1)
    models_path = Path.home() / ".pi" / "agent" / "models.json"
    try:
        data = json.loads(models_path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    providers = data.get("providers", data) if isinstance(data, dict) else {}
    provider = providers.get(provider_name) if isinstance(providers, dict) else None
    if not isinstance(provider, dict):
        return None
    value = provider.get("baseUrl") or provider.get("base_url")
    return str(value) if value else None


def _wire_model_ref(model_id: str | None, models_path=None) -> str | None:
    """Alias-aware provider/wire-id reference for pi's --model argument.

    pi exact-matches --model against models.json; alias (quant-variant)
    benchmark ids would leak raw to the router. Resolves through the
    provider entry's aliases to its wire id.
    """
    if not model_id or "/" not in model_id:
        return model_id
    from harness.adapters.sampling import _find_pi_model

    path = models_path or (
        Path.home() / ".pi" / "agent" / "models.json"
    )
    entry = _find_pi_model(str(model_id), Path(path))
    if entry and entry.get("id"):
        provider, _, _ = str(model_id).partition("/")
        return f"{provider}/{entry['id']}"
    return model_id


def _command_model_id(cmd: Sequence[str]) -> str | None:
    values = list(cmd)
    try:
        index = values.index("--model")
    except ValueError:
        return None
    return str(values[index + 1]) if index + 1 < len(values) else None


def _command_session_dir(cmd: Sequence[str]) -> Path | None:
    """Return an absolute explicit pi session directory, when requested."""
    values = list(cmd)
    try:
        index = values.index("--session-dir")
    except ValueError:
        return None
    if index + 1 >= len(values):
        return None
    path = Path(str(values[index + 1])).expanduser()
    return path.resolve() if path.is_absolute() else None


def _write_private_agent_config(agent_dir: Path, model_id: str | None) -> None:
    """Create the smallest pi config needed by one selected model."""
    source_dir = Path.home() / ".pi" / "agent"
    agent_dir.mkdir(parents=True, exist_ok=True)
    for dirname in ("extensions", "git", "npm", "sessions"):
        (agent_dir / dirname).mkdir()

    settings_path = source_dir / "settings.json"
    if settings_path.exists():
        (agent_dir / "settings.json").write_bytes(settings_path.read_bytes())

    models_path = source_dir / "models.json"
    try:
        data = json.loads(models_path.read_text())
    except (OSError, json.JSONDecodeError):
        data = {}
    providers = data.get("providers", data) if isinstance(data, dict) else {}
    selected: dict[str, Any] = {}
    if model_id and "/" in model_id and isinstance(providers, dict):
        provider_name, provider_model = model_id.split("/", 1)
        provider = providers.get(provider_name)
        if isinstance(provider, dict):
            provider = dict(provider)
            matching_models = []
            for item in provider.get("models", []):
                candidate = (
                    item.get("id") or item.get("name")
                    if isinstance(item, dict)
                    else item
                )
                if candidate in {model_id, provider_model}:
                    matching_models.append(item)
            if matching_models:
                provider["models"] = matching_models
            selected[provider_name] = provider
    (agent_dir / "models.json").write_text(
        json.dumps({"providers": selected}, indent=2) + "\n"
    )


def _append_dir_options(options: list[str], paths: Sequence[Path]) -> None:
    """Create destination paths in an otherwise-empty bubblewrap root."""
    existing = {
        Path(options[index + 1])
        for index, value in enumerate(options[:-1])
        if value == "--dir"
    }
    for path in paths:
        chain = [parent for parent in reversed(path.parents) if parent != Path("/")]
        chain.append(path)
        for item in chain:
            if item not in existing:
                options.extend(["--dir", str(item)])
                existing.add(item)


def _nvm_version_root() -> Path | None:
    pi_executable = shutil.which("pi")
    if not pi_executable:
        return None
    resolved = Path(pi_executable).resolve()
    return next(
        (parent for parent in resolved.parents if parent.parent == _NVM_ROOT),
        None,
    )


def _sandbox_agent_command(
    cmd: Sequence[str],
    workdir: str | os.PathLike[str],
    sandbox_root: Path,
    relay_socket: Path | None,
    model_url: str | None,
    task_name: str | None = None,
) -> list[str]:
    """Build a filesystem-allowlisted command with optional model access."""
    workdir = Path(workdir).resolve()
    sandbox_cwd = agent_sandbox_cwd(workdir, task_name)
    sandbox_parent = sandbox_cwd.parent
    pi_home = Path.home() / ".pi"
    sessions_root = pi_home / "agent" / "sessions"
    encoded_cwd = str(sandbox_cwd).strip("/").replace("/", "-")
    trial_session_dir = sessions_root / f"--{encoded_cwd}--"
    explicit_session_dir = _command_session_dir(cmd)
    endpoint = urlparse(model_url) if model_url else None
    if endpoint and (
        endpoint.scheme not in {"http", "https"} or not endpoint.hostname
    ):
        raise ValueError(f"Unsupported model base URL for sandbox: {model_url}")
    endpoint_port = (
        endpoint.port or (443 if endpoint.scheme == "https" else 80)
        if endpoint
        else None
    )
    if endpoint:
        is_ipv4 = re.fullmatch(r"\d+(?:\.\d+){3}", endpoint.hostname)
        if is_ipv4 and endpoint.hostname not in {"127.0.0.1", "0.0.0.0"}:
            raise ValueError(
                "Hermetic sandbox requires a hostname or loopback model URL; "
                f"got IP literal {endpoint.hostname}"
            )
    hosts_file = sandbox_root / "hosts"
    hosts_lines = ["127.0.0.1 localhost", "::1 localhost"]
    if endpoint and endpoint.hostname not in {
        "127.0.0.1",
        "localhost",
        "0.0.0.0",
    }:
        hosts_lines.append(f"127.0.0.1 {endpoint.hostname}")
    hosts_file.write_text("\n".join(hosts_lines) + "\n")

    wrapped = [
        "bwrap",
        "--die-with-parent",
        "--unshare-pid",
        "--unshare-net",
    ]

    # System runtime and language toolchains. No repository or general home
    # directory is mounted into the namespace.
    _append_dir_options(wrapped, [Path("/usr"), Path("/etc"), Path("/opt")])
    wrapped.extend(["--ro-bind", "/usr", "/usr"])
    for link, target in (
        ("bin", "usr/bin"),
        ("sbin", "usr/bin"),
        ("lib", "usr/lib"),
        ("lib64", "usr/lib"),
    ):
        wrapped.extend(["--symlink", target, f"/{link}"])
    if Path("/opt/miniforge").is_dir():
        wrapped.extend(["--ro-bind", "/opt/miniforge", "/opt/miniforge"])
    for etc_path in (
        Path("/etc/ca-certificates"),
        Path("/etc/ssl"),
        Path("/etc/ld.so.cache"),
        Path("/etc/nsswitch.conf"),
        Path("/etc/passwd"),
        Path("/etc/group"),
        Path("/etc/localtime"),
        Path("/etc/os-release"),
    ):
        if etc_path.exists():
            wrapped.extend(["--ro-bind", str(etc_path), str(etc_path)])
    wrapped.extend(["--ro-bind", str(hosts_file), "/etc/hosts"])

    nvm_version = _nvm_version_root()
    if nvm_version:
        _append_dir_options(wrapped, [nvm_version])
        wrapped.extend(["--ro-bind", str(nvm_version), str(nvm_version)])

    if endpoint:
        persisted_session_dir = explicit_session_dir or trial_session_dir
        persisted_session_dir.mkdir(parents=True, exist_ok=True)
        private_agent = sandbox_root / "agent"
        _write_private_agent_config(private_agent, _command_model_id(cmd))

        # A private pi config contains only the selected provider. Installed
        # devstack package trees are read-only, and only this trial's session
        # path is persisted back to the host for telemetry.
        _append_dir_options(wrapped, [pi_home, pi_home / "agent"])
        wrapped.extend(["--bind", str(private_agent), str(pi_home / "agent")])
        source_agent = Path.home() / ".pi" / "agent"
        for dirname in ("extensions", "git", "npm"):
            source = source_agent / dirname
            if source.is_dir():
                wrapped.extend(
                    ["--ro-bind", str(source), str(pi_home / "agent" / dirname)]
                )
        if explicit_session_dir is None:
            wrapped.extend(
                [
                    "--bind",
                    str(trial_session_dir),
                    str(pi_home / "agent" / "sessions" / trial_session_dir.name),
                ]
            )

    cache_dir = Path.home() / ".cache"
    _append_dir_options(wrapped, [cache_dir])
    camoufox_cache = cache_dir / "camoufox"
    if camoufox_cache.is_dir():
        _append_dir_options(wrapped, [camoufox_cache])
        wrapped.extend(
            [
                "--overlay-src",
                str(camoufox_cache),
                "--tmp-overlay",
                str(camoufox_cache),
            ]
        )
    for dependency_cache in (
        Path.home() / ".npm",
        Path.home() / ".gradle",
        Path.home() / ".cargo" / "registry",
        Path.home() / ".cargo" / "git",
    ):
        if dependency_cache.is_dir():
            _append_dir_options(wrapped, [dependency_cache])
            wrapped.extend(
                [
                    "--overlay-src",
                    str(dependency_cache),
                    "--tmp-overlay",
                    str(dependency_cache),
                ]
            )

    # Superpowers adapters may name individual repository-backed skill paths.
    # Mount only those selected directories, never the harness or repository.
    for value in cmd:
        path = Path(str(value))
        if (
            path.is_absolute()
            and path.exists()
            and _PROJECT_ROOT in path.parents
            and workdir not in path.parents
        ):
            # Explicit extensions are files while skill paths are directories.
            # Creating a directory at a file mountpoint makes bwrap reject the
            # subsequent bind with "Is a directory".
            _append_dir_options(
                wrapped,
                [path if path.is_dir() else path.parent],
            )
            wrapped.extend(["--ro-bind", str(path), str(path)])

    _append_dir_options(
        wrapped,
        [Path("/run"), Path("/tmp"), Path("/mnt"), sandbox_parent, sandbox_cwd],
    )
    wrapped.extend(
        [
            "--proc",
            "/proc",
            "--dev",
            "/dev",
            "--tmpfs",
            "/tmp",
            "--tmpfs",
            "/run",
        ]
    )
    if explicit_session_dir is not None and not (
        explicit_session_dir == workdir or workdir in explicit_session_dir.parents
    ):
        _append_dir_options(wrapped, [explicit_session_dir])
        wrapped.extend(
            ["--bind", str(explicit_session_dir), str(explicit_session_dir)]
        )
    wrapped.extend(
        [
            "--bind",
            str(workdir),
            str(sandbox_cwd),
            "--chdir",
            str(sandbox_cwd),
        ]
    )
    if endpoint:
        if relay_socket is None or endpoint_port is None:
            raise ValueError("Model sandbox requires a relay socket")
        bridge_script = (
            f"socat TCP-LISTEN:{endpoint_port},bind=127.0.0.1,reuseaddr,fork "
            "UNIX-CONNECT:/run/cospa-model.sock & bridge=$!; "
            "trap 'kill $bridge 2>/dev/null || true; "
            "wait $bridge 2>/dev/null || true' EXIT HUP INT TERM; "
            '"$@"'
        )
        wrapped.extend(
            [
                "--ro-bind",
                str(relay_socket),
                "/run/cospa-model.sock",
                "/bin/bash",
                "-c",
                bridge_script,
                "cospa-model-bridge",
                *cmd,
            ]
        )
    else:
        wrapped.extend(cmd)
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


def register_termination_callback(callback: Callable[[int], None]) -> None:
    """Register a best-effort state flush before signal termination."""
    with _TERMINATION_CALLBACKS_LOCK:
        _TERMINATION_CALLBACKS.add(callback)


def unregister_termination_callback(callback: Callable[[int], None]) -> None:
    """Remove a previously registered termination callback."""
    with _TERMINATION_CALLBACKS_LOCK:
        _TERMINATION_CALLBACKS.discard(callback)


def notify_termination_callbacks(signum: int) -> None:
    """Invoke registered state flushes without blocking later cleanup."""
    with _TERMINATION_CALLBACKS_LOCK:
        callbacks = list(_TERMINATION_CALLBACKS)
    for callback in callbacks:
        try:
            callback(signum)
        except Exception:
            pass


atexit.register(terminate_active_process_groups)


def _start_model_relay(model_url: str, socket_path: Path) -> subprocess.Popen:
    """Forward one Unix socket to the selected model host and port."""
    endpoint = urlparse(model_url)
    if endpoint.scheme not in {"http", "https"} or not endpoint.hostname:
        raise ValueError(f"Unsupported model base URL for sandbox: {model_url}")
    port = endpoint.port or (443 if endpoint.scheme == "https" else 80)
    relay = subprocess.Popen(
        [
            "/usr/bin/socat",
            f"UNIX-LISTEN:{socket_path},fork",
            f"TCP:{endpoint.hostname}:{port},connect-timeout=10",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    _remember_process_group(relay.pid)
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        if socket_path.exists():
            return relay
        if relay.poll() is not None:
            break
        time.sleep(0.02)
    _forget_process_group(relay.pid)
    if relay.poll() is None:
        terminate_process_group(relay.pid)
        relay.wait(timeout=2)
    raise RuntimeError(f"Could not start model-only relay for {model_url}")


def _stop_model_relay(relay: subprocess.Popen | None) -> None:
    if relay is None:
        return
    try:
        if relay.poll() is None:
            terminate_process_group(relay.pid)
            try:
                relay.wait(timeout=2)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(relay.pid, signal.SIGKILL)
                except OSError:
                    pass
                relay.wait(timeout=2)
    finally:
        _forget_process_group(relay.pid)


def _termination_signal_handler(signum, frame) -> None:
    notify_termination_callbacks(signum)
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
    sandbox_model_url: str | None = None,
    sandbox_model_access: bool = True,
) -> subprocess.CompletedProcess:
    """Run a command in its own process group and clean up on timeout.

    Python's `subprocess.run(..., timeout=...)` only guarantees cleanup of the
    immediate child. Eval adapters launch tools that launch package managers,
    browsers, compilers, and test binaries; those must be terminated as one
    process group when a trial times out or the runner exits cleanly.
    """
    sandbox_tmp: tempfile.TemporaryDirectory | None = None
    relay: subprocess.Popen | None = None
    if sandbox_workdir is not None:
        model_url = None
        if sandbox_model_access:
            model_id = _command_model_id(cmd)
            if model_id:
                resolved_ref = _wire_model_ref(model_id)
                if resolved_ref != model_id:
                    values = list(cmd)
                    values[values.index("--model") + 1] = resolved_ref
                    cmd = values
            model_url = sandbox_model_url or (
                resolve_model_base_url(model_id) if model_id else None
            )
            if not model_url:
                raise RuntimeError(
                    "Agent sandbox requires the selected model's base URL"
                )
        sandbox_tmp = tempfile.TemporaryDirectory(prefix="cospa-sandbox-")
        sandbox_root = Path(sandbox_tmp.name)
        relay_socket = sandbox_root / "model.sock"
        try:
            if model_url:
                relay = _start_model_relay(model_url, relay_socket)
            cmd = _sandbox_agent_command(
                cmd,
                sandbox_workdir,
                sandbox_root,
                relay_socket if model_url else None,
                model_url,
                sandbox_name,
            )
        except Exception:
            _stop_model_relay(relay)
            sandbox_tmp.cleanup()
            raise

    if capture_output:
        if stdout is not None or stderr is not None:
            raise ValueError("stdout/stderr arguments may not be used with capture_output")
        stdout = subprocess.PIPE
        stderr = subprocess.PIPE

    try:
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
    except Exception:
        _stop_model_relay(relay)
        if sandbox_tmp is not None:
            sandbox_tmp.cleanup()
        raise
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
        _stop_model_relay(relay)
        if sandbox_tmp is not None:
            sandbox_tmp.cleanup()
