"""
little_coder adapter — little-coder launcher.

Launches `little-coder -m <model>` which is pi + 20 extensions + 30 skills.
Maximal targeted scaffold for small models. Same loop and tools API as pi,
but with little-coder's context engineering.
"""

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from harness.adapters.session_utils import trial_session_args
from harness.subprocess_utils import run_command


@dataclass
class AdapterResult:
    returncode: int
    usage: Optional[object] = None
    error: Optional[str] = None


class LittleCoderAdapter:
    """Little-coder launcher — pi + 20 ext + 30 skills."""

    name = "little_coder"
    version = "1.9.11"
    uses_workspace_sandbox = True

    def run(self, task_data: dict, workdir: Path, log_file: Path, stderr_file: Path) -> AdapterResult:
        """
        Run little-coder in headless mode against the task workdir.

        Args:
            task_data: Dict with 'prompt' (problem statement) and 'files' (starter files)
            workdir: Directory containing the task files
            log_file: Path to write session log
            stderr_file: Path to write stderr

        Returns:
            AdapterResult with exit code and optional token usage
        """
        prompt = task_data.get("prompt", "")

        # Build the little-coder command
        cmd = [
            "little-coder",
            "--print",
            "--model", task_data.get("model_id", "nvidia/nemotron-3-ultra-550b-a55b"),
        ]
        cmd.extend(trial_session_args(log_file))

        thinking = task_data.get("thinking")
        if thinking:
            cmd.extend(["--thinking", str(thinking)])

        # Run little-coder in the workdir, passing the prompt
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
                        timeout=task_data.get("timeout", 600),  # 10 min default
                        sandbox_workdir=workdir,
                        sandbox_name=task_data.get("problem"),
                    )

            return AdapterResult(returncode=result.returncode)

        except subprocess.TimeoutExpired:
            return AdapterResult(returncode=-1)
        except Exception as e:
            return AdapterResult(returncode=-1, error=str(e))
