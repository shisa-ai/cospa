"""
Tests for the Superpowers ablation adapters (pi_superpowers,
little_coder_superpowers).

The plan (P14) says these adapters must strip interactive skill-check flows
and load only the pinned, headless-safe debugging/TDD/verification profile.
The previous implementation just loaded the ENTIRE ~/.pi/agent/skills
directory, which (a) is the user's personal skills, not the bench subset,
and (b) includes arbitrary interactive flows.

These tests pin the intended behavior:
  - --no-skills is set (strip default discovery)
  - only the checksum-verified repo-local profile is loaded via --skill
  - interactive skills (e.g. `check`, `realitycheck`) are NOT loaded
"""

import asyncio
import importlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import types
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from harness.adapters.pi_superpowers import PiSuperpowersAdapter
from harness.adapters.little_coder_superpowers import LittleCoderSuperpowersAdapter
from harness.adapters import load_adapter
from harness.runner import run_trial


# Skills that are interactive (require a human in the loop) and must be
# stripped from the bench ablation.
INTERACTIVE_SKILLS = {"check", "realitycheck", "shisa-kb"}

# Skills that are part of the Superpowers bench subset.
BENCH_SKILLS = {
    "systematic-debugging",
    "test-driven-development",
    "verification-before-completion",
}
PINNED_SUPERPOWERS_REVISION = "b36e0829c6d0140e93cfef2ca599b1b07d4a7797"


def _load_skills_through_pi(skill_paths, tmp_path):
    """Return Pi's real resource inventory and resulting session prompt."""
    pi_executable = shutil.which("pi")
    assert pi_executable, "pi must be installed for the Superpowers qualification"
    pi_module = Path(pi_executable).resolve().with_name("index.js")
    assert pi_module.is_file(), f"could not locate Pi SDK beside {pi_executable}"

    agent_dir = tmp_path / "empty-agent"
    agent_dir.mkdir(exist_ok=True)
    script = r"""
const {
  createAgentSession,
  DefaultResourceLoader,
  SessionManager,
  SettingsManager,
} = await import(process.env.COSPA_PI_MODULE);

const settings = SettingsManager.inMemory();
const loader = new DefaultResourceLoader({
  cwd: process.env.COSPA_CWD,
  agentDir: process.env.COSPA_AGENT_DIR,
  settingsManager: settings,
  additionalSkillPaths: JSON.parse(process.env.COSPA_SKILL_PATHS),
  noExtensions: true,
  noSkills: true,
  noPromptTemplates: true,
  noThemes: true,
  noContextFiles: true,
});
await loader.reload();
const model = {
  provider: "cospa-test",
  id: "resource-probe",
  name: "Resource probe",
  api: "openai-completions",
  baseUrl: "http://127.0.0.1:1/v1",
  reasoning: false,
  input: ["text"],
  contextWindow: 8192,
  maxTokens: 1024,
  cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
};
const { session } = await createAgentSession({
  cwd: process.env.COSPA_CWD,
  agentDir: process.env.COSPA_AGENT_DIR,
  model,
  resourceLoader: loader,
  settingsManager: settings,
  sessionManager: SessionManager.inMemory(process.env.COSPA_CWD),
});
const inventory = loader.getSkills();
console.log(JSON.stringify({
  skills: inventory.skills.map((skill) => ({
    name: skill.name,
    description: skill.description,
    filePath: skill.filePath,
  })),
  diagnostics: inventory.diagnostics,
  systemPrompt: session.agent.state.systemPrompt,
}));
session.dispose();
"""
    env = os.environ.copy()
    env.update(
        {
            "PI_OFFLINE": "1",
            "COSPA_PI_MODULE": pi_module.as_uri(),
            "COSPA_CWD": str(tmp_path),
            "COSPA_AGENT_DIR": str(agent_dir),
            "COSPA_SKILL_PATHS": json.dumps([str(Path(path)) for path in skill_paths]),
        }
    )
    result = subprocess.run(
        ["node", "--input-type=module", "--eval", script],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    return json.loads(result.stdout)


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

    with patch(f"{adapter.__class__.__module__}.run_command", side_effect=fake_run):
        adapter.run(task_data, workdir, log_file, stderr_file)
    return captured["cmd"]


def _skill_paths_in_cmd(cmd) -> list:
    """Extract the paths passed to --skill in a command list."""
    paths = []
    for i, c in enumerate(cmd):
        if c in ("--skill",) and i + 1 < len(cmd):
            paths.append(cmd[i + 1])
    return paths


def test_pinned_superpowers_profile_reaches_pi_system_prompt(tmp_path):
    """Removing valid frontmatter or a selected skill must fail qualification."""
    skill_root = PROJECT_ROOT / "harness" / "bench_skills"
    inventory = _load_skills_through_pi(
        [skill_root / name for name in sorted(BENCH_SKILLS)],
        tmp_path,
    )

    assert {skill["name"] for skill in inventory["skills"]} == BENCH_SKILLS
    assert inventory["diagnostics"] == []
    for name in BENCH_SKILLS:
        assert f"<name>{name}</name>" in inventory["systemPrompt"]


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


def _import_harbor_agents_with_fake_native_harbor(monkeypatch):
    """Import the modern Harbor branch without installing Harbor."""
    for name in list(sys.modules):
        if name == "harness.harbor_agents" or name.startswith("harbor"):
            monkeypatch.delitem(sys.modules, name, raising=False)

    class FakeBaseInstalledAgent:
        def __init__(self, model_name, *args, **kwargs):
            self.model_name = model_name
            self.root_commands = []
            self.agent_commands = []

        def version(self):
            return None

        async def exec_as_root(self, environment, *, command, env=None):
            self.root_commands.append(command)

        async def exec_as_agent(self, environment, *, command, env=None):
            self.agent_commands.append(command)

    for name in (
        "harbor",
        "harbor.agents",
        "harbor.agents.installed",
        "harbor.environments",
        "harbor.models",
        "harbor.models.agent",
    ):
        monkeypatch.setitem(sys.modules, name, types.ModuleType(name))

    base_mod = types.ModuleType("harbor.agents.installed.base")
    base_mod.BaseInstalledAgent = FakeBaseInstalledAgent
    environment_mod = types.ModuleType("harbor.environments.base")
    environment_mod.BaseEnvironment = object
    context_mod = types.ModuleType("harbor.models.agent.context")
    context_mod.AgentContext = object
    monkeypatch.setitem(sys.modules, "harbor.agents.installed.base", base_mod)
    monkeypatch.setitem(sys.modules, "harbor.environments.base", environment_mod)
    monkeypatch.setitem(sys.modules, "harbor.models.agent.context", context_mod)

    return importlib.import_module("harness.harbor_agents")


def test_harbor_materializes_same_loadable_superpowers_profile(monkeypatch, tmp_path):
    """Container setup must produce the same three real, Pi-loadable skills."""
    harbor_agents = _import_harbor_agents_with_fake_native_harbor(monkeypatch)
    agent = harbor_agents.PiSuperpowersHarborAgent("test/model")
    asyncio.run(agent.install(object()))

    skill_command = agent.root_commands[-1]
    host_destination = tmp_path / "bench-skills"
    materialize_command = skill_command.replace(
        "/installed-agent/bench-skills", str(host_destination)
    )
    subprocess.run(["bash", "-c", materialize_command], check=True)
    inventory = _load_skills_through_pi(
        [host_destination / name for name in sorted(BENCH_SKILLS)],
        tmp_path,
    )

    assert {skill["name"] for skill in inventory["skills"]} == BENCH_SKILLS
    assert inventory["diagnostics"] == []
    for name in BENCH_SKILLS:
        assert f"<name>{name}</name>" in inventory["systemPrompt"]


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


def test_superpowers_manifest_records_pinned_loaded_profile(tmp_path):
    """Changing or omitting the capability treatment must change the manifest."""

    class ManifestSuite:
        name = "manifest_probe"
        version = "test"

        def materialize_task(self, task_id, workdir, vendor_dir):
            return {"prompt": "Inspect the workspace.", "problem": task_id}

        def verify(self, task_data, workdir):
            return {"passed": True, "test_count": 1, "exit_code": 0}

    completed = subprocess.CompletedProcess(args=[], returncode=0)
    with (
        patch("harness.adapters.pi_superpowers.run_command", return_value=completed),
        patch("harness.runner.load_model_metadata", return_value={}),
    ):
        manifest, _ = run_trial(
            ManifestSuite(),
            PiSuperpowersAdapter(),
            "test/model",
            "probe",
            1,
            tmp_path / "results",
            tmp_path / "vendor",
        )

    profile = manifest["adapter"]["capability_profile"]
    assert profile["id"] == "superpowers-bench-v1"
    assert profile["source"]["revision"] == PINNED_SUPERPOWERS_REVISION
    assert {skill["name"] for skill in profile["skills"]} == BENCH_SKILLS
    assert all(len(skill["sha256"]) == 64 for skill in profile["skills"])
