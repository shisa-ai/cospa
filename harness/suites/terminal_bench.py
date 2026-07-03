"""
Terminal-Bench suite — canonical agentic eval via Harbor.

Wraps `harbor run` against `terminal-bench@latest` using `--agent-import-path`
per adapter.

Landmine: Harbor `upload_dir` bug — if the agent creates `/tests` during a
task, the verifier's files land at `/tests/tests/test.sh` and scoring
silently breaks. Patch before any TB run; record the patch hash in the manifest.

Wall-clock probe first: run k=1 on a 5-task slice, measure time, then decide
k for the real matrix. TB on small models is slow.
"""

import json
import subprocess
from pathlib import Path
from typing import List, Dict, Any


class TerminalBenchSuite:
    """Terminal-Bench: canonical agentic eval via Harbor."""

    name = "terminal_bench"
    upload_dir_patch_hash = None  # Set after patching

    def get_task_ids(self) -> List[str]:
        """Get all task IDs from Terminal-Bench registry."""
        registry_file = Path("vendor/terminal-bench/registry.json")
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
                # We'll need to discover tasks from the tasks/ directory
                tasks_dir = Path("vendor/terminal-bench/tasks")
                if tasks_dir.exists():
                    for task_dir in tasks_dir.iterdir():
                        if task_dir.is_dir():
                            task_ids.append(task_dir.name)
                break
            elif entry.get("task_id_subset"):
                task_ids.extend(entry["task_id_subset"])

        return sorted(set(task_ids))  # Deduplicate

    def materialize_task(self, task_id: str, workdir: Path, vendor_dir: Path) -> Dict[str, Any]:
        """
        Materialize a task into a workdir.

        For Terminal-Bench, we don't materialize — we let Harbor handle it.
        This method returns minimal task data; the actual execution is
        delegated to harbor run.
        """
        return {
            "prompt": "",
            "files": [],
            "model_id": "nvidia/nemotron-3-ultra-550b-a55b",
            "task_id": task_id,
        }

    def verify(self, task_data: Dict[str, Any], workdir: Path) -> Dict[str, Any]:
        """
        Verify the solution by checking Harbor output.

        For Terminal-Bench, verification is handled by Harbor's scoring.
        This method checks if Harbor has produced a score for the task.
        """
        # Check if there's a Harbor output directory for this task
        harbor_output = workdir / ".harbor"
        if harbor_output.exists():
            # Look for score files
            score_file = harbor_output / "score.json"
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

    def run_harbor_job(self, adapter_name: str, task_ids: List[str], n_attempts: int = 1) -> Dict[str, Any]:
        """
        Run a Harbor job for Terminal-Bench tasks.

        Args:
            adapter_name: Adapter name (pi_vanilla, pi_devstack, little_coder)
            task_ids: List of task IDs to run
            n_attempts: Number of attempts per trial

        Returns:
            Job results dict
        """
        # Build harbor run command
        cmd = [
            "harbor", "run",
            "-d", "terminal-bench@latest",
            "-n", str(n_attempts),
            "--n-tasks", str(len(task_ids)),
        ]

        # Add task filters
        for task_id in task_ids:
            cmd.extend(["-i", task_id])

        # Add adapter-specific plugin
        if adapter_name == "little_coder":
            cmd.extend([
                "--plugin", "benchmarks.harbor_adapter.little_coder_agent:LittleCoderAgent"
            ])
        else:
            # For pi adapters, we'd need a pi_terminal_bench adapter
            # For now, use a generic approach
            cmd.extend([
                "--plugin", f"harness.suites.terminal_bench:{adapter_name.capitalize()}Agent"
            ])

        # Run harbor
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=3600,  # 1 hour
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
                "stderr": "HARBOR RUN TIMEOUT",
            }
        except Exception as e:
            return {
                "returncode": -1,
                "stdout": "",
                "stderr": f"HARBOR ERROR: {e}",
            }
