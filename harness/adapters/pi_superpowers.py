"""
pi_superpowers adapter — pi + Superpowers skills (bench mode).

Strips interactive skill-check flows (no user present to answer clarifying
questions). Keeps only systematic-debugging + verification-before-completion
skills.

This is the "Superpowers helps pi_vanilla on TB (recovery discipline)" arm
of the 2x2 ablation.
"""

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class AdapterResult:
    returncode: int
    usage: Optional[object] = None


class PiSuperpowersAdapter:
    """Pi + Superpowers skills (bench mode, no interactive flows)."""

    name = "pi_superpowers"
    version = "superpowers-bench"

    def run(self, task_data: dict, workdir: Path, log_file: Path, stderr_file: Path) -> AdapterResult:
        """
        Run pi with Superpowers skills in headless mode.

        Args:
            task_data: Dict with 'prompt' (problem statement) and 'files' (starter files)
            workdir: Directory containing the task files
            log_file: Path to write session log
            stderr_file: Path to write stderr

        Returns:
            AdapterResult with exit code and optional token usage
        """
        prompt = task_data.get("prompt", "")

        # Build the pi command with Superpowers skills
        cmd = [
            "pi",
            "--print",
            "--no-extensions",
            "--no-skills",
            "-m", task_data.get("model_id", "nvidia/nemotron-3-ultra-550b-a55b"),
        ]

        # Add Superpowers skills (systematic debugging + verification)
        # In bench mode, we strip interactive flows
        skills_dir = Path.home() / ".pi" / "agent" / "skills"
        if skills_dir.exists():
            cmd.extend(["--skill", str(skills_dir)])

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
