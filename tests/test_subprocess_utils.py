import signal
import shlex
import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest

from harness import subprocess_utils


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
    """The real bubblewrap boundary must hide vendor/results, not just look right."""
    sandbox_cwd = subprocess_utils.agent_sandbox_cwd(tmp_path, "all-your-base")
    sessions_root = Path.home() / ".pi" / "agent" / "sessions"
    prior_session = sessions_root / f"cospa-leak-probe-{tmp_path.name}"
    prior_session.mkdir(parents=True)
    encoded_cwd = str(sandbox_cwd).strip("/").replace("/", "-")
    trial_session = sessions_root / f"--{encoded_cwd}--"
    project_root = Path(__file__).resolve().parents[1]
    pi_overlay_probe = Path.home() / ".pi" / f"cospa-overlay-{tmp_path.name}"
    result = subprocess_utils.run_command(
        [
            "/bin/bash",
            "-c",
            (
                f"test -z \"$(find {shlex.quote(str(project_root / 'vendor'))} -mindepth 1 "
                "-print -quit)\" && "
                f"test -z \"$(find {shlex.quote(str(project_root / 'results'))} -mindepth 1 "
                "-print -quit)\" && "
                f"test \"$PWD\" = {shlex.quote(str(sandbox_cwd))} && "
                f"test ! -e {shlex.quote(str(prior_session))} && "
                f"touch {shlex.quote(str(trial_session / 'sandbox-session-write'))} && "
                f"touch {shlex.quote(str(pi_overlay_probe))} && "
                "cache_probe=$HOME/.cache/cospa-sandbox-write-$$ && "
                "touch \"$cache_probe\" && rm \"$cache_probe\" && "
                "touch /tmp/cospa-sandbox-temp && "
                "touch sandbox-write"
            ),
        ],
        sandbox_workdir=tmp_path,
        sandbox_name="all-your-base",
    )
    prior_session.rmdir()
    (trial_session / "sandbox-session-write").unlink(missing_ok=True)
    trial_session.rmdir()

    assert result.returncode == 0
    assert not pi_overlay_probe.exists()
    assert sandbox_cwd.name == "all-your-base"
    assert (tmp_path / "sandbox-write").exists()
