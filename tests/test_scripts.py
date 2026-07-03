"""
Pytest wrapper that runs the shell-script tests under tests/scripts/.

These cover check-models.sh and run-matrix.sh, which can't be exercised
cleanly from Python. The actual assertions live in the .sh files; this
module just invokes them and reports pass/fail to pytest.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent / "scripts"


def _run_shell_test(script: Path):
    result = subprocess.run(
        ["bash", str(script)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        msg = result.stdout + result.stderr
        pytest.fail(f"{script.name} failed:\n{msg}")


@pytest.mark.parametrize("script", sorted(SCRIPTS_DIR.glob("test_*.sh")))
def test_shell_script(script):
    """Run each tests/scripts/test_*.sh and assert it exits 0."""
    _run_shell_test(script)
