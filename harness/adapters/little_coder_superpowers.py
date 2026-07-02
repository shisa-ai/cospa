"""
little_coder_superpowers adapter — little-coder + Superpowers skills (bench mode).

Strips interactive skill-check flows. This is the "Superpowers helps little_coder"
arm of the 2x2 ablation.
"""

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class AdapterResult:
    returncode: int
    usage: Optional[object] = None


class LittleCoderSuperpowersAdapter:
    """Little-coder + Superpowers skills (bench mode, no interactive flows)."""

    name = "little_coder_superpowers"
    version = "superpowers-bench"

    def run(self, task_data: dict, workdir: Path, log_file: Path, stderr_file: Path) -> AdapterResult:
        """
        Run little-coder with Superpowers skills in headless mode.

        Args:
            task_data: Dict with 'prompt' (problem statement) and 'files' (starter files)
            workdir: Directory containing the task files
            log_file: Path to write session log
            stderr_file: Path to write stderr

        Returns:
            AdapterResult with exit code and optional token usage
        """
        prompt = task_data.get("prompt", "")

        # Build the little-coder command with Superpowers skills
        cmd = [
            "little-coder",
            "--print",
            "-m", task_data.get("model_id", "nvidia/nemotron-3-ultra-550b-a55b"),
        ]

        # Add Superpowers skills
        skills_dir = Path.home() / ".pi" / "agent" / "skills"
        if skills_dir.exists():
            cmd.extend(["--skill", str(skills_dir)])

        # Run little-coder in the workdir, passing the prompt
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
