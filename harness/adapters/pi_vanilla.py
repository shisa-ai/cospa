"""
pi_vanilla adapter — pi --no-extensions, baseline scaffold.

Launches `pi --no-extensions --print -m <model>` in headless mode against
a task workdir. This is the floor: pi's four built-in tools, ~1K-token
system prompt, nothing else.
"""

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from harness.adapters.sampling import validate_pi_sampling_params
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
    budget_exhausted: bool = False


class PiVanillaAdapter:
    """Pi with no extensions — minimal scaffold."""

    name = "pi_vanilla"
    version = "vanilla"
    uses_workspace_sandbox = True

    def run(self, task_data: dict, workdir: Path, log_file: Path, stderr_file: Path) -> AdapterResult:
        """
        Run pi in headless mode against the task workdir.

        Args:
            task_data: Dict with 'prompt' (problem statement) and 'files' (starter files)
            workdir: Directory containing the task files
            log_file: Path to write session log
            stderr_file: Path to write stderr

        Returns:
            AdapterResult with exit code and optional token usage
        """
        prompt = with_no_network_hint(task_data.get("prompt", ""))
        validate_pi_sampling_params(
            task_data.get("model_id", ""), task_data.get("sampling_params", {})
        )
        trace_env = behavior_trace_env(log_file)

        # Build the pi command
        cmd = [
            "pi",
            "--no-extensions",
            "--print",
            "--model", task_data.get("model_id", "nvidia/nemotron-3-ultra-550b-a55b"),
        ]
        cmd.extend(trial_session_args(log_file))
        cmd.extend(behavior_trace_args(log_file))

        # Optional thinking/effort level. When set, forward as `pi --thinking <level>`.
        # When unset, omit the flag entirely so pi/model defaults apply.
        thinking = task_data.get("thinking")
        if thinking:
            cmd.extend(["--thinking", str(thinking)])

        # Run pi in the workdir, passing the prompt
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
                        timeout=task_data.get("timeout", 600),  # 10 min default
                        sandbox_workdir=workdir,
                        sandbox_name=task_data.get("problem"),
                        sandbox_model_url=task_data.get("model_base_url"),
                    )

            return AdapterResult(returncode=result.returncode)

        except subprocess.TimeoutExpired:
            return AdapterResult(returncode=-1, budget_exhausted=True)
        except Exception as e:
            return AdapterResult(returncode=-1, error=str(e))
