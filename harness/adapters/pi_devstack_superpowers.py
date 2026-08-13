"""
pi_devstack_superpowers adapter — devstack pi + Superpowers bench skills.

Preserves pi's normal extension discovery so the run keeps the devstack tool
surface, but disables default skill discovery and loads only the
bench-appropriate Superpowers subset. This gives a direct
pi_devstack-vs-pi_devstack+Superpowers comparison without interactive skills.
"""

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from harness.adapters.pi_superpowers import _resolve_bench_skill_paths
from harness.adapters.session_utils import trial_session_args, with_no_network_hint
from harness.subprocess_utils import run_command


@dataclass
class AdapterResult:
    returncode: int
    usage: Optional[object] = None
    error: Optional[str] = None


class PiDevstackSuperpowersAdapter:
    """Pi devstack extensions + Superpowers bench skills."""

    name = "pi_devstack_superpowers"
    version = "devstack-superpowers-bench"
    uses_workspace_sandbox = True

    def run(
        self,
        task_data: dict,
        workdir: Path,
        log_file: Path,
        stderr_file: Path,
    ) -> AdapterResult:
        prompt = with_no_network_hint(task_data.get("prompt", ""))

        cmd = [
            "pi",
            "--print",
            "--no-skills",
            "--model",
            task_data.get("model_id", "nvidia/nemotron-3-ultra-550b-a55b"),
        ]
        cmd.extend(trial_session_args(log_file))

        thinking = task_data.get("thinking")
        if thinking:
            cmd.extend(["--thinking", str(thinking)])

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
