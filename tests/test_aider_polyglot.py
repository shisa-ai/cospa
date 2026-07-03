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

import sys
import tempfile
from pathlib import Path

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
