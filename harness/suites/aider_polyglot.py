"""
Aider Polyglot suite — polyglot-benchmark evaluation.

This suite runs the Aider Polyglot benchmark, which tests coding agents
across multiple programming languages using Exercism-style problems.

Dataset structure (real polyglot-benchmark):
  vendor/aider-polyglot/problems/<language>/<problem>/
    problem.txt          - Problem statement
    starter/             - Starter code files
    tests/               - Test files

This suite is compatible with both the simplified local format and the
full polyglot-benchmark dataset from https://github.com/Aider-AI/polyglot-benchmark.
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


class AiderPolyglotSuite:
    """Aider Polyglot benchmark suite."""

    name = "aider_polyglot"
    version = "0.1"
    languages = ["python", "javascript", "typescript", "go", "java", "rust", "c", "cpp", "csharp", "ruby", "php", "swift", "kotlin", "scala", "r", "julia", "matlab", "haskell", "lua", "perl", "bash", "zsh", "powershell"]
    task_count = 0

    def get_task_ids(self, vendor_dir: Path = None) -> List[str]:
        """Get all task IDs from the Aider Polyglot dataset."""
        if vendor_dir is None:
            vendor_dir = Path("vendor")

        problems_dir = vendor_dir / "aider-polyglot" / "problems"
        if not problems_dir.exists():
            return []

        task_ids = []
        for lang_dir in problems_dir.iterdir():
            if not lang_dir.is_dir():
                continue
            for problem_dir in lang_dir.iterdir():
                if problem_dir.is_dir() and (problem_dir / "problem.txt").exists():
                    task_ids.append(f"{lang_dir.name}/{problem_dir.name}")

        return sorted(task_ids)

    def materialize_task(self, task_id: str, workdir: Path, vendor_dir: Path = None) -> Dict[str, Any]:
        """
        Materialize an Aider Polyglot task into the workdir.

        Copies problem.txt, starter files, and test files into the workdir.
        """
        if vendor_dir is None:
            vendor_dir = Path("vendor")

        # Parse task_id (e.g., "python/hello")
        parts = task_id.split("/")
        if len(parts) != 2:
            raise ValueError(f"Invalid task_id format: {task_id}. Expected 'language/problem'.")

        language, problem = parts

        # Find the problem directory
        problem_dir = vendor_dir / "aider-polyglot" / "problems" / language / problem
        if not problem_dir.exists():
            raise FileNotFoundError(f"Problem not found: {problem_dir}")

        # Create workdir
        workdir.mkdir(parents=True, exist_ok=True)

        # Read problem statement
        problem_file = problem_dir / "problem.txt"
        prompt = ""
        if problem_file.exists():
            prompt = problem_file.read_text()

        # Copy starter files
        starter_dir = problem_dir / "starter"
        if starter_dir.exists():
            shutil.copytree(starter_dir, workdir, dirs_exist_ok=True)

        # Copy test files
        tests_dir = problem_dir / "tests"
        if tests_dir.exists():
            shutil.copytree(tests_dir, workdir / "tests", dirs_exist_ok=True)

        # Detect language from directory name
        lang_map = {
            "python": "python",
            "javascript": "javascript",
            "typescript": "typescript",
            "go": "go",
            "java": "java",
            "rust": "rust",
            "c": "c",
            "cpp": "cpp",
            "csharp": "csharp",
            "ruby": "ruby",
            "php": "php",
            "swift": "swift",
            "kotlin": "kotlin",
            "scala": "scala",
            "r": "r",
            "julia": "julia",
            "matlab": "matlab",
            "haskell": "haskell",
            "lua": "lua",
            "perl": "perl",
            "bash": "bash",
            "zsh": "zsh",
            "powershell": "powershell",
        }

        return {
            "task_id": task_id,
            "prompt": prompt,
            "language": lang_map.get(language, language),
            "problem": problem,
            "model_id": "nvidia/nemotron-3-ultra-550b-a55b",
        }

    def verify(self, task_data: Dict[str, Any], workdir: Path) -> Dict[str, Any]:
        """
        Verify the solution by running tests.

        Detects the language and runs the appropriate test command.
        """
        language = task_data.get("language", "python")
        timeout = task_data.get("timeout", 300)  # 5 min default for tests

        # Build test command based on language
        if language == "python":
            cmd = ["python", "-m", "pytest", "-v", "--tb=short", "-x"]
        elif language == "javascript" or language == "typescript":
            # Check for package.json and use npm/yarn
            pkg_file = workdir / "package.json"
            if pkg_file.exists():
                cmd = ["npm", "test"]
            else:
                cmd = ["npx", "jest", "--verbose"]
        elif language == "go":
            cmd = ["go", "test", "./...", "-v", "-timeout", "5m"]
        elif language == "java":
            cmd = ["gradle", "test", "--info"]
        elif language == "rust":
            cmd = ["cargo", "test", "--verbose"]
        elif language == "c" or language == "cpp":
            # Try cmake + make + test
            cmd = ["bash", "-c", "cmake -B build && cmake --build build && ./build/test || echo 'Build failed'"]
        elif language == "csharp":
            cmd = ["dotnet", "test", "--logger", "console", "--verbosity", "normal"]
        elif language == "ruby":
            cmd = ["bundle", "exec", "rspec", "--format", "documentation"]
        elif language == "php":
            cmd = ["php", "-d", "display_errors=on", "-d", "error_reporting=E_ALL", "vendor/bin/phpunit"]
        elif language == "swift":
            cmd = ["swift", "test", "--verbose"]
        elif language == "kotlin":
            cmd = ["./gradlew", "test", "--info"]
        elif language == "scala":
            cmd = ["sbt", "test"]
        elif language == "r":
            cmd = ["Rscript", "-e", "testthat::test_dir('tests')"]
        elif language == "julia":
            cmd = ["julia", "--project=.", "-e", "using Pkg; Pkg.test()"]
        elif language == "matlab":
            cmd = ["matlab", "-batch", "run_tests"]
        elif language == "haskell":
            cmd = ["stack", "test", "--test-arguments", "-v"]
        elif language == "lua":
            cmd = [" busted", "--verbose"]
        elif language == "perl":
            cmd = ["prove", "-v", "t/"]
        elif language == "bash" or language == "zsh":
            cmd = ["bash", "-c", "find . -name '*.test.sh' -exec bash {} \\;"]
        elif language == "powershell":
            cmd = ["pwsh", "-Command", "Invoke-Pester -Output Detail"]
        else:
            return {
                "passed": False,
                "test_count": 0,
                "grader_output": f"Unsupported language: {language}",
                "exit_code": -1,
            }

        # Run tests
        try:
            result = subprocess.run(
                cmd,
                cwd=str(workdir),
                capture_output=True,
                text=True,
                timeout=timeout,
            )

            # Parse test results
            test_count = self._count_tests(result.stdout + result.stderr)
            passed = result.returncode == 0 and test_count > 0

            # Store both stdout and stderr for diagnostics
            grader_output = result.stdout
            if result.stderr:
                grader_output += "\n--- STDERR ---\n" + result.stderr

            return {
                "passed": passed,
                "test_count": test_count,
                "grader_output": grader_output,
                "exit_code": result.returncode,
            }

        except subprocess.TimeoutExpired:
            return {
                "passed": False,
                "test_count": 0,
                "grader_output": f"Test timed out after {timeout}s",
                "exit_code": -1,
            }
        except FileNotFoundError as e:
            return {
                "passed": False,
                "test_count": 0,
                "grader_output": f"Test runner not found: {e}",
                "exit_code": -1,
            }
        except Exception as e:
            return {
                "passed": False,
                "test_count": 0,
                "grader_output": f"Test verification error: {e}",
                "exit_code": -1,
            }

    def _count_tests(self, output: str) -> int:
        """Count number of tests from test output."""
        if not output:
            return 0

        import re

        # Try to parse pytest-style output
        match = re.search(r"(\d+) passed", output)
        if match:
            return int(match.group(1))

        # Try to parse go test output
        match = re.search(r"^ok\s+.*\((\d+)\s+tests?\)", output, re.MULTILINE)
        if match:
            return int(match.group(1))

        # Try to parse Rust cargo test output
        match = re.search(r"(\d+)\s+tests?:", output)
        if match:
            return int(match.group(1))

        # Try to parse Java test output
        match = re.search(r"Tests\s+run:\s+(\d+)", output)
        if match:
            return int(match.group(1))

        # Try to parse CMake/test output
        match = re.search(r"(\d+)\s+tests?\s+passed", output, re.IGNORECASE)
        if match:
            return int(match.group(1))

        return 0
