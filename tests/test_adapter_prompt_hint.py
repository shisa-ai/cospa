"""
Tests that every benchmark adapter prepends the no-network hint to the task
prompt.

The eval sandbox has no network and hides reference files (e.g. hidden test
files). Without the hint, devstack-style agents (which have web/search tools)
burn their whole per-trial budget trying to fetch hidden files online. This
invariant locks the hint into every adapter so no scaffold silently drops it.
"""

import json
import sys
import tempfile
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from harness.adapters import ADAPTERS, AGENTIC_ADAPTERS, PROTOCOL_ADAPTERS
from harness.adapters import session_utils
from harness.adapters.session_utils import NO_NETWORK_HINT, with_no_network_hint
from harness.adapters.pi_vanilla import PiVanillaAdapter
from harness.adapters.pi_devstack import PiDevstackAdapter
from harness.adapters.pi_devstack_superpowers import PiDevstackSuperpowersAdapter
from harness.adapters.little_coder import LittleCoderAdapter
from harness.adapters.pi_superpowers import PiSuperpowersAdapter
from harness.adapters.little_coder_superpowers import LittleCoderSuperpowersAdapter
from harness.adapters.opencode import (
    OpenCodeSuperpowersAdapter,
    OpenCodeVanillaAdapter,
)

# Adapter modules bind ``run_command`` into their own namespace at import, so we
# patch each module's attribute rather than harness.subprocess_utils.
_ADAPTER_MODULES = {
    "pi_vanilla": PiVanillaAdapter.__module__,
    "pi_devstack": PiDevstackAdapter.__module__,
    "pi_devstack_superpowers": PiDevstackSuperpowersAdapter.__module__,
    "little_coder": LittleCoderAdapter.__module__,
    "pi_superpowers": PiSuperpowersAdapter.__module__,
    "little_coder_superpowers": LittleCoderSuperpowersAdapter.__module__,
    "opencode_vanilla": OpenCodeVanillaAdapter.__module__,
    "opencode_superpowers": OpenCodeSuperpowersAdapter.__module__,
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
        if adapter_name.startswith("opencode_"):
            kwargs["stdout"].write(
                json.dumps(
                    {
                        "type": "step_finish",
                        "sessionID": "ses_test",
                        "part": {
                            "tokens": {"input": 1, "output": 1, "total": 2}
                        },
                    }
                )
                + "\n"
            )
            kwargs["stdout"].flush()
        return _FakeResult()

    task_data = {
        "prompt": prompt,
        "model_id": "local/muse-glimmer-30b",
        "problem": "allergies",
    }
    with tempfile.TemporaryDirectory() as temp_dir, ExitStack() as stack:
        root = Path(temp_dir)
        workdir = root / "work"
        out_dir = root / "out"
        workdir.mkdir()
        out_dir.mkdir()
        module = _ADAPTER_MODULES[adapter_name]
        stack.enter_context(patch(module + ".run_command", side_effect=fake_run_command))
        if adapter_name.startswith("opencode_"):
            base_url = "http://model.test:8000/v1"
            task_data.update(
                {
                    "model_base_url": base_url,
                    "context_window": 32768,
                    "max_tokens": 4096,
                    "reasoning": False,
                    "sampling_params": {},
                }
            )
            stack.enter_context(patch(module + ".validate_opencode_runtime"))
            stack.enter_context(
                patch(
                    module + ".load_opencode_connection",
                    return_value={
                        "base_url": base_url,
                        "api_key": "test",
                        "api": "openai-completions",
                        "model": "muse-glimmer-30b",
                    },
                )
            )
        adapter.run(
            task_data=task_data,
            workdir=workdir,
            log_file=out_dir / "session.log",
            stderr_file=out_dir / "stderr.log",
        )
    return captured["input"], captured["cmd"]


def test_no_network_hint_directs_solution_to_visible_task_context():
    assert (
        "Network access, hidden test files, and reference solutions are unavailable."
        in NO_NETWORK_HINT
    )
    assert (
        "Solve the task directly from the problem statement and visible workspace."
        in NO_NETWORK_HINT
    )


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
    assert AGENTIC_ADAPTERS, "agentic adapter registry must not be empty"
    for name in AGENTIC_ADAPTERS:
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
    for name in AGENTIC_ADAPTERS:
        sent, _ = _capture_prompt(name)
        assert sent.count("Write a solution.") == 1
        # exactly one hint line
        assert sent.count(NO_NETWORK_HINT) == 1


def test_every_adapter_emits_native_behavior_trace():
    """Each runtime must emit its qualified durable telemetry format."""
    for name, adapter_type in AGENTIC_ADAPTERS.items():
        _, cmd = _capture_prompt(name)
        adapter = adapter_type()
        if getattr(adapter, "uses_pi_session", True):
            assert "--extension" in cmd, f"adapter {name} omitted telemetry extension"
            path = Path(cmd[cmd.index("--extension") + 1])
            assert path.name == "behavior_trace_extension.ts"
            assert path.is_file()
        else:
            assert cmd[:2] == ["opencode", "run"]
            assert cmd[cmd.index("--format") + 1] == "json"


def test_protocol_adapters_are_separate_from_agent_scaffold_invariants():
    assert set(ADAPTERS) == set(AGENTIC_ADAPTERS) | set(PROTOCOL_ADAPTERS)
    assert set(AGENTIC_ADAPTERS).isdisjoint(PROTOCOL_ADAPTERS)
    assert set(PROTOCOL_ADAPTERS) == {"bigcodebench_openai"}
