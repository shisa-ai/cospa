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
import os
import shlex
import shutil
import subprocess
import tempfile
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List

from harness.subprocess_utils import run_command


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
    GENERATED_ARTIFACT_DIRS = {
        ".gradle",
        ".pytest_cache",
        "__pycache__",
        "build",
        "node_modules",
        "target",
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
            if item.is_dir() and item.name in self.GENERATED_ARTIFACT_DIRS:
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
        setup_cmds: list[list[str]] = []
        run_in_temp_copy = False
        env = self._verification_env()

        # Build test command based on language
        if language == "python":
            test_files = sorted(
                path.name
                for pattern in ("*_test.py", "test_*.py")
                for path in workdir.glob(pattern)
            )
            cmd = [
                "python",
                "-m",
                "pytest",
                "-v",
                "--tb=short",
                "-x",
                *(test_files or ["."]),
            ]
        elif language == "javascript" or language == "typescript":
            # Check for package.json and use npm/yarn
            pkg_file = workdir / "package.json"
            if pkg_file.exists():
                setup_cmds.append(
                    ["npm", "install", "--no-audit", "--no-fund", "--ignore-scripts"]
                )
                cmd = ["npm", "test"]
                run_in_temp_copy = True
            else:
                cmd = ["npx", "jest", "--verbose"]
        elif language == "go":
            cmd = ["go", "test", "./...", "-v", "-timeout", "5m"]
        elif language == "java":
            gradle_cmd = "./gradlew" if (workdir / "gradlew").exists() else "gradle"
            cmd = [gradle_cmd, "test", "--info"]
            run_in_temp_copy = True
        elif language == "rust":
            cmd = ["cargo", "test", "--verbose"]
            run_in_temp_copy = True
        elif language == "c" or language == "cpp":
            # Try cmake + build + test. Do not append a shell fallback such as
            # `|| echo ...`: that masks nonzero build/test exits as success.
            problem = task_data.get("problem")
            source_dir = "."
            if problem:
                source_link = workdir / problem
                if not source_link.exists():
                    source_link.symlink_to(".", target_is_directory=True)
                if (source_link / "CMakeLists.txt").exists():
                    source_dir = problem
            build_cmd = "cmake --build build"
            if problem:
                build_cmd += f" --target {shlex.quote(f'test_{problem}')}"
            cmd = [
                "bash",
                "-c",
                (
                    f"cmake -S {shlex.quote(source_dir)} -B build "
                    f"-DEXERCISM_RUN_ALL_TESTS=ON && {build_cmd}"
                ),
            ]
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

        # Run tests. Some language toolchains either install large dependency
        # trees or fail under deeply encoded result paths; run those from a
        # short temp copy while keeping the model-authored workdir unchanged.
        try:
            if run_in_temp_copy:
                with tempfile.TemporaryDirectory(
                    prefix=f"coding-eval-{language}-"
                ) as tmp:
                    verify_dir = Path(tmp) / "workdir"
                    self._copy_for_verification(workdir, verify_dir)
                    return self._run_verifier_commands(
                        setup_cmds,
                        cmd,
                        verify_dir,
                        timeout=timeout,
                        env=env,
                    )
            return self._run_verifier_commands(
                setup_cmds,
                cmd,
                workdir,
                timeout=timeout,
                env=env,
            )
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

    @classmethod
    def _run_verifier_commands(
        cls,
        setup_cmds: list[list[str]],
        test_cmd: list[str],
        workdir: Path,
        *,
        timeout: int,
        env: dict[str, str],
    ) -> Dict[str, Any]:
        setup_output = ""
        for setup_cmd in setup_cmds:
            setup_result = run_command(
                setup_cmd,
                cwd=str(workdir),
                capture_output=True,
                text=True,
                timeout=timeout,
                env=env,
            )
            if setup_result.stdout:
                setup_output += setup_result.stdout
            if setup_result.stderr:
                setup_output += "\n--- SETUP STDERR ---\n" + setup_result.stderr
            if setup_result.returncode != 0:
                return {
                    "passed": False,
                    "test_count": 0,
                    "grader_output": setup_output,
                    "exit_code": setup_result.returncode,
                }

        result = run_command(
            test_cmd,
            cwd=str(workdir),
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )

        # Parse test results
        test_output = (result.stdout or "") + (result.stderr or "")
        test_count = cls._count_tests(test_output)
        if test_count == 0:
            test_count = cls._count_tests_from_artifacts(workdir)
        passed = result.returncode == 0 and test_count > 0

        # Store both stdout and stderr for diagnostics
        grader_output = setup_output + (result.stdout or "")
        if result.stderr:
            grader_output += "\n--- STDERR ---\n" + result.stderr

        return {
            "passed": passed,
            "test_count": test_count,
            "grader_output": grader_output,
            "exit_code": result.returncode,
        }

    @classmethod
    def _copy_for_verification(cls, source: Path, dest: Path) -> None:
        def ignore(_dir: str, names: list[str]) -> set[str]:
            return set(names) & cls.GENERATED_ARTIFACT_DIRS

        shutil.copytree(source, dest, ignore=ignore)

    @staticmethod
    def _verification_env() -> dict[str, str]:
        env = os.environ.copy()
        java_home = env.get("JAVA_HOME")
        if java_home and not (Path(java_home) / "bin" / "java").exists():
            env.pop("JAVA_HOME", None)
        return env

    @staticmethod
    def _count_tests_from_artifacts(workdir: Path) -> int:
        total = 0
        for xml_file in workdir.glob("build/test-results/**/*.xml"):
            try:
                root = ET.parse(xml_file).getroot()
            except ET.ParseError:
                continue
            try:
                total += int(root.attrib.get("tests", 0))
            except ValueError:
                continue
        return total

    @staticmethod
    def _count_tests(output: str) -> int:
        """Count number of tests from test output."""
        if not output:
            return 0

        import re

        # Cargo can report several test binaries. Sum the executed passing tests
        # so an initial "0 passed" lib/doc-test block does not mask real tests.
        rust_counts = [
            int(count)
            for count in re.findall(r"test result:\s+ok\.\s+(\d+)\s+passed;", output)
        ]
        if rust_counts:
            return sum(rust_counts)

        # Try to parse pytest-style output
        matches = [int(count) for count in re.findall(r"(\d+) passed", output)]
        positive_matches = [count for count in matches if count > 0]
        if positive_matches:
            return sum(positive_matches)

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

        # Try to parse Java/Maven/Gradle test output
        match = re.search(r"Tests\s+run:\s+(\d+)", output)
        if match:
            return int(match.group(1))
        match = re.search(r"(\d+)\s+tests?\s+completed", output, re.IGNORECASE)
        if match:
            return int(match.group(1))
        match = re.search(r"\[\s*(\d+)\s+tests?\s+successful\s*\]", output, re.IGNORECASE)
        if match:
            return int(match.group(1))

        # Try to parse CMake/CTest output
        match = re.search(
            r"All tests passed \([^)]*\bin\s+(\d+)\s+test cases?\)",
            output,
            re.IGNORECASE,
        )
        if match:
            return int(match.group(1))
        match = re.search(r"(\d+)\s+tests?\s+passed", output, re.IGNORECASE)
        if match:
            return int(match.group(1))
        match = re.search(r"tests?\s+failed\s+out\s+of\s+(\d+)", output, re.IGNORECASE)
        if match:
            return int(match.group(1))

        return 0
