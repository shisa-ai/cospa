"""
Tests for the Superpowers ablation adapters (pi_superpowers,
little_coder_superpowers).

The plan (P14) says these adapters must strip interactive skill-check flows
and keep only systematic-debugging + verification-before-completion skills.
The previous implementation just loaded the ENTIRE ~/.pi/agent/skills
directory, which (a) is the user's personal skills, not the bench subset,
and (b) includes arbitrary interactive flows.

These tests pin the intended behavior:
  - --no-skills is set (strip default discovery)
  - only a configured allowlist of bench-appropriate skills is loaded via --skill
  - interactive skills (e.g. `check`, `realitycheck`) are NOT loaded
"""

import sys
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from harness.adapters.pi_superpowers import PiSuperpowersAdapter
from harness.adapters.little_coder_superpowers import LittleCoderSuperpowersAdapter
from harness.adapters import load_adapter


# Skills that are interactive (require a human in the loop) and must be
# stripped from the bench ablation.
INTERACTIVE_SKILLS = {"check", "realitycheck", "shisa-kb"}

# Skills that are part of the Superpowers bench subset.
BENCH_SKILLS = {"systematic-debugging", "verification-before-completion"}


def _run_adapter(adapter, tmp_path):
    task_data = {"model_id": "test/model", "prompt": "test"}
    workdir = tmp_path / "workdir"
    workdir.mkdir()
    log_file = tmp_path / "log.txt"
    stderr_file = tmp_path / "stderr.txt"
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = list(cmd)
        captured["kwargs"] = kwargs
        import subprocess as sp
        return sp.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    with patch("subprocess.run", side_effect=fake_run):
        adapter.run(task_data, workdir, log_file, stderr_file)
    return captured["cmd"]


def _skill_paths_in_cmd(cmd) -> list:
    """Extract the paths passed to --skill in a command list."""
    paths = []
    for i, c in enumerate(cmd):
        if c in ("--skill",) and i + 1 < len(cmd):
            paths.append(cmd[i + 1])
    return paths


def test_pi_superpowers_strips_default_skills():
    """pi_superpowers must use --no-skills (strip default discovery)."""
    adapter = PiSuperpowersAdapter()
    with tempfile.TemporaryDirectory() as tmp:
        cmd = _run_adapter(adapter, Path(tmp))
    assert "--no-skills" in cmd, f"missing --no-skills in {cmd}"


def test_pi_superpowers_does_not_load_entire_user_skills_dir():
    """pi_superpowers must NOT pass the entire ~/.pi/agent/skills directory.

    It must filter to a known bench subset. Loading the whole directory
    brings in arbitrary interactive user skills (review finding #8).
    """
    adapter = PiSuperpowersAdapter()
    with tempfile.TemporaryDirectory() as tmp:
        cmd = _run_adapter(adapter, Path(tmp))
    skill_paths = _skill_paths_in_cmd(cmd)
    user_skills_dir = str(Path.home() / ".pi" / "agent" / "skills")
    for p in skill_paths:
        # No --skill path may BE or END WITH the bare user skills dir
        assert not p.endswith(".pi/agent/skills"), (
            f"must not load entire user skills dir, got {p}"
        )
        assert p != user_skills_dir, f"must not load entire user skills dir: {p}"


def test_pi_superpowers_does_not_load_interactive_skills():
    """No --skill path may point at a known interactive skill."""
    adapter = PiSuperpowersAdapter()
    with tempfile.TemporaryDirectory() as tmp:
        cmd = _run_adapter(adapter, Path(tmp))
    skill_paths = _skill_paths_in_cmd(cmd)
    for p in skill_paths:
        basename = Path(p).name
        assert basename not in INTERACTIVE_SKILLS, (
            f"interactive skill '{basename}' must not be loaded: {p}"
        )


def test_little_coder_superpowers_strips_default_skills():
    """little_coder_superpowers must use --no-skills."""
    adapter = LittleCoderSuperpowersAdapter()
    with tempfile.TemporaryDirectory() as tmp:
        cmd = _run_adapter(adapter, Path(tmp))
    assert "--no-skills" in cmd, f"missing --no-skills in {cmd}"


def test_little_coder_superpowers_does_not_load_entire_user_skills_dir():
    adapter = LittleCoderSuperpowersAdapter()
    with tempfile.TemporaryDirectory() as tmp:
        cmd = _run_adapter(adapter, Path(tmp))
    skill_paths = _skill_paths_in_cmd(cmd)
    for p in skill_paths:
        assert not p.endswith(".pi/agent/skills"), (
            f"must not load entire user skills dir, got {p}"
        )


def test_pi_devstack_superpowers_preserves_extensions_and_filters_skills():
    """pi_devstack_superpowers keeps devstack extensions but filters skills."""
    adapter = load_adapter("pi_devstack_superpowers")
    with tempfile.TemporaryDirectory() as tmp:
        cmd = _run_adapter(adapter, Path(tmp))

    assert "--no-extensions" not in cmd, (
        f"devstack superpowers must preserve normal extension discovery: {cmd}"
    )
    assert "--no-skills" in cmd, (
        f"devstack superpowers must strip default skill discovery: {cmd}"
    )
    skill_paths = _skill_paths_in_cmd(cmd)
    assert skill_paths, f"expected allowlisted bench skills in {cmd}"
    for p in skill_paths:
        basename = Path(p).name
        assert basename in BENCH_SKILLS, f"unexpected skill {basename}: {cmd}"
