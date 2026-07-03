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
    """Aider Polyglot benchmark suite.

    Dataset: https://github.com/Aider-AI/polyglot-benchmark
    Layout (Exercism-sourced, 225 problems across 6 languages):

        polyglot-benchmark/<lang>/exercises/practice/<problem>/
            .docs/instructions.md       <- problem statement
            <basename>.<ext>            <- starter file (functions with `pass`)
            <basename>_test.<ext>       <- test file

    The previous implementation assumed a simplified
    `problems/<lang>/<problem>/{problem.txt, starter/, tests/}` shape that
    does not exist in the real benchmark. We now read the real layout.
    """

    name = "aider_polyglot"
    version = "0.2"
    # Languages present in the real polyglot-benchmark repo
    languages = ["python", "go", "rust", "cpp", "java", "javascript"]
    task_count = 0

    # Map language -> file extension used for starter/test files
    LANG_EXT = {
        "python": "py",
        "go": "go",
        "rust": "rs",
        "cpp": "cpp",
        "java": "java",
        "javascript": "js",
    }

    def _problem_dir(self, vendor_dir: Path, language: str, problem: str) -> Path:
        """Locate the on-disk problem directory for a (language, problem)."""
        # Real polyglot-benchmark layout
        return (
            vendor_dir
            / "polyglot-benchmark"
            / language
            / "exercises"
            / "practice"
            / problem
        )

    def get_task_ids(self, vendor_dir: Path = None) -> List[str]:
        """Discover all task IDs from the polyglot-benchmark dataset."""
        if vendor_dir is None:
            vendor_dir = Path("vendor")
        vendor_dir = Path(vendor_dir)

        root = vendor_dir / "polyglot-benchmark"
        if not root.exists():
            return []

        task_ids = []
        for lang_dir in sorted(root.iterdir()):
            if not lang_dir.is_dir() or lang_dir.name not in self.LANG_EXT:
                continue
            practice_dir = lang_dir / "exercises" / "practice"
            if not practice_dir.is_dir():
                continue
            for problem_dir in sorted(practice_dir.iterdir()):
                if not problem_dir.is_dir():
                    continue
                # A problem is real if it has an instructions.md
                if (problem_dir / ".docs" / "instructions.md").exists():
                    task_ids.append(f"{lang_dir.name}/{problem_dir.name}")

        return sorted(task_ids)

    def materialize_task(self, task_id: str, workdir: Path, vendor_dir: Path = None) -> Dict[str, Any]:
        """
        Materialize a polyglot-benchmark problem into the workdir.

        Copies the starter file and test file into the workdir root, and
        extracts the prompt from .docs/instructions.md.
        """
        if vendor_dir is None:
            vendor_dir = Path("vendor")
        vendor_dir = Path(vendor_dir)

        # Parse task_id (e.g., "python/two-fer", "go/zebra-puzzle")
        parts = task_id.split("/")
        if len(parts) != 2:
            raise ValueError(
                f"Invalid task_id format: {task_id}. Expected 'language/problem'."
            )

        language, problem = parts
        problem_dir = self._problem_dir(vendor_dir, language, problem)
        if not problem_dir.exists():
            raise FileNotFoundError(f"Problem not found: {problem_dir}")

        workdir.mkdir(parents=True, exist_ok=True)

        # Prompt from .docs/instructions.md
        prompt = ""
        instr_file = problem_dir / ".docs" / "instructions.md"
        if instr_file.exists():
            prompt = instr_file.read_text()

        # Copy ALL files from the problem dir into the workdir root so the
        # language's test runner can find starter + tests + module files.
        for item in problem_dir.iterdir():
            if item.name == ".docs":
                continue
            if item.is_dir():
                shutil.copytree(item, workdir / item.name, dirs_exist_ok=True)
            else:
                shutil.copy2(item, workdir / item.name)

        return {
            "task_id": task_id,
            "prompt": prompt,
            "language": language,
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
        match = re.findall(r"^--- PASS:", output, re.MULTILINE)
        if match:
            return len(match)

        # Legacy/custom go output with an explicit count
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
