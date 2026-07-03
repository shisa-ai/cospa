"""
little_coder_superpowers adapter — little-coder + Superpowers skills (bench mode).

Strips interactive skill-check flows. This is the "Superpowers helps little_coder"
arm of the 2x2 ablation.

NOTE: This is a simplified implementation. In a full bench, we would:
1. Load only specific Superpowers skills (systematic-debugging, verification)
2. Strip interactive flows that require user input
3. Use --no-skills and then explicitly load only the bench-appropriate skills

For now, we load all skills from ~/.pi/agent/skills, which may include
interactive flows. This is a known limitation (see ORNITH-CODER-REVIEW.md #8).
"""

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class AdapterResult:
    returncode: int
    usage: Optional[object] = None
    error: Optional[str] = None


class LittleCoderSuperpowersAdapter:
    """Little-coder + Superpowers skills (bench mode, no interactive flows)."""

    name = "little_coder_superpowers"
    version = "superpowers-bench"

    def run(self, task_data: dict, workdir: Path, log_file: Path, stderr_file: Path) -> AdapterResult:
        """
        Run little-coder with Superpowers skills in headless mode.

        Uses --no-skills then explicitly loads only the Superpowers skills directory.
        """
        prompt = task_data.get("prompt", "")

        # Build the little-coder command with Superpowers skills
        cmd = [
            "little-coder",
            "--print",
            "--no-skills",
            "--model", task_data.get("model_id", "nvidia/nemotron-3-ultra-550b-a55b"),
        ]

        # Add Superpowers skills
        skills_dir = Path.home() / ".pi" / "agent" / "skills"
        if skills_dir.exists():
            cmd.extend(["--skill", str(skills_dir)])

        # Run little-coder in the workdir, passing the prompt
        try:
            with open(log_file, "w") as log_f:
                with open(stderr_file, "w") as stderr_f:
                    result = subprocess.run(
                        cmd,
                        input=prompt,
                        cwd=str(workdir),
                        stdout=log_f,
                        stderr=stderr_f,
                        text=True,
                        timeout=task_data.get("timeout", 600),  # 10 min default
                    )

            return AdapterResult(returncode=result.returncode)

        except subprocess.TimeoutExpired:
            return AdapterResult(returncode=-1)
        except Exception as e:
            return AdapterResult(returncode=-1, error=str(e))
