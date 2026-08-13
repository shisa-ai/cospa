"""
Tests that every benchmark adapter prepends the no-network hint to the task
prompt.

The eval sandbox has no network and hides reference files (e.g. hidden test
files). Without the hint, devstack-style agents (which have web/search tools)
burn their whole per-trial budget trying to fetch hidden files online. This
invariant locks the hint into every adapter so no scaffold silently drops it.
"""

import sys
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from harness.adapters import ADAPTERS
from harness.adapters import session_utils
from harness.adapters.session_utils import NO_NETWORK_HINT, with_no_network_hint
from harness.adapters.pi_vanilla import PiVanillaAdapter
from harness.adapters.pi_devstack import PiDevstackAdapter
from harness.adapters.pi_devstack_superpowers import PiDevstackSuperpowersAdapter
from harness.adapters.little_coder import LittleCoderAdapter
from harness.adapters.pi_superpowers import PiSuperpowersAdapter
from harness.adapters.little_coder_superpowers import LittleCoderSuperpowersAdapter

# Adapter modules bind ``run_command`` into their own namespace at import, so we
# patch each module's attribute rather than harness.subprocess_utils.
_ADAPTER_MODULES = {
    "pi_vanilla": PiVanillaAdapter.__module__,
    "pi_devstack": PiDevstackAdapter.__module__,
    "pi_devstack_superpowers": PiDevstackSuperpowersAdapter.__module__,
    "little_coder": LittleCoderAdapter.__module__,
    "pi_superpowers": PiSuperpowersAdapter.__module__,
    "little_coder_superpowers": LittleCoderSuperpowersAdapter.__module__,
}


class _FakeResult:
    returncode = 0


def _capture_prompt(adapter_name: str, prompt: str = "Write a solution."):
    """Run the named adapter, capturing the prompt it passes to the agent."""
    adapter = ADAPTERS[adapter_name]()
    captured = {}

    def fake_run_command(cmd, **kwargs):
        captured["input"] = kwargs.get("input", "")
        captured["cmd"] = cmd
        return _FakeResult()

    with patch(_ADAPTER_MODULES[adapter_name] + ".run_command", side_effect=fake_run_command):
        adapter.run(
            task_data={
                "prompt": prompt,
                "model_id": "local/muse-glimmer-30b",
                "problem": "allergies",
            },
            workdir=Path("/tmp/nonexistent-workdir"),
            log_file=Path("/tmp/nonexistent.log"),
            stderr_file=Path("/tmp/nonexistent.err"),
        )
    return captured["input"], captured["cmd"]


def test_with_no_network_hint_prepends_by_default():
    out = with_no_network_hint("Solve the task.")
    assert out.startswith(NO_NETWORK_HINT)
    assert "Solve the task." in out
    # original task text must survive verbatim after the hint
    assert out.endswith("Solve the task.")


def test_with_no_network_hint_handles_empty_prompt():
    assert with_no_network_hint("") == ""
    assert with_no_network_hint("", at_top=False) == ""


def test_with_no_network_hint_can_append_at_bottom():
    out = with_no_network_hint("Solve it.", at_top=False)
    assert out.startswith("Solve it.")
    assert out.endswith(NO_NETWORK_HINT)


def test_every_adapter_prepends_no_network_hint():
    """Every registered adapter must pass the hint to the agent on every run."""
    assert ADAPTERS, "adapter registry must not be empty"
    for name in ADAPTERS:
        sent, cmd = _capture_prompt(name)
        assert NO_NETWORK_HINT in sent, (
            f"adapter {name} did not include the no-network hint in its prompt"
        )
        # hint must be at the very top so the agent reads it before exploring
        assert sent.startswith(NO_NETWORK_HINT), (
            f"adapter {name} did not prepend the hint (prompt starts: {sent[:60]!r})"
        )
        # and the original task prompt must still be present
        assert "Write a solution." in sent


def test_every_adapter_preserves_original_task_text():
    """The hint must not clobber the real problem statement."""
    for name in ADAPTERS:
        sent, _ = _capture_prompt(name)
        assert sent.count("Write a solution.") == 1
        # exactly one hint line
        assert sent.count(NO_NETWORK_HINT) == 1
