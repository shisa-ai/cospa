"""Custom Harbor agents for the coding-eval adapter matrix.

Harbor accepts custom agents as ``module:ClassName`` import paths. These
classes keep Terminal-Bench aligned with the same scaffold variants used by
the generic runner instead of collapsing several labels onto Harbor's built-in
agents.
"""

from __future__ import annotations

import os
import shlex
import sys
from pathlib import Path
from typing import Any


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


_PROVIDER_ENV_KEYS = (
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_OAUTH_TOKEN",
    "OPENAI_API_KEY",
    "AZURE_OPENAI_API_KEY",
    "AZURE_OPENAI_BASE_URL",
    "AZURE_OPENAI_RESOURCE_NAME",
    "AZURE_OPENAI_API_VERSION",
    "AZURE_OPENAI_DEPLOYMENT_NAME_MAP",
    "DEEPSEEK_API_KEY",
    "NVIDIA_API_KEY",
    "GEMINI_API_KEY",
    "GROQ_API_KEY",
    "CEREBRAS_API_KEY",
    "XAI_API_KEY",
    "FIREWORKS_API_KEY",
    "TOGETHER_API_KEY",
    "OPENROUTER_API_KEY",
    "AI_GATEWAY_API_KEY",
    "ZAI_API_KEY",
    "ZAI_CODING_CN_API_KEY",
    "MISTRAL_API_KEY",
    "MINIMAX_API_KEY",
    "MOONSHOT_API_KEY",
    "OPENCODE_API_KEY",
    "KIMI_API_KEY",
    "CLOUDFLARE_API_KEY",
    "CLOUDFLARE_ACCOUNT_ID",
    "CLOUDFLARE_GATEWAY_ID",
    "AWS_PROFILE",
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_BEARER_TOKEN_BEDROCK",
    "AWS_REGION",
    "PI_OFFLINE",
)

_CODING_EVAL_AGENT_ENV_KEYS = (
    "CODING_EVAL_LOCAL_BASE_URL",
    "CODING_EVAL_LOCAL_API_KEY",
    "CODING_EVAL_PI_PROVIDER_NAME",
    "CODING_EVAL_PI_PROVIDER_BASE_URL",
    "CODING_EVAL_PI_PROVIDER_API_KEY",
    "CODING_EVAL_PI_PROVIDER_API",
    "CODING_EVAL_PI_PROVIDER_MODEL_ID",
    "CODING_EVAL_PI_PROVIDER_MODEL_NAME",
    "CODING_EVAL_THINKING",
    "CODING_EVAL_REASONING_EFFORT",
)

_CONTAINER_BENCH_SKILLS = (
    "/installed-agent/bench-skills/systematic-debugging",
    "/installed-agent/bench-skills/verification-before-completion",
)

_RUNTIME_DEPENDENCY_INSTALL_COMMAND = r"""
set -e
if command -v curl >/dev/null 2>&1; then
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


def _devstack_profile_install_command() -> str:
    """Install the read-only devstack package snapshot into the agent home."""
    return r'''
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
. "$HOME/.nvm/nvm.sh"
pi list
'''.strip()


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
                for key in (*_PROVIDER_ENV_KEYS, *_CODING_EVAL_AGENT_ENV_KEYS)
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
. "$HOME/.nvm/nvm.sh"
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
const models = [
  {
    id: modelId,
    name: modelName,
    reasoning: true,
    input: ['text'],
    contextWindow: 262144,
    maxTokens: 81920,
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
        contextWindow: 262144,
        maxTokens: 81920,
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
"""
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
            command = r"""
mkdir -p /installed-agent/bench-skills/systematic-debugging
cat >/installed-agent/bench-skills/systematic-debugging/SKILL.md <<'EOF'
# Systematic Debugging

When a task fails, form a concrete hypothesis, run the smallest useful
diagnostic command, inspect the actual output, and make one targeted change.
Do not guess repeatedly without checking the result.
EOF

mkdir -p /installed-agent/bench-skills/verification-before-completion
cat >/installed-agent/bench-skills/verification-before-completion/SKILL.md <<'EOF'
# Verification Before Completion

Before finishing, run the task's relevant tests or validation command. If that
is impossible, state exactly what command could not run and why.
EOF
"""
            await self.exec_as_root(environment, command=command)

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
                    "if [[ -f \"$HOME/.nvm/nvm.sh\" ]]; then "
                    ". \"$HOME/.nvm/nvm.sh\"; "
                    "else "
                    "curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.2/install.sh | bash; "
                    ". \"$HOME/.nvm/nvm.sh\"; "
                    "fi; "
                    "nvm install 22; "
                    f"if ! command -v {shlex.quote(self.cli_command)} >/dev/null 2>&1; then "
                    f"npm install -g {shlex.quote(package)}; "
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
                self.model_name,
                *_thinking_args(),
                instruction,
            ]
            await self.exec_as_agent(
                environment,
                command=_wrap_with_pi_session_export(
                    f". ~/.nvm/nvm.sh; {shlex.join(cmd)}",
                    output_filename=self._output_filename,
                ),
                env=self._provider_env(),
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
                for key in (*_PROVIDER_ENV_KEYS, *_CODING_EVAL_AGENT_ENV_KEYS)
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
                "include_devstack_profile": self.include_devstack_profile,
            }

        def _run_agent_commands(self, instruction: str) -> list[TerminalCommand]:
            cmd = [
                self.cli_command,
                "--print",
                *self.extra_args,
                "--model",
                self._model_name,
                *_thinking_args(),
                instruction,
            ]
            return [
                TerminalCommand(
                    command=_wrap_with_pi_session_export(shlex.join(cmd)),
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
    )
    include_bench_skills = True
    _agent_name = "coding-eval-little-coder-superpowers"

    @staticmethod
    def name() -> str:
        return LittleCoderSuperpowersHarborAgent._agent_name
