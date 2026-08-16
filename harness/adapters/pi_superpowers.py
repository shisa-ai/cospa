"""
pi_superpowers adapter — pi + Superpowers skills (bench mode).

Strips interactive skill-check flows (no user present to answer clarifying
questions). Loads the pinned systematic-debugging, test-driven-development,
and verification-before-completion profile. This is the "Superpowers helps
pi_vanilla on TB (recovery discipline)" arm of the 2x2 ablation.

We use --no-skills to disable default discovery, then explicitly load only the
checksum-verified repo-local profile. We do not pass the mutable
~/.pi/agent/skills directory, which can contain arbitrary interactive skills.
"""

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from harness.adapters.sampling import validate_pi_sampling_params
from harness.skill_profiles import (
    load_superpowers_profile,
    superpowers_skill_paths,
)
from harness.adapters.session_utils import (
    behavior_trace_args,
    behavior_trace_env,
    trial_session_args,
    with_no_network_hint,
)
from harness.subprocess_utils import run_command


@dataclass
class AdapterResult:
    returncode: int
    usage: Optional[object] = None
    error: Optional[str] = None


def _resolve_bench_skill_paths() -> list[str]:
    """Return checksum-validated, repo-local paths for the pinned treatment."""
    return superpowers_skill_paths()


class PiSuperpowersAdapter:
    """Pi + Superpowers skills (bench mode, no interactive flows)."""

    name = "pi_superpowers"
    version = "superpowers-bench-v1"
    uses_workspace_sandbox = True

    @staticmethod
    def manifest_metadata() -> dict:
        return {"capability_profile": load_superpowers_profile()}

    def run(self, task_data: dict, workdir: Path, log_file: Path, stderr_file: Path) -> AdapterResult:
        """
        Run pi with the Superpowers bench subset in headless mode.

        Uses --no-skills to disable default discovery, then loads only the
        allowlisted bench skills (systematic-debugging,
        test-driven-development, verification-before-completion). Interactive
        skills are stripped.
        """
        prompt = with_no_network_hint(task_data.get("prompt", ""))
        validate_pi_sampling_params(
            task_data.get("model_id", ""), task_data.get("sampling_params", {})
        )
        trace_env = behavior_trace_env(log_file)

        cmd = [
            "pi",
            "--print",
            "--no-extensions",
            "--no-skills",
            "--model", task_data.get("model_id", "nvidia/nemotron-3-ultra-550b-a55b"),
        ]
        cmd.extend(trial_session_args(log_file))
        cmd.extend(behavior_trace_args(log_file))

        thinking = task_data.get("thinking")
        if thinking:
            cmd.extend(["--thinking", str(thinking)])

        # Load ONLY the bench-appropriate skills (never the whole user dir)
        for skill_path in _resolve_bench_skill_paths():
            cmd.extend(["--skill", skill_path])

        try:
            with open(log_file, "w") as log_f:
                with open(stderr_file, "w") as stderr_f:
                    result = run_command(
                        cmd,
                        input=prompt,
                        cwd=str(workdir),
                        stdout=log_f,
                        stderr=stderr_f,
                        text=True,
                        env=trace_env,
                        timeout=task_data.get("timeout", 600),
                        sandbox_workdir=workdir,
                        sandbox_name=task_data.get("problem"),
                        sandbox_model_url=task_data.get("model_base_url"),
                    )

            return AdapterResult(returncode=result.returncode)

        except subprocess.TimeoutExpired:
            return AdapterResult(returncode=-1)
        except Exception as e:
            return AdapterResult(returncode=-1, error=str(e))
