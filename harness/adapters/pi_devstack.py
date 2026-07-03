"""
pi_devstack adapter — canonical devstack pi profile.

Launches pi with the devstack's extensions and skills loaded. This is
"pi as we run it day-to-day" — mid-scaffold.
"""

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class AdapterResult:
    returncode: int
    usage: Optional[object] = None


class PiDevstackAdapter:
    """Pi with devstack extensions and skills."""

    name = "pi_devstack"
    version = "devstack"

    def run(self, task_data: dict, workdir: Path, log_file: Path, stderr_file: Path) -> AdapterResult:
        """
        Run pi with devstack extensions and skills in headless mode.

        Args:
            task_data: Dict with 'prompt' (problem statement) and 'files' (starter files)
            workdir: Directory containing the task files
            log_file: Path to write session log
            stderr_file: Path to write stderr

        Returns:
            AdapterResult with exit code and optional token usage
        """
        prompt = task_data.get("prompt", "")

        # Build the pi command with devstack extensions and skills
        cmd = [
            "pi",
            "--print",
            "--no-extensions",
            "--no-skills",
            "-m", task_data.get("model_id", "nvidia/nemotron-3-ultra-550b-a55b"),
        ]

        # Add devstack extensions (individual files)
        extensions_dir = Path.home() / ".pi" / "agent" / "extensions"
        if extensions_dir.exists():
            for ext in extensions_dir.iterdir():
                if ext.is_file():
                    cmd.extend(["--extension", str(ext)])
                elif ext.is_dir():
                    # If it's a directory, load all .ts files in it
                    for ext_file in ext.glob("*.ts"):
                        cmd.extend(["--extension", str(ext_file)])

        # Add devstack skills
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
