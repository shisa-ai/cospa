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


@dataclass
class AdapterResult:
    returncode: int
    usage: Optional[object] = None


class PiVanillaAdapter:
    """Pi with no extensions — minimal scaffold."""

    name = "pi_vanilla"
    version = "vanilla"

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
        prompt = task_data.get("prompt", "")

        # Build the pi command
        cmd = [
            "pi",
            "--no-extensions",
            "--print",
            "-m", task_data.get("model_id", "nvidia/nemotron-3-ultra-550b-a55b"),
        ]

        # Run pi in the workdir, passing the prompt
        try:
            result = subprocess.run(
                cmd,
                input=prompt,
                cwd=str(workdir),
                stdout=open(log_file, "w"),
                stderr=stderr_file,
                text=True,
                timeout=task_data.get("timeout", 600),  # 10 min default
            )

            return AdapterResult(returncode=result.returncode)

        except subprocess.TimeoutExpired:
            return AdapterResult(returncode=-1)
        except Exception as e:
            return AdapterResult(returncode=-1)
