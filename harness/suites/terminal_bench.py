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

        task_ids = []
        for task_key in registry.keys():
            # Extract task ID from registry key (e.g., "org/name" -> "name")
            task_id = task_key.split("/")[-1]
            task_ids.append(task_id)

        return sorted(task_ids)

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
        Verify the solution by running harbor run.

        This is a stub — full implementation delegates to harbor run.
        """
        return {
            "passed": False,
            "test_count": 0,
            "grader_output": "STUB — use harbor run directly",
            "exit_code": -1,
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
