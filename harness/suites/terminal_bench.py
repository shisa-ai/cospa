"""
Terminal-Bench suite — canonical agentic eval via Harbor.

Wraps `harbor run` against `terminal-bench@latest` using `--agent-import-path`
per adapter.

This is a stub — full implementation in P11.
"""

from typing import List, Dict, Any


class TerminalBenchSuite:
    """Terminal-Bench: canonical agentic eval via Harbor."""

    name = "terminal_bench"

    def get_task_ids(self) -> List[str]:
        """Get all task IDs from Terminal-Bench."""
        # Stub — will be implemented in P11
        return []

    def materialize_task(self, task_id: str, workdir, vendor_dir) -> Dict[str, Any]:
        """Materialize a task into a workdir."""
        # Stub
        return {"prompt": "", "files": [], "model_id": "nvidia/nemotron-3-ultra-550b-a55b"}

    def verify(self, task_data: Dict[str, Any], workdir) -> Dict[str, Any]:
        """Verify the solution."""
        # Stub
        return {"passed": False, "test_count": 0, "grader_output": "STUB", "exit_code": -1}
