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


try:
    from terminal_bench.agents.installed_agents.abstract_installed_agent import (
        AbstractInstalledAgent,
    )
    from terminal_bench.terminal.models import TerminalCommand
except ModuleNotFoundError:
    # Unit tests run in the coding-eval mamba env, which does not install the
    # terminal_bench package. Use the vendored checkout for importability there;
    # the Harbor subprocess will normally resolve terminal_bench from Harbor's
    # own environment.
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

_CONTAINER_BENCH_SKILLS = (
    "/installed-agent/bench-skills/systematic-debugging",
    "/installed-agent/bench-skills/verification-before-completion",
)


class _BasePiCliHarborAgent(AbstractInstalledAgent):
    cli_command = "pi"
    npm_package = "@earendil-works/pi-coding-agent"
    extra_args: tuple[str, ...] = ()
    include_bench_skills = False
    _agent_name = "coding-eval-pi"

    @staticmethod
    def name() -> str:
        return _BasePiCliHarborAgent._agent_name

    def __init__(self, model_name: str, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._model_name = model_name
        self._version = kwargs.get("version", "latest")

    @property
    def _env(self) -> dict[str, str]:
        return {
            key: value
            for key in _PROVIDER_ENV_KEYS
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
        }

    def _run_agent_commands(self, instruction: str) -> list[TerminalCommand]:
        cmd = [
            self.cli_command,
            "--print",
            *self.extra_args,
            "--model",
            self._model_name,
            instruction,
        ]
        return [
            TerminalCommand(
                command=shlex.join(cmd),
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
    _agent_name = "coding-eval-pi-devstack"

    @staticmethod
    def name() -> str:
        return PiDevstackHarborAgent._agent_name


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
