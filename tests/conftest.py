"""
Shared pytest fixtures for the coding-eval test suite.

Provides `make_polyglot_problem` which builds a problem in the REAL
polyglot-benchmark (Exercism) layout, so tests don't regress to the toy
`problems/<lang>/<problem>/{problem.txt, starter/, tests/}` shape.
"""

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def _write_real_polyglot_problem(
    vendor_dir: Path,
    language: str,
    problem: str,
    *,
    instructions: str = "Solve the problem.",
    starter_name: str = None,
    starter_content: str = "def solution():\n    pass\n",
    test_content: str = "def test_solution():\n    assert True\n",
):
    """Create a polyglot-benchmark-shaped problem dir under vendor_dir.

    Layout: vendor_dir/polyglot-benchmark/<lang>/exercises/practice/<problem>/
        .docs/instructions.md
        <starter_name>.<ext>
        <starter_name>_test.<ext>
    """
    ext = {"python": "py", "go": "go", "rust": "rs",
           "javascript": "js", "cpp": "cpp", "java": "java"}.get(language, "txt")
    # Exercism/python uses snake_case; others use the dasherized problem name.
    if starter_name is None:
        starter_name = problem.replace("-", "_") if language == "python" else problem

    pdir = (
        vendor_dir
        / "polyglot-benchmark"
        / language
        / "exercises"
        / "practice"
        / problem
    )
    pdir.mkdir(parents=True)
    (pdir / ".docs").mkdir()
    (pdir / ".docs" / "instructions.md").write_text(instructions)
    (pdir / f"{starter_name}.{ext}").write_text(starter_content)
    (pdir / f"{starter_name}_test.{ext}").write_text(test_content)
    return pdir


@pytest.fixture
def make_polyglot_problem():
    """Fixture returning the _write_real_polyglot_problem helper."""
    return _write_real_polyglot_problem


@pytest.fixture
def polyglot_vendor(tmp_path):
    """A vendor dir pre-seeded with one real-shaped python/two-fer problem."""
    vendor_dir = tmp_path / "vendor"
    _write_real_polyglot_problem(
        vendor_dir, "python", "two-fer",
        instructions="# Two Fer\nImplement two-fer.",
        starter_name="two_fer",
        starter_content="def two_fer(name=None):\n    pass\n",
        test_content=(
            "from two_fer import two_fer\n"
            "def test_two_fer():\n"
            "    assert two_fer() == 'One for you, one for me.'\n"
        ),
    )
    return vendor_dir
