"""
Aider Polyglot suite — 225 Exercism problems across 6 languages.

Loads the dataset, materializes problems into workdirs, runs the adapter,
then grades via the language's native test runner.

Dataset structure (expected):
  vendor/aider-polyglot/
    problems/
      <language>/
        <problem_id>/
          problem.txt      # Problem statement
          starter/         # Starter files
          tests/           # Test files
          solution/        # Reference solution (optional)
"""

import json
import shutil
import subprocess
from pathlib import Path
from typing import List, Dict, Any


class AiderPolyglotSuite:
    """Aider Polyglot: 225 Exercism problems, 6 languages."""

    name = "aider_polyglot"
    languages = ["cpp", "go", "java", "js", "python", "rust"]

    def get_task_ids(self) -> List[str]:
        """Get all problem IDs from the dataset."""
        polyglot_dir = Path("vendor/aider-polyglot")
        if not polyglot_dir.exists():
            return []

        task_ids = []
        for lang in self.languages:
            lang_dir = polyglot_dir / "problems" / lang
            if lang_dir.exists():
                for problem_dir in lang_dir.iterdir():
                    if problem_dir.is_dir():
                        task_ids.append(f"{lang}/{problem_dir.name}")

        return sorted(task_ids)

    def materialize_task(self, task_id: str, workdir: Path, vendor_dir: Path) -> Dict[str, Any]:
        """
        Materialize a problem into a workdir.

        Args:
            task_id: Problem ID (e.g. "python/two-fer")
            workdir: Directory to materialize into
            vendor_dir: Vendor directory containing the dataset

        Returns:
            Task data dict with 'prompt', 'files', 'language', 'test_cmd'
        """
        lang, problem = task_id.split("/")
        problem_dir = vendor_dir / "aider-polyglot" / "problems" / lang / problem

        # Create workdir structure
        workdir.mkdir(parents=True, exist_ok=True)

        # Copy starter files
        starter_dir = problem_dir / "starter"
        if starter_dir.exists():
            shutil.copytree(starter_dir, workdir, dirs_exist_ok=True)

        # Read problem statement
        prompt = ""
        problem_file = problem_dir / "problem.txt"
        if problem_file.exists():
            prompt = problem_file.read_text()

        # Build test command based on language
        test_cmd = self._get_test_command(lang, workdir)

        return {
            "prompt": prompt,
            "files": list(workdir.iterdir()),
            "language": lang,
            "problem": problem,
            "test_cmd": test_cmd,
            "model_id": "nvidia/nemotron-3-ultra-550b-a55b",  # Default, overridden by runner
        }

    def _get_test_command(self, lang: str, workdir: Path) -> str:
        """Get the test command for a language."""
        commands = {
            "python": "pytest",
            "js": "npm test",
            "java": "gradle test",
            "cpp": "cmake --build . && ./test",
            "go": "go test ./...",
            "rust": "cargo test",
        }
        return commands.get(lang, "echo 'no test command'")

    def verify(self, task_data: Dict[str, Any], workdir: Path) -> Dict[str, Any]:
        """
        Verify the solution by running the test command.

        Args:
            task_data: Task data from materialize_task
            workdir: Directory with the solution

        Returns:
            Verdict dict with 'passed', 'test_count', 'grader_output'
        """
        test_cmd = task_data.get("test_cmd", "echo 'no test command'")

        try:
            result = subprocess.run(
                test_cmd,
                cwd=str(workdir),
                shell=True,
                capture_output=True,
                text=True,
                timeout=120,  # 2 min for tests
            )

            passed = result.returncode == 0
            test_count = self._count_tests(result.stdout)

            return {
                "passed": passed,
                "test_count": test_count,
                "grader_output": result.stdout[-2000:] if result.stdout else "",  # Last 2KB
                "exit_code": result.returncode,
            }

        except subprocess.TimeoutExpired:
            return {
                "passed": False,
                "test_count": 0,
                "grader_output": "TEST TIMEOUT",
                "exit_code": -1,
            }
        except Exception as e:
            return {
                "passed": False,
                "test_count": 0,
                "grader_output": f"VERIFICATION ERROR: {e}",
                "exit_code": -1,
            }

    def _count_tests(self, output: str) -> int:
        """Count number of tests from test output."""
        if not output:
            return 0

        # Try to parse pytest-style output
        if "passed" in output:
            import re
            match = re.search(r"(\d+) passed", output)
            if match:
                return int(match.group(1))

        # Try to parse go test output
        if "ok" in output:
            import re
            match = re.search(r"(\d+)\.(\d+)s", output)
            if match:
                return 1  # Simplified

        return 0
