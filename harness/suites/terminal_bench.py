"""
Terminal-Bench suite — Harbor-based evaluation.

This suite delegates to Harbor for task execution and verification.
It reads the Terminal-Bench registry to discover tasks, then launches
Harbor jobs with the appropriate agent and model.

Reference: vendor/terminal-bench/CLAUDE.md
"""

import json
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List


@dataclass
class SuiteResult:
    name: str
    adapter: str
    model: str
    task_id: str
    trial: int
    passed: bool
    test_count: int = 0
    wall_clock_seconds: float = 0.0


class TerminalBenchSuite:
    """Terminal-Bench suite using Harbor for execution."""

    name = "terminal_bench"
    version = "0.1"
    languages = ["python"]
    task_count = 0

    def get_task_ids(self, vendor_dir: Path = None) -> List[str]:
        """Get all task IDs from Terminal-Bench registry or original-tasks directory."""
        if vendor_dir is None:
            vendor_dir = Path("vendor")

        registry_file = vendor_dir / "terminal-bench" / "registry.json"
        if not registry_file.exists():
            return []

        with open(registry_file) as f:
            registry = json.load(f)

        # Registry is a list of dataset versions
        task_ids = []
        for entry in registry:
            # Use the head version if available, otherwise use the latest
            if entry.get("version") == "head" and entry.get("task_id_subset") is None:
                # Head version with no subset = all tasks
                # Discover tasks from the original-tasks directory
                tasks_dir = vendor_dir / "terminal-bench" / "original-tasks"
                if tasks_dir.exists():
                    for task_dir in tasks_dir.iterdir():
                        if task_dir.is_dir():
                            task_ids.append(task_dir.name)
                break
            elif entry.get("task_id_subset"):
                task_ids.extend(entry["task_id_subset"])

        return sorted(set(task_ids))  # Deduplicate

    def materialize_task(self, task_id: str, workdir: Path, vendor_dir: Path = None) -> Dict[str, Any]:
        """
        Materialize a Terminal-Bench task into the workdir.

        For Terminal-Bench, we don't copy files — we let Harbor handle
        task setup via its own mechanisms. The workdir is used as the
        jobs directory for Harbor output.

        Returns task_data with metadata for the adapter/Harbor.
        """
        if vendor_dir is None:
            vendor_dir = Path("vendor")

        # Copy the original task into the workdir
        original_task_dir = vendor_dir / "terminal-bench" / "original-tasks" / task_id
        if original_task_dir.exists():
            # Clear workdir and copy task files
            if workdir.exists():
                shutil.rmtree(workdir)
            workdir.mkdir(parents=True, exist_ok=True)
            shutil.copytree(original_task_dir, workdir, dirs_exist_ok=True)

            # Read the task instruction if available
            instruction_file = workdir / "instruction.md"
            prompt = ""
            if instruction_file.exists():
                prompt = instruction_file.read_text()

            # Read the verifier if available
            verifier_file = workdir / "verifier.py"
            verifier = ""
            if verifier_file.exists():
                verifier = verifier_file.read_text()

            # Read the scorer if available
            scorer_file = workdir / "scorer.py"
            scorer = ""
            if scorer_file.exists():
                scorer = scorer_file.read_text()
        else:
            prompt = f"Terminal-Bench task: {task_id}"

        return {
            "task_id": task_id,
            "prompt": prompt,
            "verifier": verifier,
            "scorer": scorer,
            "model_id": "nvidia/nemotron-3-ultra-550b-a55b",
        }

    def verify(self, task_data: Dict[str, Any], workdir: Path) -> Dict[str, Any]:
        """
        Verify the solution by checking Harbor output.

        For Terminal-Bench, verification is handled by Harbor's scoring.
        This method checks if Harbor has produced a score for the task.
        """
        # Check if there's a Harbor output directory for this task
        # Harbor stores results in jobs/<job_id>/trials/<trial_id>/
        harbor_jobs = workdir.parent / "jobs"
        if harbor_jobs.exists():
            # Look for recent job output
            for job_dir in sorted(harbor_jobs.iterdir(), reverse=True):
                if job_dir.is_dir():
                    trials_dir = job_dir / "trials"
                    if trials_dir.exists():
                        for trial_dir in trials_dir.iterdir():
                            if trial_dir.is_dir():
                                score_file = trial_dir / "score.json"
                                if score_file.exists():
                                    try:
                                        with open(score_file) as f:
                                            score_data = json.load(f)
                                        return {
                                            "passed": score_data.get("score", 0) > 0,
                                            "test_count": score_data.get("total_tests", 0),
                                            "grader_output": json.dumps(score_data, indent=2),
                                            "exit_code": 0,
                                        }
                                    except Exception:
                                        pass

        # If no Harbor output, return a pending status
        return {
            "passed": False,
            "test_count": 0,
            "grader_output": "No Harbor output found — run harbor run first",
            "exit_code": -1,
            "pending": True,
        }

    def run_harbor_job(
        self,
        task_id: str,
        model_id: str,
        adapter_name: str,
        workdir: Path,
        jobs_dir: Path,
        n_attempts: int = 1,
    ) -> Dict[str, Any]:
        """
        Run a Harbor job for a Terminal-Bench task.

        This is the primary execution path for Terminal-Bench tasks.
        It delegates to `harbor run` with the appropriate agent and model.
        """
        # Map adapter name to Harbor agent
        agent_map = {
            "pi_vanilla": "pi",
            "pi_devstack": "pi",
            "pi_superpowers": "pi",
            "little_coder": "aider",
            "little_coder_superpowers": "aider",
        }
        agent = agent_map.get(adapter_name, "pi")

        # Build harbor command
        cmd = [
            "harbor",
            "run",
            "--agent", agent,
            "--model", model_id,
            "--jobs-dir", str(jobs_dir),
            "--n-attempts", str(n_attempts),
            "--path", str(workdir),
            "--yes",  # Auto-confirm
        ]

        try:
            result = subprocess.run(
                cmd,
                cwd=str(workdir),
                capture_output=True,
                text=True,
                timeout=3600,  # 1 hour timeout for Harbor
            )

            return {
                "returncode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
            }
        except subprocess.TimeoutExpired:
            return {
                "returncode": -1,
                "stdout": "",
                "stderr": "Harbor job timed out",
            }
        except Exception as e:
            return {
                "returncode": -1,
                "stdout": "",
                "stderr": str(e),
            }
