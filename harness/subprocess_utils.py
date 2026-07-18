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
_FNM_NODE_VERSIONS_ROOT = (
    Path.home() / ".local" / "share" / "fnm" / "node-versions"
)
_HEADLESS_TUI_PACKAGE_SOURCES = frozenset(
    {
        "https://github.com/lhl/pi-zentui",
        "git:github.com/lhl/pi-zentui",
        "../../github/lhl/pi-zentui",
    }
)
_HEADLESS_TUI_EXTENSION_NAMES = frozenset({"pi-zentui"})


def _headless_extension_paths(extensions_dir: Path) -> list[Path]:
    """Return direct extensions that are safe and relevant in print mode."""
    return sorted(
        (
            path
            for path in extensions_dir.iterdir()
            if path.name not in _HEADLESS_TUI_EXTENSION_NAMES
        ),
        key=lambda path: path.name,
    )


def _headless_agent_settings(settings: dict[str, Any]) -> dict[str, Any]:
    """Disable TUI-only extensions in Pi's print-mode sandbox profile."""
    filtered = dict(settings)
    packages = settings.get("packages")
    if not isinstance(packages, list):
        return filtered

    filtered_packages: list[Any] = []
    for entry in packages:
        source = entry if isinstance(entry, str) else None
        if isinstance(entry, dict) and isinstance(entry.get("source"), str):
            source = entry["source"]
        if source not in _HEADLESS_TUI_PACKAGE_SOURCES:
            filtered_packages.append(entry)
            continue
        package = {"source": source} if isinstance(entry, str) else dict(entry)
        package["extensions"] = []
        filtered_packages.append(package)
    filtered["packages"] = filtered_packages
    return filtered


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
        try:
            settings = json.loads(settings_path.read_text())
        except (OSError, json.JSONDecodeError):
            (agent_dir / "settings.json").write_bytes(settings_path.read_bytes())
        else:
            if isinstance(settings, dict):
                settings = _headless_agent_settings(settings)
            (agent_dir / "settings.json").write_text(
                json.dumps(settings, indent=2) + "\n"
            )

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


def _java_external_config_roots() -> list[Path]:
    """Return /etc roots referenced by the selected JDK's conf symlink."""
    java_executable = shutil.which("java")
    if not java_executable:
        return []
    java_home = Path(java_executable).resolve().parent.parent
    conf_path = java_home / "conf"
    if not conf_path.is_symlink():
        return []
    target = conf_path.resolve()
    etc_root = Path("/etc")
    if target == etc_root or etc_root not in target.parents:
        return []
    return [target]


def _node_installation_root() -> Path | None:
    """Return the selected NVM/FNM Node installation mounted for adapters."""
    node_executable = shutil.which("node")
    if not node_executable:
        return None
    resolved = Path(node_executable).resolve()
    if resolved.parent.name != "bin":
        return None
    installation = resolved.parent.parent
    allowed_roots = (_NVM_ROOT, _FNM_NODE_VERSIONS_ROOT)
    if not any(
        installation == root or root in installation.parents
        for root in allowed_roots
    ):
        return None
    return installation


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
    cmd = [str(value) for value in cmd]
    sandbox_cwd = agent_sandbox_cwd(workdir, task_name)
    sandbox_parent = sandbox_cwd.parent
    session_dir: Path | None = None
    sandbox_session_dir: Path | None = None
    if "--session-dir" in cmd:
        option_index = cmd.index("--session-dir")
        if option_index + 1 >= len(cmd):
            raise ValueError("--session-dir requires a path")
        session_dir = Path(cmd[option_index + 1]).resolve()
        try:
            session_dir.relative_to(workdir.parent)
        except ValueError as exc:
            raise ValueError(
                "Sandbox session directory must stay within the trial root: "
                f"{session_dir}"
            ) from exc
        session_dir.mkdir(parents=True, exist_ok=True)
        sandbox_session_dir = sandbox_parent / "pi-sessions"
        cmd[option_index + 1] = str(sandbox_session_dir)
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
    for java_config_root in _java_external_config_roots():
        _append_dir_options(wrapped, [java_config_root])
        wrapped.extend(
            [
                "--ro-bind",
                str(java_config_root),
                str(java_config_root),
            ]
        )

    node_installation = _node_installation_root()
    if node_installation:
        _append_dir_options(wrapped, [node_installation])
        node_bin = str(node_installation / "bin")
        selected_node = shutil.which("node")
        selected_bin = str(Path(selected_node).parent) if selected_node else None
        path_entries = os.environ.get("PATH", "").split(os.pathsep)
        sandbox_path = [
            node_bin if selected_bin and entry == selected_bin else entry
            for entry in path_entries
        ]
        if node_bin not in sandbox_path:
            sandbox_path.append(node_bin)
        wrapped.extend(
            [
                "--ro-bind",
                str(node_installation),
                str(node_installation),
                "--setenv",
                "PATH",
                os.pathsep.join(sandbox_path),
            ]
        )

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
        extensions_dir = source_agent / "extensions"
        if extensions_dir.is_dir():
            for source in _headless_extension_paths(extensions_dir):
                private_target = private_agent / "extensions" / source.name
                if source.is_dir():
                    private_target.mkdir()
                else:
                    private_target.touch()
                wrapped.extend(
                    [
                        "--ro-bind",
                        str(source),
                        str(pi_home / "agent" / "extensions" / source.name),
                    ]
                )
        for dirname in ("git", "npm"):
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
    # Mount only explicit --skill values, never arbitrary absolute arguments.
    for index, value in enumerate(cmd[:-1]):
        if value != "--skill":
            continue
        path = Path(cmd[index + 1])
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

    sandbox_dirs = [
        Path("/run"),
        Path("/tmp"),
        Path("/mnt"),
        sandbox_parent,
        sandbox_cwd,
    ]
    if sandbox_session_dir is not None:
        sandbox_dirs.append(sandbox_session_dir)
    _append_dir_options(wrapped, sandbox_dirs)
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
        ]
    )
    if session_dir is not None and sandbox_session_dir is not None:
        wrapped.extend(
            ["--bind", str(session_dir), str(sandbox_session_dir)]
        )
    wrapped.extend(["--chdir", str(sandbox_cwd)])
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
