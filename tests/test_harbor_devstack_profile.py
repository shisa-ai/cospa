import importlib
import json
import os
import subprocess
import sys
import types


def _import_harbor_agents(monkeypatch):
    terminal_bench = types.ModuleType("terminal_bench")
    agents = types.ModuleType("terminal_bench.agents")
    installed_agents = types.ModuleType("terminal_bench.agents.installed_agents")
    abstract_mod = types.ModuleType(
        "terminal_bench.agents.installed_agents.abstract_installed_agent"
    )
    terminal = types.ModuleType("terminal_bench.terminal")
    models_mod = types.ModuleType("terminal_bench.terminal.models")

    class FakeAbstractInstalledAgent:
        pass

    class FakeTerminalCommand:
        pass

    abstract_mod.AbstractInstalledAgent = FakeAbstractInstalledAgent
    models_mod.TerminalCommand = FakeTerminalCommand
    modules = {
        "terminal_bench": terminal_bench,
        "terminal_bench.agents": agents,
        "terminal_bench.agents.installed_agents": installed_agents,
        "terminal_bench.agents.installed_agents.abstract_installed_agent": abstract_mod,
        "terminal_bench.terminal": terminal,
        "terminal_bench.terminal.models": models_mod,
    }
    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)
    sys.modules.pop("harness.harbor_agents", None)
    return importlib.import_module("harness.harbor_agents")


def test_headless_profile_removes_packages_that_install_or_load_native_code(
    monkeypatch, tmp_path
):
    harbor_agents = _import_harbor_agents(monkeypatch)
    agent_dir = tmp_path / ".pi" / "agent"
    agent_dir.mkdir(parents=True)
    settings_path = agent_dir / "settings.json"
    settings_path.write_text(json.dumps({
        "defaultProvider": "codex",
        "packages": [
            "npm:pi-context-prune",
            "npm:pi-smart-fetch",
            {
                "source": "npm:@the-forge-flow/camoufox-pi@0.2.1",
                "extensions": [],
            },
            "https://github.com/lhl/pi-zentui",
        ],
    }))

    sanitizer = getattr(
        harbor_agents, "_devstack_settings_sanitizer_command"
    )()
    env = os.environ.copy()
    env["HOME"] = str(tmp_path)
    subprocess.run(
        ["bash", "-lc", sanitizer],
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )

    sanitized = json.loads(settings_path.read_text())
    assert sanitized["defaultProvider"] == "codex"
    assert sanitized["packages"] == ["npm:pi-context-prune"]


def test_profile_is_sanitized_before_pi_package_discovery(monkeypatch):
    harbor_agents = _import_harbor_agents(monkeypatch)
    command = harbor_agents._devstack_profile_install_command()
    assert command.index("COSPA_HEADLESS_EXCLUDED_PACKAGES") < command.index(
        "pi list"
    )
