"""
Tests for the Aider Polyglot suite against the REAL polyglot-benchmark layout.

The real benchmark (https://github.com/Aider-AI/polyglot-benchmark) uses the
Exercism directory layout:

    <lang>/exercises/practice/<problem>/
        .docs/instructions.md       <- the problem statement
        <problem>.<ext>             <- starter file (functions with `pass`)
        <problem>_test.<ext>        <- test file

The previous suite assumed a fake `problems/<lang>/<problem>/{problem.txt,
starter/, tests/}` shape and only worked against a toy `python/hello` task.

These tests build a minimal but real-shaped polyglot tree and exercise the
suite against it.
"""

import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from harness.suites.aider_polyglot import AiderPolyglotSuite


def _make_real_polyglot_problem(vendor_dir: Path, lang: str, problem: str,
                                 instructions: str, starter: str, test: str,
                                 extra_files=None):
    """Create a problem dir in the real Exercism layout."""
    pdir = vendor_dir / "polyglot-benchmark" / lang / "exercises" / "practice" / problem
    pdir.mkdir(parents=True)
    (pdir / ".docs").mkdir()
    (pdir / ".docs" / "instructions.md").write_text(instructions)

    ext = {"python": "py", "go": "go", "rust": "rs", "javascript": "js"}.get(lang, "txt")
    starter_name = problem.replace("-", "_") if lang == "python" else problem
    test_name = f"{starter_name}_test"

    (pdir / f"{starter_name}.{ext}").write_text(starter)
    (pdir / f"{test_name}.{ext}").write_text(test)
    if extra_files:
        for name, content in extra_files.items():
            (pdir / name).write_text(content)
    return pdir


def test_get_task_ids_finds_real_polyglot_layout():
    """get_task_ids must discover the real Exercism layout under polyglot-benchmark/."""
    suite = AiderPolyglotSuite()
    with tempfile.TemporaryDirectory() as tmp:
        vendor_dir = Path(tmp) / "vendor"
        _make_real_polyglot_problem(
            vendor_dir, "python", "two-fer",
            instructions="# Two Fer\nImplement two-fer.",
            starter="def two_fer(name=None):\n    pass\n",
            test="from two_fer import two_fer\ndef test_two_fer():\n    assert two_fer() == 'One for you, one for me.'\n",
        )
        ids = suite.get_task_ids(vendor_dir)
    assert "python/two-fer" in ids, ids


def test_materialize_task_real_layout_copies_starter_and_tests():
    """materialize_task must copy starter + test files and extract the prompt."""
    suite = AiderPolyglotSuite()
    with tempfile.TemporaryDirectory() as tmp:
        vendor_dir = Path(tmp) / "vendor"
        _make_real_polyglot_problem(
            vendor_dir, "python", "two-fer",
            instructions="# Two Fer\nImplement two-fer.",
            starter="def two_fer(name=None):\n    pass\n",
            test="from two_fer import two_fer\ndef test_two_fer():\n    assert True\n",
        )
        workdir = Path(tmp) / "workdir"
        td = suite.materialize_task("python/two-fer", workdir, vendor_dir)

        assert "Two Fer" in td["prompt"], td["prompt"]
        assert td["language"] == "python"
        assert td["problem"] == "two-fer"
        # Starter and test files must be present in the workdir
        assert (workdir / "two_fer.py").exists(), list(workdir.iterdir())
        assert (workdir / "two_fer_test.py").exists(), list(workdir.iterdir())


@pytest.mark.parametrize(
    "language",
    ["cpp", "go", "java", "javascript", "python", "rust"],
)
def test_materialize_task_prompt_pins_language_and_workdir(language):
    """Agents must not solve a sibling language or mutate shared datasets."""
    suite = AiderPolyglotSuite()
    with tempfile.TemporaryDirectory() as tmp:
        vendor_dir = Path(tmp) / "vendor"
        _make_real_polyglot_problem(
            vendor_dir,
            language,
            "all-your-base",
            instructions="# Instructions\nConvert between bases.",
            starter="starter implementation\n",
            test="exercise tests\n",
        )
        workdir = Path(tmp) / "workdir"
        task = suite.materialize_task(
            f"{language}/all-your-base", workdir, vendor_dir
        )

    prompt = task["prompt"]
    assert f"Task ID: `{language}/all-your-base`" in prompt
    assert f"Required language: `{language}`" in prompt
    assert "Work only in the current working directory" in prompt
    assert "Do not inspect or modify files outside" in prompt
    assert "Do not create a solution in another language" in prompt
    assert "# Instructions\nConvert between bases." in prompt


@pytest.mark.parametrize(
    "language",
    ["cpp", "go", "java", "javascript", "python", "rust"],
)
def test_materialize_task_excludes_reference_solutions(language):
    """Official examples and approach guides must not leak into trials."""
    suite = AiderPolyglotSuite()
    with tempfile.TemporaryDirectory() as tmp:
        vendor_dir = Path(tmp) / "vendor"
        problem_dir = _make_real_polyglot_problem(
            vendor_dir,
            language,
            "all-your-base",
            instructions="Convert between bases.",
            starter="starter implementation\n",
            test="exercise tests\n",
        )
        (problem_dir / ".meta").mkdir()
        (problem_dir / ".meta" / "example.txt").write_text(
            "official reference solution\n"
        )
        (problem_dir / ".approaches").mkdir()
        (problem_dir / ".approaches" / "in-sequence.md").write_text(
            "complete solution guide\n"
        )

        workdir = Path(tmp) / "workdir"
        suite.materialize_task(
            f"{language}/all-your-base", workdir, vendor_dir
        )

        assert not (workdir / ".meta").exists()
        assert not (workdir / ".approaches").exists()


def test_materialize_task_skips_generated_build_artifacts():
    """Vendored build caches must not poison fresh trial workdirs."""
    suite = AiderPolyglotSuite()
    with tempfile.TemporaryDirectory() as tmp:
        vendor_dir = Path(tmp) / "vendor"
        pdir = _make_real_polyglot_problem(
            vendor_dir, "cpp", "bank-account",
            instructions="# Bank Account\nImplement bank-account.",
            starter="class bank_account {};",
            test="int main() { return 0; }\n",
        )
        build_dir = pdir / "build"
        build_dir.mkdir()
        (build_dir / "CMakeCache.txt").write_text(
            f"CMAKE_HOME_DIRECTORY:INTERNAL={pdir}\n"
        )

        workdir = Path(tmp) / "workdir"
        suite.materialize_task("cpp/bank-account", workdir, vendor_dir)

        assert not (workdir / "build").exists(), list(workdir.iterdir())


def test_materialize_task_handles_dash_to_underscore_for_python():
    """python problem 'hello-world' starter is 'hello_world.py'."""
    suite = AiderPolyglotSuite()
    with tempfile.TemporaryDirectory() as tmp:
        vendor_dir = Path(tmp) / "vendor"
        _make_real_polyglot_problem(
            vendor_dir, "python", "hello-world",
            instructions="Say hello.",
            starter="def hello():\n    pass\n",
            test="from hello import hello\ndef test_hello():\n    assert True\n",
        )
        workdir = Path(tmp) / "workdir"
        td = suite.materialize_task("python/hello-world", workdir, vendor_dir)
        assert (workdir / "hello_world.py").exists() or (workdir / "hello.py").exists()


def test_setup_sh_uses_real_benchmark_and_fails_loudly_when_missing(monkeypatch=None):
    """setup.sh must clone polyglot-benchmark (not aider-polyglot) and must
    NOT silently create a placeholder on failure."""
    # We assert against the script's text: it must reference the real repo
    # and must not contain the silent-placeholder fallback.
    setup_path = PROJECT_ROOT / "scripts" / "setup.sh"
    text = setup_path.read_text()
    assert "polyglot-benchmark" in text, (
        "setup.sh must clone Aider-AI/polyglot-benchmark (the real benchmark)"
    )
    # The silent placeholder fallback is the exact failure mode from the audit
    assert "creating placeholder" not in text.lower(), (
        "setup.sh must not silently create a placeholder when the clone fails"
    )
    # And it must exit nonzero on clone failure rather than continuing
    assert "exit 1" in text, "setup.sh must exit 1 on dataset clone failure"


@pytest.mark.parametrize(
    ("fixture_name", "expected_count"),
    [
        ("pytest_verbose_pass.txt", 2),
        ("go_test_verbose_pass.txt", 2),
        ("cargo_test_pass.txt", 2),
        ("jest_verbose_pass.txt", 2),
        ("gradle_test_pass.txt", 2),
        ("ctest_pass.txt", 2),
    ],
)
def test_count_tests_counts_real_language_runner_outputs(fixture_name, expected_count):
    """Successful language runner output must not be marked failed as 0 tests."""
    suite = AiderPolyglotSuite()
    output = (PROJECT_ROOT / "tests" / "fixtures" / fixture_name).read_text()

    assert suite._count_tests(output) == expected_count


def test_count_tests_counts_later_rust_test_binary_when_first_has_zero_tests():
    """Cargo may report a zero-test crate before the real exercise tests."""
    suite = AiderPolyglotSuite()
    output = """
running 0 tests

test result: ok. 0 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out;

running 12 tests
test accumulate_empty ... ok

test result: ok. 1 passed; 0 failed; 11 ignored; 0 measured; 0 filtered out;
"""

    assert suite._count_tests(output) == 1


def test_run_verifier_commands_counts_junit_xml_when_stdout_has_no_count():
    """Gradle may only expose the number of executed tests in JUnit XML."""
    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)
        xml_dir = workdir / "build" / "test-results" / "test"
        xml_dir.mkdir(parents=True)
        (xml_dir / "TEST-AffineCipherTest.xml").write_text(
            '<testsuite name="AffineCipherTest" tests="16" skipped="15" '
            'failures="0" errors="0"></testsuite>'
        )

        with patch("harness.suites.aider_polyglot.run_command") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=["./gradlew", "test"],
                returncode=0,
                stdout="BUILD SUCCESSFUL in 1s\n",
                stderr="",
            )
            verdict = AiderPolyglotSuite._run_verifier_commands(
                [],
                ["./gradlew", "test"],
                workdir,
                timeout=1,
                env={},
            )

    assert verdict["passed"] is True
    assert verdict["test_count"] == 16


def test_verify_cpp_command_does_not_mask_test_runner_failures():
    """The C++ verifier must preserve nonzero build/test exit codes."""
    suite = AiderPolyglotSuite()
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = list(cmd)
        return subprocess.CompletedProcess(
            args=cmd,
            returncode=1,
            stdout="0 tests passed, 2 tests failed out of 2\n",
            stderr="",
        )

    with tempfile.TemporaryDirectory() as tmp:
        with patch("harness.suites.aider_polyglot.run_command", side_effect=fake_run):
            verdict = suite.verify({"language": "cpp", "timeout": 1}, Path(tmp))

    shell_cmd = captured["cmd"][-1]
    assert "||" not in shell_cmd, shell_cmd
    assert verdict["passed"] is False
    assert verdict["exit_code"] == 1


def test_verify_cpp_runs_exercism_cmake_test_target():
    """C++ exercises expose test_<exercise> targets, not build/test."""
    suite = AiderPolyglotSuite()

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(
            args=cmd,
            returncode=0,
            stdout="All tests passed (12 assertions in 3 test cases)\n",
            stderr="",
        )

    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "CMakeLists.txt").write_text("add_custom_target(test_allergies)\n")
        with patch("harness.suites.aider_polyglot.run_command", side_effect=fake_run) as mock_run:
            verdict = suite.verify(
                {"language": "cpp", "problem": "allergies", "timeout": 1},
                Path(tmp),
            )

    shell_cmd = mock_run.call_args[0][0][-1]
    assert "./build/test" not in shell_cmd, shell_cmd
    assert "cmake -S allergies -B build" in shell_cmd, shell_cmd
    assert "cmake --build build --target test_allergies" in shell_cmd, shell_cmd
    assert verdict["passed"] is True
    assert verdict["test_count"] == 3


def test_verify_cpp_uses_clean_copy_without_agent_build_cache():
    """A sandbox /mnt CMake cache must not poison host-side grading."""
    suite = AiderPolyglotSuite()
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cwd"] = Path(kwargs["cwd"])
        captured["cache_visible"] = (
            captured["cwd"] / "build" / "CMakeCache.txt"
        ).exists()
        return subprocess.CompletedProcess(
            args=cmd,
            returncode=0,
            stdout="All tests passed (17 assertions in 1 test case)\n",
            stderr="",
        )

    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp) / "workdir"
        workdir.mkdir()
        (workdir / "CMakeLists.txt").write_text(
            "add_custom_target(test_all-your-base)\n"
        )
        (workdir / "all_your_base.cpp").write_text("// solution\n")
        (workdir / "build").mkdir()
        (workdir / "build" / "CMakeCache.txt").write_text(
            "CMAKE_HOME_DIRECTORY:INTERNAL=/mnt\n"
        )

        with patch(
            "harness.suites.aider_polyglot.run_command", side_effect=fake_run
        ):
            verdict = suite.verify(
                {
                    "language": "cpp",
                    "problem": "all-your-base",
                    "timeout": 1,
                },
                workdir,
            )

        assert captured["cwd"] != workdir
        assert captured["cache_visible"] is False
        assert verdict["passed"] is True


def test_verify_cpp_rejects_symlinks_outside_trial():
    """Host-side grading must not follow a guessed link into shared data."""
    suite = AiderPolyglotSuite()

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        workdir = tmp / "workdir"
        workdir.mkdir()
        (workdir / "CMakeLists.txt").write_text(
            "add_custom_target(test_all-your-base)\n"
        )
        reference_solution = tmp / "official-example.cpp"
        reference_solution.write_text("// official solution\n")
        (workdir / "all_your_base.cpp").symlink_to(reference_solution)

        with patch(
            "harness.suites.aider_polyglot.run_command",
            return_value=subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout="All tests passed (17 assertions in 1 test case)\n",
                stderr="",
            ),
        ):
            verdict = suite.verify(
                {
                    "language": "cpp",
                    "problem": "all-your-base",
                    "timeout": 1,
                },
                workdir,
            )

    assert verdict["passed"] is False
    assert "outside trial workdir" in verdict["grader_output"]


def test_verify_java_prefers_checked_in_gradle_wrapper():
    """Java exercises vendor gradlew, so clean machines do not need global gradle."""
    suite = AiderPolyglotSuite()

    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)
        (workdir / "gradlew").write_text("#!/usr/bin/env sh\n")
        with patch("harness.suites.aider_polyglot.run_command") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=["./gradlew"],
                returncode=0,
                stdout="3 tests completed, 0 failed\n",
                stderr="",
            )
            verdict = suite.verify({"language": "java", "timeout": 1}, workdir)

    assert mock_run.call_args[0][0][:2] == ["./gradlew", "test"]
    assert verdict["passed"] is True
    assert verdict["test_count"] == 3


def test_verify_python_targets_copied_test_files():
    """Python verification must not let the repo pyproject collect 0 tests."""
    suite = AiderPolyglotSuite()

    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)
        (workdir / "affine_cipher_test.py").write_text("def test_ok(): pass\n")
        with patch("harness.suites.aider_polyglot.run_command") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=["python"],
                returncode=0,
                stdout="1 passed in 0.01s\n",
                stderr="",
            )
            verdict = suite.verify({"language": "python", "timeout": 1}, workdir)

    cmd = mock_run.call_args[0][0]
    assert "affine_cipher_test.py" in cmd, cmd
    assert verdict["passed"] is True
    assert verdict["test_count"] == 1


def test_verify_java_drops_invalid_java_home(monkeypatch):
    """A stale host JAVA_HOME must not make every Java exercise fail."""
    suite = AiderPolyglotSuite()
    monkeypatch.setenv("JAVA_HOME", "/definitely/not/a/jdk")

    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)
        (workdir / "gradlew").write_text("#!/usr/bin/env sh\n")
        with patch("harness.suites.aider_polyglot.run_command") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=["./gradlew"],
                returncode=0,
                stdout="3 tests completed, 0 failed\n",
                stderr="",
            )
            verdict = suite.verify({"language": "java", "timeout": 1}, workdir)

    env = mock_run.call_args.kwargs["env"]
    assert "JAVA_HOME" not in env
    assert verdict["passed"] is True


def test_verify_javascript_installs_exercise_dependencies_first():
    """Jest exercises need their package.json devDependencies installed."""
    suite = AiderPolyglotSuite()

    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)
        (workdir / "package.json").write_text('{"scripts":{"test":"jest ./*"}}\n')
        with patch("harness.suites.aider_polyglot.run_command") as mock_run:
            mock_run.side_effect = [
                subprocess.CompletedProcess(
                    args=["npm", "install"],
                    returncode=0,
                    stdout="installed\n",
                    stderr="",
                ),
                subprocess.CompletedProcess(
                    args=["npm", "test"],
                    returncode=0,
                    stdout="Tests:       1 passed, 1 total\n",
                    stderr="",
                ),
            ]
            verdict = suite.verify({"language": "javascript", "timeout": 1}, workdir)

    first_cmd = mock_run.call_args_list[0].args[0]
    second_cmd = mock_run.call_args_list[1].args[0]
    assert first_cmd[:2] == ["npm", "install"]
    assert second_cmd == ["npm", "test"]
    assert verdict["passed"] is True
    assert verdict["test_count"] == 1


def test_verify_rust_uses_short_temp_copy_for_cargo():
    """Cargo/linker can fail under deeply encoded result paths."""
    suite = AiderPolyglotSuite()

    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp) / ("deep-" * 20)
        workdir.mkdir(parents=True)
        (workdir / "Cargo.toml").write_text("[package]\nname='x'\nversion='0.0.0'\nedition='2021'\n")
        (workdir / "src").mkdir()
        (workdir / "src" / "lib.rs").write_text("")
        with patch("harness.suites.aider_polyglot.run_command") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=["cargo"],
                returncode=0,
                stdout="test result: ok. 1 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out;\n",
                stderr="",
            )
            verdict = suite.verify({"language": "rust", "timeout": 1}, workdir)

    cargo_cwd = Path(mock_run.call_args.kwargs["cwd"])
    assert cargo_cwd != workdir
    assert str(cargo_cwd).startswith("/tmp/")
    assert verdict["passed"] is True
