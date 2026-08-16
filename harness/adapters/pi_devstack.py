"""
pi_devstack adapter — canonical devstack pi profile.

Launches pi with the devstack's extensions and skills loaded via normal
discovery. This is "pi as we run it day-to-day" — mid-scaffold.

The devstack configuration is managed by pi-packages.json and pi's
normal extension/skill discovery mechanism. We do NOT use --no-extensions
or --no-skills here, because we want the full devstack behavior.
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


class PiDevstackAdapter:
    """Pi with devstack extensions and skills (normal discovery)."""

    name = "pi_devstack"
    version = "devstack"
    uses_workspace_sandbox = True

    def run(self, task_data: dict, workdir: Path, log_file: Path, stderr_file: Path) -> AdapterResult:
        """
        Run pi with devstack extensions and skills in headless mode.

        Uses pi's normal extension/skill discovery (no --no-extensions flag).
        """
        prompt = with_no_network_hint(task_data.get("prompt", ""))
        validate_pi_sampling_params(
            task_data.get("model_id", ""), task_data.get("sampling_params", {})
        )
        trace_env = behavior_trace_env(log_file)

        # Build the pi command — use normal devstack discovery
        cmd = [
            "pi",
            "--print",
            "--model", task_data.get("model_id", "nvidia/nemotron-3-ultra-550b-a55b"),
        ]
        cmd.extend(trial_session_args(log_file))
        cmd.extend(behavior_trace_args(log_file))

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
