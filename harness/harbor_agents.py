"""Custom Harbor agents for the coding-eval adapter matrix.

Harbor accepts custom agents as ``module:ClassName`` import paths. These
classes keep Terminal-Bench aligned with the same scaffold variants used by
the generic runner instead of collapsing several labels onto Harbor's built-in
agents.
"""

from __future__ import annotations

import json
import os
import shlex
import sys
from pathlib import Path
from typing import Any

from harness.skill_profiles import (
    superpowers_container_skill_paths,
    superpowers_install_command,
)


try:
    from harbor.agents.installed.base import BaseInstalledAgent
    from harbor.environments.base import BaseEnvironment
    from harbor.models.agent.context import AgentContext

    _HARBOR_NATIVE = True
except ModuleNotFoundError:
    _HARBOR_NATIVE = False

if not _HARBOR_NATIVE:
    try:
        from terminal_bench.agents.installed_agents.abstract_installed_agent import (
            AbstractInstalledAgent,
        )
        from terminal_bench.terminal.models import TerminalCommand
    except ModuleNotFoundError:
        # Unit tests run in the coding-eval mamba env, which does not install the
        # terminal_bench package. Use the vendored checkout for importability there.
        PROJECT_ROOT = Path(__file__).resolve().parent.parent
        vendored_tb = PROJECT_ROOT / "vendor" / "terminal-bench"
        if vendored_tb.exists():
            sys.path.insert(0, str(vendored_tb))
        from terminal_bench.agents.installed_agents.abstract_installed_agent import (
            AbstractInstalledAgent,
        )
        from terminal_bench.terminal.models import TerminalCommand


_CODING_EVAL_AGENT_ENV_KEYS = (
    "CODING_EVAL_LOCAL_BASE_URL",
    "CODING_EVAL_LOCAL_API_KEY",
    "CODING_EVAL_PI_PROVIDER_NAME",
    "CODING_EVAL_PI_PROVIDER_BASE_URL",
    "CODING_EVAL_PI_PROVIDER_API_KEY",
    "CODING_EVAL_PI_PROVIDER_API",
    "CODING_EVAL_PI_PROVIDER_MODEL_ID",
    "CODING_EVAL_PI_PROVIDER_MODEL_NAME",
    "CODING_EVAL_PI_SAMPLING_PARAMS",
    "CODING_EVAL_PI_CONTEXT_WINDOW",
    "CODING_EVAL_PI_MAX_TOKENS",
    "CODING_EVAL_PI_THINKING_LEVEL_MAP",
    "CODING_EVAL_PI_COMPAT",
    "CODING_EVAL_THINKING",
    "CODING_EVAL_REASONING_EFFORT",
    "CODING_EVAL_CLEAN_AGENT_PROCESSES",
)

_CONTAINER_BENCH_SKILLS = superpowers_container_skill_paths()

_PI_RUNTIME_DIR = "/opt/coding-eval-pi-runtime"
_COMPAT_NODE_DIR = "/opt/coding-eval-node-compat"
_RUNTIME_ACTIVATION_INLINE = (
    f'if [[ -x "{_PI_RUNTIME_DIR}/bin/pi" ]] '
    f'&& "{_PI_RUNTIME_DIR}/bin/node" --version >/dev/null 2>&1; then '
    f'export PATH="{_PI_RUNTIME_DIR}/bin:$PATH"; '
    f'elif [[ -x "{_PI_RUNTIME_DIR}/bin/pi" ]] '
    f'&& "{_COMPAT_NODE_DIR}/bin/node" --version >/dev/null 2>&1; then '
    f'export PATH="{_COMPAT_NODE_DIR}/bin:{_PI_RUNTIME_DIR}/bin:$PATH"; '
    'else . "${NVM_DIR:-$HOME/.nvm}/nvm.sh"; nvm use 22 >/dev/null; fi'
)

_RUNTIME_DEPENDENCY_INSTALL_COMMAND = rf"""
set -e
if [[ -x "{_PI_RUNTIME_DIR}/bin/pi" ]] \
   && ("{_PI_RUNTIME_DIR}/bin/node" --version >/dev/null 2>&1 \
       || "{_COMPAT_NODE_DIR}/bin/node" --version >/dev/null 2>&1); then
    exit 0
elif command -v curl >/dev/null 2>&1; then
    exit 0
elif command -v apt-get >/dev/null 2>&1; then
    export DEBIAN_FRONTEND=noninteractive
    apt-get update
    apt-get install -y curl ca-certificates
elif command -v dnf >/dev/null 2>&1; then
    dnf install -y curl ca-certificates
elif command -v microdnf >/dev/null 2>&1; then
    microdnf install -y curl ca-certificates
elif command -v yum >/dev/null 2>&1; then
    yum install -y curl ca-certificates
elif command -v apk >/dev/null 2>&1; then
    apk add --no-cache curl ca-certificates
else
    echo "Unable to install curl: no supported package manager" >&2
    exit 1
fi
""".strip()


def _resolve_pi_model_arg(
    model_name: str | None, provider_env: dict | None = None
) -> str | None:
    """Substitute provider/resolved-wire-id for pi's --model when the env
    carries a resolved MODEL_ID for the same provider.

    Containers bake a one-model models.json from
    CODING_EVAL_PI_PROVIDER_MODEL_ID; pi's --model must land on that exact
    id or pi sends the raw benchmark id upstream (alias/quant labels like
    local/qwen3.8-27b-fp8-block would otherwise 400 at the router).
    """
    if not model_name:
        return model_name
    env = provider_env if provider_env is not None else os.environ
    provider_name = env.get("CODING_EVAL_PI_PROVIDER_NAME")
    model_id_env = env.get("CODING_EVAL_PI_PROVIDER_MODEL_ID")
    if not provider_name or not model_id_env:
        return model_name
    if model_name.split("/", 1)[0] != provider_name:
        return model_name
    return f"{provider_name}/{model_id_env}"


_PROCESS_SNAPSHOT_COMMAND = (
    "for process in /proc/[0-9]*; do "
    "printf '%s\\n' \"${process##*/}\"; "
    "done"
)


def _new_process_cleanup_command(baseline_pids: set[int]) -> str:
    """Return a root cleanup command for processes created by one agent run.

    Harbor uploads hidden tests into the shared task container only after the
    solving phase. A model can otherwise leave a watcher daemon behind and read
    or mutate those tests. Preserve the pre-agent container processes and the
    cleanup exec's own ancestor chain, then kill everything else in repeated
    passes so newly forked children cannot race the cleanup.
    """
    baseline = " " + " ".join(str(pid) for pid in sorted(baseline_pids)) + " "
    return rf'''
baseline={shlex.quote(baseline)}
keep="$baseline"
pid=$$
while [[ "$pid" =~ ^[0-9]+$ ]] && (( pid > 1 )); do
  keep="$keep $pid "
  pid=$(awk '/^PPid:/ {{ print $2 }}' "/proc/$pid/status" 2>/dev/null || echo 0)
done
for pass in 1 2 3; do
  for process in /proc/[0-9]*; do
    pid=${{process##*/}}
    (( pid > 1 )) || continue
    case "$keep" in
      *" $pid "*) ;;
      *) kill -KILL "$pid" 2>/dev/null || true ;;
    esac
  done
  sleep 0.05
done
'''.strip()


def _configured_thinking() -> str | None:
    thinking = (
        os.environ.get("CODING_EVAL_THINKING")
        or os.environ.get("CODING_EVAL_REASONING_EFFORT")
    )
    if not thinking or thinking == "default":
        return None
    return thinking


def _thinking_args() -> list[str]:
    thinking = _configured_thinking()
    return ["--thinking", thinking] if thinking else []


_HEADLESS_EXCLUDED_PACKAGE_FRAGMENTS = (
    "npm:pi-smart-fetch",
    "npm:@the-forge-flow/camoufox-pi",
    "github.com/lhl/pi-zentui",
)


def _devstack_settings_sanitizer_command() -> str:
    """Remove packages that cannot initialize portably in headless images."""
    excluded = json.dumps(_HEADLESS_EXCLUDED_PACKAGE_FRAGMENTS)
    command = r'''node <<'NODE'
const fs = require('fs');
const path = require('path');
const settingsPath = path.join(process.env.HOME, '.pi', 'agent', 'settings.json');
const COSPA_HEADLESS_EXCLUDED_PACKAGES = __COSPA_EXCLUDED_PACKAGES__;
const settings = JSON.parse(fs.readFileSync(settingsPath, 'utf8'));
const packages = Array.isArray(settings.packages) ? settings.packages : [];
settings.packages = packages.filter((entry) => {
  const source = typeof entry === 'string' ? entry : entry?.source;
  return typeof source !== 'string' || !COSPA_HEADLESS_EXCLUDED_PACKAGES.some(
    (fragment) => source.includes(fragment),
  );
});
fs.writeFileSync(settingsPath, JSON.stringify(settings, null, 2) + '\n');
NODE'''
    return command.replace("__COSPA_EXCLUDED_PACKAGES__", excluded)


def _devstack_profile_install_command() -> str:
    """Install the read-only devstack package snapshot into the agent home."""
    command = r'''
set -euo pipefail
profile_root=/opt/coding-eval-devstack
agent_dir="$HOME/.pi/agent"
test -d "$profile_root/npm"
test -d "$profile_root/git"
test -f "$profile_root/settings.json"
mkdir -p "$agent_dir"
rm -rf "$agent_dir/npm" "$agent_dir/git"
ln -s "$profile_root/npm" "$agent_dir/npm"
ln -s "$profile_root/git" "$agent_dir/git"
cp "$profile_root/settings.json" "$agent_dir/settings.json"
__COSPA_RUNTIME_ACTIVATION__
__COSPA_SETTINGS_SANITIZER__
pi list
'''.strip()
    return command.replace(
        "__COSPA_RUNTIME_ACTIVATION__", _RUNTIME_ACTIVATION_INLINE
    ).replace(
        "__COSPA_SETTINGS_SANITIZER__",
        _devstack_settings_sanitizer_command(),
    )


def _wrap_with_pi_session_export(
    run_command: str,
    *,
    output_filename: str | None = None,
) -> str:
    """Run an agent command and export pi JSONL sessions as Harbor artifacts."""
    if output_filename:
        log_path = shlex.quote(f"/logs/agent/{output_filename}")
        run_lines = [
            f"{run_command} 2>&1 </dev/null | tee {log_path}",
            "agent_status=${PIPESTATUS[0]}",
        ]
    else:
        run_lines = [
            run_command,
            "agent_status=$?",
        ]

    script = "\n".join([
        "set -o pipefail",
        "agent_status=0",
        *run_lines,
        "export_dir=/logs/artifacts/pi-sessions",
        "sessions_root=\"$HOME/.pi/agent/sessions\"",
        "mkdir -p \"$export_dir\"",
        "if [[ -d \"$sessions_root\" ]]; then",
        "  find \"$sessions_root\" -type f -name '*.jsonl' -print0 | while IFS= read -r -d '' session_file; do",
        "    rel=\"${session_file#${sessions_root}/}\"",
        "    safe_rel=\"${rel//\\//__}\"",
        "    cp \"$session_file\" \"$export_dir/$safe_rel\"",
        "  done",
        "fi",
        "exit \"$agent_status\"",
    ])
    return f"bash -lc {shlex.quote(script)}"


if _HARBOR_NATIVE:

    class _BasePiCliHarborAgent(BaseInstalledAgent):
        cli_command = "pi"
        npm_package = "@earendil-works/pi-coding-agent"
        extra_args: tuple[str, ...] = ()
        include_bench_skills = False
        include_devstack_profile = False
        _agent_name = "coding-eval-pi"
        _output_filename = "coding-eval-agent.txt"

        @staticmethod
        def name() -> str:
            return _BasePiCliHarborAgent._agent_name

        def _provider_env(self) -> dict[str, str]:
            return {
                key: value
                for key in _CODING_EVAL_AGENT_ENV_KEYS
                if (value := os.environ.get(key))
            }

        async def _write_local_pi_config(self, environment: BaseEnvironment) -> None:
            env = self._provider_env()
            if not (
                env.get("CODING_EVAL_PI_PROVIDER_BASE_URL")
                or env.get("CODING_EVAL_LOCAL_BASE_URL")
            ):
                return

            command = r"""
mkdir -p "$HOME/.pi/agent"
__COSPA_RUNTIME_ACTIVATION__
node <<'NODE'
const fs = require('fs');
const os = require('os');
const path = require('path');
const dir = path.join(os.homedir(), '.pi', 'agent');
const providerName = process.env.CODING_EVAL_PI_PROVIDER_NAME || 'local';
const baseUrl = (
  process.env.CODING_EVAL_PI_PROVIDER_BASE_URL ||
  process.env.CODING_EVAL_LOCAL_BASE_URL
);
const apiKey = (
  process.env.CODING_EVAL_PI_PROVIDER_API_KEY ||
  process.env.CODING_EVAL_LOCAL_API_KEY ||
  'EMPTY'
);
const api = process.env.CODING_EVAL_PI_PROVIDER_API || 'openai-completions';
const modelId = process.env.CODING_EVAL_PI_PROVIDER_MODEL_ID || 'ornith-1.0-35b';
const modelName = process.env.CODING_EVAL_PI_PROVIDER_MODEL_NAME || modelId;
const contextWindow = Number(process.env.CODING_EVAL_PI_CONTEXT_WINDOW || 262144);
const maxTokens = Number(process.env.CODING_EVAL_PI_MAX_TOKENS || 81920);
function parseJsonEnv(name) {
  try {
    return JSON.parse(process.env[name] || '{}');
  } catch (error) {
    throw new Error(`Invalid ${name}: ${error.message}`);
  }
}
const samplingParams = parseJsonEnv('CODING_EVAL_PI_SAMPLING_PARAMS');
const thinkingLevelMap = parseJsonEnv('CODING_EVAL_PI_THINKING_LEVEL_MAP');
const compat = parseJsonEnv('CODING_EVAL_PI_COMPAT');
const models = [
  {
    id: modelId,
    name: modelName,
    reasoning: true,
    input: ['text'],
    contextWindow,
    maxTokens,
    samplingParams,
    thinkingLevelMap,
    compat,
    cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 }
  }
];
if (providerName === 'local') {
  for (const alias of ['ornith-1.0-35b', 'Ornith-1.0-35B']) {
    if (!models.some((model) => model.id === alias)) {
      models.push({
        id: alias,
        name: 'Ornith 1.0 35B',
        reasoning: true,
        input: ['text'],
        contextWindow,
        maxTokens,
        samplingParams,
        thinkingLevelMap,
        compat,
        cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 }
      });
    }
  }
}
const cfg = {
  providers: {
    [providerName]: { baseUrl, apiKey, api, models }
  }
};
fs.mkdirSync(dir, { recursive: true });
fs.writeFileSync(path.join(dir, 'models.json'), JSON.stringify(cfg, null, 2));
NODE
""".replace("__COSPA_RUNTIME_ACTIVATION__", _RUNTIME_ACTIVATION_INLINE)
            await self.exec_as_agent(environment, command=command, env=env)

        async def _install_devstack_profile(
            self,
            environment: BaseEnvironment,
        ) -> None:
            if not self.include_devstack_profile:
                return
            await self.exec_as_agent(
                environment,
                command=_devstack_profile_install_command(),
            )

        async def _install_bench_skills(self, environment: BaseEnvironment) -> None:
            if not self.include_bench_skills:
                return
            await self.exec_as_root(
                environment,
                command=superpowers_install_command(),
            )

        async def install(self, environment: BaseEnvironment) -> None:
            await self.exec_as_root(
                environment,
                command=_RUNTIME_DEPENDENCY_INSTALL_COMMAND,
            )
            version = self.version() or "latest"
            package = self.npm_package
            if version != "latest":
                package = f"{package}@{version}"
            await self.exec_as_agent(
                environment,
                command=(
                    "set -euo pipefail; "
                    "nvm_dir=\"${NVM_DIR:-$HOME/.nvm}\"; "
                    "export NVM_DIR=\"$nvm_dir\"; "
                    f"if [[ -x \"{_PI_RUNTIME_DIR}/bin/{self.cli_command}\" ]] "
                    f"&& \"{_PI_RUNTIME_DIR}/bin/node\" --version >/dev/null 2>&1; then "
                    f"export PATH=\"{_PI_RUNTIME_DIR}/bin:$PATH\"; "
                    f"elif [[ -x \"{_PI_RUNTIME_DIR}/bin/{self.cli_command}\" ]] "
                    f"&& \"{_COMPAT_NODE_DIR}/bin/node\" --version >/dev/null 2>&1; then "
                    f"export PATH=\"{_COMPAT_NODE_DIR}/bin:{_PI_RUNTIME_DIR}/bin:$PATH\"; "
                    "else "
                    "if [[ ! -f \"$nvm_dir/nvm.sh\" ]]; then "
                    "curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.2/install.sh | bash; "
                    "fi; "
                    ". \"$nvm_dir/nvm.sh\"; "
                    "nvm install 22; "
                    "nvm alias default 22; "
                    f"if ! command -v {shlex.quote(self.cli_command)} >/dev/null 2>&1; then "
                    f"npm install -g {shlex.quote(package)}; "
                    "fi; "
                    "fi; "
                    f"{shlex.quote(self.cli_command)} --version"
                ),
            )
            await self._install_devstack_profile(environment)
            await self._install_bench_skills(environment)
            await self._write_local_pi_config(environment)

        async def run(
            self,
            instruction: str,
            environment: BaseEnvironment,
            context: AgentContext,
        ) -> None:
            if not self.model_name:
                raise ValueError("model_name is required")
            cmd = [
                self.cli_command,
                "--print",
                *self.extra_args,
                "--model",
                _resolve_pi_model_arg(self.model_name, self._provider_env()),
                *_thinking_args(),
                instruction,
            ]
            clean_agent_processes = (
                os.environ.get("CODING_EVAL_CLEAN_AGENT_PROCESSES") == "1"
            )
            baseline_pids: set[int] = set()
            if clean_agent_processes:
                snapshot = await self.exec_as_root(
                    environment,
                    command=_PROCESS_SNAPSHOT_COMMAND,
                )
                baseline_pids = {
                    int(line)
                    for line in (snapshot.stdout or "").splitlines()
                    if line.strip().isdigit()
                }
                if not baseline_pids:
                    raise RuntimeError("Could not snapshot pre-agent processes")
            try:
                await self.exec_as_agent(
                    environment,
                    command=_wrap_with_pi_session_export(
                        f"{_RUNTIME_ACTIVATION_INLINE}; {shlex.join(cmd)}",
                        output_filename=self._output_filename,
                    ),
                    env=self._provider_env(),
                )
            finally:
                if baseline_pids:
                    await self.exec_as_root(
                        environment,
                        command=_new_process_cleanup_command(baseline_pids),
                    )


else:

    class _BasePiCliHarborAgent(AbstractInstalledAgent):
        cli_command = "pi"
        npm_package = "@earendil-works/pi-coding-agent"
        extra_args: tuple[str, ...] = ()
        include_bench_skills = False
        include_devstack_profile = False
        _agent_name = "coding-eval-pi"

        @staticmethod
        def name() -> str:
            return _BasePiCliHarborAgent._agent_name

        def __init__(self, model_name: str, *args: Any, **kwargs: Any):
            super().__init__(*args, **kwargs)
            self._model_name = model_name
            self._version = kwargs.get("version", "latest")

        @property
        def _env(self) -> dict[str, str]:
            return {
                key: value
                for key in _CODING_EVAL_AGENT_ENV_KEYS
                if (value := os.environ.get(key))
            }

        @property
        def _install_agent_script_path(self) -> Path:
            return self._get_templated_script_path("harbor-agent-setup.sh.j2")

        def _get_template_variables(self) -> dict[str, str]:
            return {
                "version": self.version or "latest",
                "cli_command": self.cli_command,
                "npm_package": self.npm_package,
                "include_bench_skills": self.include_bench_skills,
                "bench_skills_install_command": (
                    superpowers_install_command() if self.include_bench_skills else ""
                ),
                "include_devstack_profile": self.include_devstack_profile,
            }

        def _run_agent_commands(self, instruction: str) -> list[TerminalCommand]:
            cmd = [
                self.cli_command,
                "--print",
                *self.extra_args,
                "--model",
                _resolve_pi_model_arg(self._model_name),
                *_thinking_args(),
                instruction,
            ]
            run_command = f"{_RUNTIME_ACTIVATION_INLINE}; {shlex.join(cmd)}"
            return [
                TerminalCommand(
                    command=_wrap_with_pi_session_export(run_command),
                    min_timeout_sec=0.0,
                    max_timeout_sec=float("inf"),
                    block=True,
                    append_enter=True,
                )
            ]


class PiVanillaHarborAgent(_BasePiCliHarborAgent):
    extra_args = ("--no-extensions",)
    _agent_name = "coding-eval-pi-vanilla"

    @staticmethod
    def name() -> str:
        return PiVanillaHarborAgent._agent_name


class PiDevstackHarborAgent(_BasePiCliHarborAgent):
    extra_args = ()
    include_devstack_profile = True
    _agent_name = "coding-eval-pi-devstack"

    @staticmethod
    def name() -> str:
        return PiDevstackHarborAgent._agent_name


class PiDevstackSuperpowersHarborAgent(_BasePiCliHarborAgent):
    include_devstack_profile = True
    extra_args = (
        "--no-skills",
        "--skill",
        _CONTAINER_BENCH_SKILLS[0],
        "--skill",
        _CONTAINER_BENCH_SKILLS[1],
        "--skill",
        _CONTAINER_BENCH_SKILLS[2],
    )
    include_bench_skills = True
    _agent_name = "coding-eval-pi-devstack-superpowers"

    @staticmethod
    def name() -> str:
        return PiDevstackSuperpowersHarborAgent._agent_name


class PiSuperpowersHarborAgent(_BasePiCliHarborAgent):
    extra_args = (
        "--no-extensions",
        "--no-skills",
        "--skill",
        _CONTAINER_BENCH_SKILLS[0],
        "--skill",
        _CONTAINER_BENCH_SKILLS[1],
        "--skill",
        _CONTAINER_BENCH_SKILLS[2],
    )
    include_bench_skills = True
    _agent_name = "coding-eval-pi-superpowers"

    @staticmethod
    def name() -> str:
        return PiSuperpowersHarborAgent._agent_name


class LittleCoderHarborAgent(_BasePiCliHarborAgent):
    cli_command = "little-coder"
    npm_package = "little-coder"
    extra_args = ()
    _agent_name = "coding-eval-little-coder"

    @staticmethod
    def name() -> str:
        return LittleCoderHarborAgent._agent_name


class LittleCoderSuperpowersHarborAgent(LittleCoderHarborAgent):
    extra_args = (
        "--no-skills",
        "--skill",
        _CONTAINER_BENCH_SKILLS[0],
        "--skill",
        _CONTAINER_BENCH_SKILLS[1],
        "--skill",
        _CONTAINER_BENCH_SKILLS[2],
    )
    include_bench_skills = True
    _agent_name = "coding-eval-little-coder-superpowers"

    @staticmethod
    def name() -> str:
        return LittleCoderSuperpowersHarborAgent._agent_name
