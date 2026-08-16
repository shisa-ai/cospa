import signal
import shlex
import subprocess
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import Mock

import pytest

from harness import subprocess_utils


class _OkHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, format, *args):
        return


@contextmanager
def _http_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _OkHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address[1]
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


def test_run_command_timeout_kills_process_group(monkeypatch):
    """Timeout cleanup must target the whole process group, not one child."""
    proc = Mock()
    proc.pid = 12345
    proc.returncode = None
    proc.communicate.side_effect = [
        subprocess.TimeoutExpired(["fake"], 1),
        ("", "timed out"),
    ]
    proc.wait.return_value = None

    popen = Mock(return_value=proc)
    killpg = Mock()
    monkeypatch.setattr(subprocess_utils.subprocess, "Popen", popen)
    monkeypatch.setattr(subprocess_utils.os, "killpg", killpg)

    with pytest.raises(subprocess.TimeoutExpired):
        subprocess_utils.run_command(["fake"], timeout=1, text=True)

    popen.assert_called_once()
    assert popen.call_args.kwargs["preexec_fn"] is not None
    killpg.assert_called_with(12345, signal.SIGTERM)


def test_agent_sandbox_hides_shared_data_and_writes_trial(tmp_path):
    """The real sandbox exposes only the trial and selected model endpoint."""
    sandbox_cwd = subprocess_utils.agent_sandbox_cwd(tmp_path, "all-your-base")
    sessions_root = Path.home() / ".pi" / "agent" / "sessions"
    prior_session = sessions_root / f"cospa-leak-probe-{tmp_path.name}"
    prior_session.mkdir(parents=True)
    encoded_cwd = str(sandbox_cwd).strip("/").replace("/", "-")
    trial_session = sessions_root / f"--{encoded_cwd}--"
    project_root = Path(__file__).resolve().parents[1]
    pi_overlay_probe = Path.home() / ".pi" / f"cospa-overlay-{tmp_path.name}"
    with _http_server() as allowed_port, _http_server() as blocked_port:
        result = subprocess_utils.run_command(
            [
                "/bin/bash",
                "-c",
                (
                    f"test ! -e {shlex.quote(str(project_root / 'README.md'))} && "
                    "test ! -e /home/lhl/sm120-tuning/BONSAI.md && "
                    f"test \"$PWD\" = {shlex.quote(str(sandbox_cwd))} && "
                    f"test ! -e {shlex.quote(str(prior_session))} && "
                    f"touch {shlex.quote(str(trial_session / 'sandbox-session-write'))} && "
                    f"touch {shlex.quote(str(pi_overlay_probe))} && "
                    f"curl -fsS http://127.0.0.1:{allowed_port}/health >/dev/null && "
                    f"! curl -fsS --max-time 1 http://127.0.0.1:{blocked_port}/health >/dev/null 2>&1 && "
                    "cache_probe=$HOME/.cache/cospa-sandbox-write-$$ && "
                    "touch \"$cache_probe\" && rm \"$cache_probe\" && "
                    "touch /tmp/cospa-sandbox-temp && "
                    "touch sandbox-write"
                ),
            ],
            sandbox_workdir=tmp_path,
            sandbox_name="all-your-base",
            sandbox_model_url=f"http://127.0.0.1:{allowed_port}/v1",
        )
    prior_session.rmdir()
    (trial_session / "sandbox-session-write").unlink(missing_ok=True)
    trial_session.rmdir()

    assert result.returncode == 0
    assert not pi_overlay_probe.exists()
    assert sandbox_cwd.name == "all-your-base"
    assert (tmp_path / "sandbox-write").exists()


def test_agent_sandbox_persists_explicit_session_dir(tmp_path):
    """An adapter's --session-dir must survive the empty-root sandbox."""
    workdir = tmp_path / "workdir"
    workdir.mkdir()
    session_dir = tmp_path / "out" / "pi-sessions"
    session_file = session_dir / "session.jsonl"

    with _http_server() as allowed_port:
        result = subprocess_utils.run_command(
            [
                "/bin/bash",
                "-c",
                f"touch {shlex.quote(str(session_file))}",
                "--session-dir",
                str(session_dir),
            ],
            sandbox_workdir=workdir,
            sandbox_name="all-your-base",
            sandbox_model_url=f"http://127.0.0.1:{allowed_port}/v1",
        )

    assert result.returncode == 0
    assert session_file.exists()


def test_agent_sandbox_mounts_only_declared_adapter_state_paths(tmp_path):
    """Adapter-private config/state must persist without exposing sibling data."""
    workdir = tmp_path / "workdir"
    workdir.mkdir()
    readonly = tmp_path / "readonly-profile"
    readonly.mkdir()
    (readonly / "profile.txt").write_text("pinned\n")
    writable = tmp_path / "adapter-state"
    writable.mkdir()
    hidden = tmp_path / "must-stay-hidden"
    hidden.mkdir()
    (hidden / "secret.txt").write_text("hidden\n")

    result = subprocess_utils.run_command(
        [
            "/bin/bash",
            "-c",
            (
                f"test \"$(cat {shlex.quote(str(readonly / 'profile.txt'))})\" = pinned && "
                f"! touch {shlex.quote(str(readonly / 'forbidden'))} 2>/dev/null && "
                f"printf persisted > {shlex.quote(str(writable / 'state.txt'))} && "
                f"test ! -e {shlex.quote(str(hidden / 'secret.txt'))}"
            ),
        ],
        cwd=workdir,
        sandbox_workdir=workdir,
        sandbox_name="adapter-state",
        sandbox_model_access=False,
        sandbox_readonly_paths=[readonly],
        sandbox_writable_paths=[writable],
    )

    assert result.returncode == 0
    assert (writable / "state.txt").read_text() == "persisted"
    assert not (readonly / "forbidden").exists()


def test_verifier_sandbox_has_no_model_or_public_network(tmp_path):
    """Model-written code executed by a verifier stays hermetically isolated."""
    project_root = Path(__file__).resolve().parents[1]
    with _http_server() as blocked_port:
        result = subprocess_utils.run_command(
            [
                "/bin/bash",
                "-c",
                (
                    f"test ! -e {shlex.quote(str(project_root / 'README.md'))} && "
                    f"! curl -fsS --max-time 1 http://127.0.0.1:{blocked_port}/ "
                    ">/dev/null 2>&1 && "
                    "touch verifier-write"
                ),
            ],
            sandbox_workdir=tmp_path,
            sandbox_name="verifier",
            sandbox_model_access=False,
        )

    assert result.returncode == 0
    assert (tmp_path / "verifier-write").exists()
