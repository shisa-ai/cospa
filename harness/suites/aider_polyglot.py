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
import fnmatch
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
    version = "0.3"
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
    REFERENCE_ARTIFACT_DIRS = {".approaches", ".meta"}
    ISOLATION_PROFILE = "aider-hermetic-v1"

    def manifest_metadata(self, task_data: Dict[str, Any]) -> Dict[str, Any]:
        """Identify trials produced after the hermetic Aider cutover."""
        return {
            "isolation": {
                "profile": self.ISOLATION_PROFILE,
                "filesystem": "bubblewrap-empty-root-allowlist",
                "agent_network": "selected-model-endpoint-only",
                "verifier_network": "none",
                "reference_artifacts_excluded": sorted(
                    self.REFERENCE_ARTIFACT_DIRS
                ),
            },
            "verifier": {
                "test_inputs": "canonical-task-snapshot",
                "solution_overlay": "declared-solution-files-only",
            },
            "dataset": task_data.get("dataset", {}),
        }

    # Files/dirs that encode the hidden test assertions. These must NEVER be
    # copied into the agent's workdir (they would let the model reverse-
    # engineer a passing solution). They are re-injected by verify() at grading
    # time, after the agent has finished. fnmatch-style filename patterns.
    HIDDEN_TEST_PATTERNS = {
        "python": ("*_test.py", "test_*.py"),
        "go": ("*_test.go",),
        "javascript": ("*.spec.js", "*.test.js"),
        "cpp": ("*_test.cpp",),
        "c": ("*_test.c",),
    }
    # Whole directories (relative to the problem dir) that hold the hidden
    # tests, e.g. Rust integration tests and the Java src/test subtree.
    HIDDEN_TEST_RELATIVE = {
        "rust": ("tests",),
        "java": ("src/test",),
    }

    @classmethod
    def _hidden_test_entries(cls, problem_dir: Path, language: str) -> list[Path]:
        """Return the problem-dir-relative paths of hidden test files/dirs."""
        hidden: list[Path] = []
        patterns = cls.HIDDEN_TEST_PATTERNS.get(language, ())
        for item in problem_dir.iterdir():
            if any(fnmatch.fnmatch(item.name, p) for p in patterns):
                hidden.append(Path(item.name))
        for rel in cls.HIDDEN_TEST_RELATIVE.get(language, ()):
            if (problem_dir / rel).exists():
                hidden.append(Path(rel))
        return hidden

    @staticmethod
    def _git_dataset_metadata(dataset_root: Path) -> Dict[str, Any]:
        """Return and validate the immutable dataset checkout identity.

        Synthetic unit-test fixtures are ordinary directories and therefore
        have no git identity. A real checkout, however, must be clean: a
        previous agent can otherwise leave a complete solution in the vendor
        tree for every later trial.
        """
        metadata = {
            "repository": "Aider-AI/polyglot-benchmark",
            "commit": None,
            "tree": None,
            "dirty": None,
        }
        if not (dataset_root / ".git").exists():
            return metadata

        def git(*args: str) -> str:
            result = subprocess.run(
                ["git", "-C", str(dataset_root), *args],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode != 0:
                raise RuntimeError(
                    f"git {' '.join(args)} failed: "
                    f"{(result.stderr or result.stdout).strip()}"
                )
            return result.stdout.strip()

        commit = git("rev-parse", "HEAD")
        tree = git("rev-parse", "HEAD^{tree}")
        status = git("status", "--porcelain", "--untracked-files=all")
        if status:
            preview = "\n".join(status.splitlines()[:20])
            raise RuntimeError(
                "polyglot-benchmark checkout is dirty; refusing to run: "
                f"{preview}"
            )
        metadata.update({"commit": commit, "tree": tree, "dirty": False})
        return metadata

    @staticmethod
    def _declared_solution_files(problem_dir: Path, workdir: Path) -> List[str]:
        """Return solution paths from Exercism metadata, with fixture fallback."""
        config_file = problem_dir / ".meta" / "config.json"
        if config_file.exists():
            try:
                config = json.loads(config_file.read_text())
                solution_files = config.get("files", {}).get("solution", [])
                if isinstance(solution_files, str):
                    solution_files = [solution_files]
                if isinstance(solution_files, list):
                    return [str(path) for path in solution_files]
            except (OSError, json.JSONDecodeError):
                pass

        return sorted(
            str(path.relative_to(workdir))
            for path in workdir.iterdir()
            if path.is_file()
            and path.suffix == ".py"
            and "test" not in path.stem.lower()
        )

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

        prompt = (
            "# Benchmark execution context\n\n"
            f"- Task ID: `{task_id}`\n"
            f"- Required language: `{language}`\n"
            "- Work only in the current working directory.\n"
            "- Modify the provided starter implementation for the required "
            "language and use the provided tests/build files.\n"
            "- Do not inspect or modify files outside the current working "
            "directory, including parent directories, vendor datasets, sibling "
            "tasks, or previous results.\n"
            "- Do not create a solution in another language.\n\n"
            f"{prompt}"
        )

        # Copy ALL files from the problem dir into the workdir root so the
        # language's test runner can find starter + tests + module files.
        # The hidden test files (which encode the expected assertions) are
        # deliberately EXCLUDED so the agent cannot read them; verify()
        # re-injects them at grading time.
        hidden_entries = self._hidden_test_entries(problem_dir, language)
        hidden_rel = [Path(rel) for rel in hidden_entries]

        def _skip(name: str) -> bool:
            child = Path(name)
            return any(child == h or h in child.parents for h in hidden_rel)

        for item in problem_dir.iterdir():
            if item.name == ".docs":
                continue
            if item.name in self.REFERENCE_ARTIFACT_DIRS:
                continue
            if item.name in self.GENERATED_ARTIFACT_DIRS:
                continue
            if _skip(item.name):
                continue
            if item.is_dir():
                def _ignore(current_dir: str, names: list[str]) -> set[str]:
                    current = Path(current_dir).relative_to(problem_dir)
                    return {
                        n
                        for n in names
                        if n in self.GENERATED_ARTIFACT_DIRS
                        or _skip(str(current / n))
                    }

                shutil.copytree(
                    item,
                    workdir / item.name,
                    dirs_exist_ok=True,
                    ignore=_ignore,
                )
            else:
                shutil.copy2(item, workdir / item.name)

        # Keep a host-side snapshot before the agent starts. The verifier uses
        # this snapshot for tests/build metadata and overlays only the declared
        # solution files from the model-authored workdir.
        canonical_dir = workdir.parent / "canonical"
        shutil.rmtree(canonical_dir, ignore_errors=True)
        self._copy_for_verification(workdir, canonical_dir)
        solution_files = self._declared_solution_files(problem_dir, workdir)
        dataset_root = vendor_dir / "polyglot-benchmark"

        return {
            "task_id": task_id,
            "prompt": prompt,
            "language": language,
            "problem": problem,
            "vendor_problem_dir": str(problem_dir),
            "hidden_test_paths": [str(rel) for rel in hidden_rel],
            "model_id": "nvidia/nemotron-3-ultra-550b-a55b",
            "solution_files": solution_files,
            "_canonical_dir": str(canonical_dir),
            "dataset": self._git_dataset_metadata(dataset_root),
        }

    def prepare_agent_dependencies(
        self, task_data: Dict[str, Any], workdir: Path
    ) -> None:
        """Fetch required language dependencies before network isolation."""
        language = task_data.get("language")
        command: list[str] | None = None
        cleanup_path: Path | None = None
        if language in {"javascript", "typescript"} and (
            workdir / "package.json"
        ).exists():
            command = [
                "npm",
                "install",
                "--no-audit",
                "--no-fund",
                "--ignore-scripts",
            ]
        elif language == "java" and (workdir / "gradlew").exists():
            cleanup_path = workdir / ".cospa-resolve.gradle"
            cleanup_path.write_text(
                "allprojects {\n"
                "  tasks.register('cospaResolveDependencies') {\n"
                "    doLast {\n"
                "      configurations.findAll { it.canBeResolved }.each { "
                "it.resolve() }\n"
                "    }\n"
                "  }\n"
                "}\n"
            )
            command = [
                "./gradlew",
                "--no-daemon",
                "--init-script",
                str(cleanup_path),
                "cospaResolveDependencies",
            ]
        elif language == "rust" and (workdir / "Cargo.toml").exists():
            command = ["cargo", "fetch"]
        if command is None:
            return

        try:
            result = run_command(
                command,
                cwd=str(workdir),
                capture_output=True,
                text=True,
                timeout=600,
                env=self._verification_env(),
            )
        finally:
            if cleanup_path is not None:
                cleanup_path.unlink(missing_ok=True)
        if result.returncode != 0:
            output = (result.stdout or "") + (result.stderr or "")
            raise RuntimeError(
                f"Dependency prefetch failed for {language}: {output[-2000:]}"
            )

    def verify(self, task_data: Dict[str, Any], workdir: Path) -> Dict[str, Any]:
        """
        Verify the solution by running tests.

        Detects the language and runs the appropriate test command.
        """
        language = task_data.get("language", "python")
        timeout = task_data.get("timeout", 300)  # 5 min default for tests
        setup_cmds: list[list[str]] = []
        # Canonical snapshots must always be verified from a clean temporary
        # tree, including Python and Go, so model-edited tests/config cannot be
        # used by the grader.
        run_in_temp_copy = bool(task_data.get("_canonical_dir"))
        env = self._verification_env()

        # Re-inject the hidden test files now that the agent has finished.
        # They were kept out of the workdir during the solve to prevent the
        # model from reading the expected assertions (contamination guard).
        self._restore_hidden_tests(task_data, workdir)

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
                    [
                        "npm",
                        "install",
                        "--offline",
                        "--no-audit",
                        "--no-fund",
                        "--ignore-scripts",
                    ]
                )
                cmd = ["npm", "test"]
                run_in_temp_copy = True
            else:
                cmd = ["npx", "jest", "--verbose"]
        elif language == "go":
            if task_data.get("problem") == "counter":
                reject_incorrect = []
                for implementation in (1, 2, 3):
                    log_path = f"/tmp/cospa-counter-{implementation}.log"
                    reject_incorrect.append(
                        f"if COUNTER_IMPL={implementation} go test ./... -v "
                        f"-timeout 5m >{log_path} 2>&1; then "
                        f"cat {log_path}; "
                        f"echo 'COUNTER_IMPL={implementation} unexpectedly passed' >&2; "
                        "exit 1; "
                        "else "
                        f"echo 'COUNTER_IMPL={implementation} correctly rejected'; "
                        "fi"
                    )
                cmd = [
                    "bash",
                    "-c",
                    "; ".join(reject_incorrect)
                    + "; COUNTER_IMPL=4 go test ./... -v -timeout 5m",
                ]
            else:
                cmd = ["go", "test", "./...", "-v", "-timeout", "5m"]
        elif language == "java":
            gradle_cmd = "./gradlew" if (workdir / "gradlew").exists() else "gradle"
            cmd = [gradle_cmd, "test", "--info", "--offline"]
            run_in_temp_copy = True
        elif language == "rust":
            cmd = ["cargo", "test", "--verbose", "--offline"]
            run_in_temp_copy = True
        elif language == "c" or language == "cpp":
            # Try cmake + build + test. Do not append a shell fallback such as
            # `|| echo ...`: that masks nonzero build/test exits as success.
            problem = task_data.get("problem")
            source_dir = problem or "."
            run_in_temp_copy = True
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
                    self._copy_canonical_for_verification(
                        task_data, workdir, verify_dir
                    )
                    if language in {"c", "cpp"} and task_data.get("problem"):
                        source_link = verify_dir / task_data["problem"]
                        if source_link.is_dir() and not source_link.is_symlink():
                            shutil.rmtree(source_link)
                        elif source_link.exists() or source_link.is_symlink():
                            source_link.unlink()
                        source_link.symlink_to(".", target_is_directory=True)
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
                sandbox_workdir=workdir,
                sandbox_name="verifier",
                sandbox_model_access=False,
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
            sandbox_workdir=workdir,
            sandbox_name="verifier",
            sandbox_model_access=False,
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
    def _restore_hidden_tests(cls, task_data: Dict[str, Any], workdir: Path) -> None:
        """Re-inject hidden test files from the vendor problem dir at grading time.

        The hidden tests were excluded from the agent's workdir during the solve
        (see materialize_task). verify() runs after the agent has finished, so
        restoring them here lets the grader run the real assertions without
        ever exposing them to the model.
        """
        problem_dir = task_data.get("vendor_problem_dir")
        rels = task_data.get("hidden_test_paths") or []
        if not problem_dir or not rels:
            return
        problem_dir = Path(problem_dir)
        for rel in rels:
            src = problem_dir / rel
            dst = workdir / rel
            if src.is_dir():
                shutil.copytree(src, dst, dirs_exist_ok=True)
            elif src.exists():
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
    @classmethod
    def _copy_canonical_for_verification(
        cls, task_data: Dict[str, Any], workdir: Path, dest: Path
    ) -> None:
        """Copy canonical evaluator inputs and overlay model solution files."""
        canonical_value = task_data.get("_canonical_dir")
        if not canonical_value:
            cls._copy_for_verification(workdir, dest)
            return

        canonical_dir = Path(canonical_value)
        if not canonical_dir.is_dir():
            raise ValueError(f"Canonical verifier snapshot is missing: {canonical_dir}")
        cls._copy_for_verification(canonical_dir, dest)

        for relative in task_data.get("solution_files", []):
            solution = Path(relative)
            if solution.is_absolute() or ".." in solution.parts:
                raise ValueError(f"Invalid declared solution path: {relative}")
            source = workdir / solution
            target = dest / solution
            if not source.is_file():
                raise ValueError(f"Declared solution file is missing: {source}")
            try:
                source.resolve().relative_to(workdir.resolve())
            except ValueError as exc:
                raise ValueError(
                    f"Refusing solution symlink outside trial workdir: {source}"
                ) from exc
            target.parent.mkdir(parents=True, exist_ok=True)
            target.unlink(missing_ok=True)
            shutil.copy2(source, target)

    @classmethod
    def _copy_for_verification(cls, source: Path, dest: Path) -> None:
        source_root = source.resolve()
        for path in source.rglob("*"):
            if not path.is_symlink():
                continue
            try:
                path.resolve().relative_to(source_root)
            except ValueError as exc:
                raise ValueError(
                    f"Refusing symlink outside trial workdir: {path}"
                ) from exc

        def ignore(_dir: str, names: list[str]) -> set[str]:
            return set(names) & cls.GENERATED_ARTIFACT_DIRS

        shutil.copytree(source, dest, ignore=ignore, symlinks=True)

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
