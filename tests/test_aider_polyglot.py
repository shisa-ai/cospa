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
        with patch("subprocess.run", side_effect=fake_run):
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
        with patch("subprocess.run", side_effect=fake_run) as mock_run:
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


def test_verify_java_prefers_checked_in_gradle_wrapper():
    """Java exercises vendor gradlew, so clean machines do not need global gradle."""
    suite = AiderPolyglotSuite()

    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)
        (workdir / "gradlew").write_text("#!/usr/bin/env sh\n")
        with patch("subprocess.run") as mock_run:
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
