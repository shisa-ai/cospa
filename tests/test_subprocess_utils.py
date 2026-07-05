import signal
import subprocess
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
