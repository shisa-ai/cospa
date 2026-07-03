"""
Tests for view-scores/server.py against a real encoded result tree.

These tests exercise the viewer end-to-end against a tree written by the
runner with model IDs and task IDs that BOTH contain slashes (the exact
shape called out in ORNITH-CODER-REVIEW.md findings #3, #13 and audit A).
"""

import json
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from harness.path_utils import encode_model_path, encode_task_path


def _write_trial(trial_dir: Path, *, passed: bool, wall_clock=10.0, exit_code=0,
                 test_count=1, adapter_failed=False, task_id="python/hello"):
    """Write a manifest.json + verdict.json pair into a trial dir."""
    trial_dir.mkdir(parents=True, exist_ok=True)
    (trial_dir / "manifest.json").write_text(json.dumps({
        "model": {"id": "nvidia/nemotron-3-ultra-550b-a55b",
                  "provider": "nvidia",
                  "served_model": "nvidia/nemotron-3-ultra-550b-a55b"},
        "adapter": {"id": "PiVanillaAdapter", "version": "vanilla"},
        "suite": {"id": "AiderPolyglotSuite", "task_id": task_id},
        "trial": 1,
        "timing": {"wall_clock_seconds": wall_clock},
        "exit_code": exit_code,
    }, indent=2))
    (trial_dir / "verdict.json").write_text(json.dumps({
        "passed": passed,
        "test_count": test_count,
        "grader_output": "ok" if passed else "fail",
        "exit_code": exit_code,
        "adapter_failed": adapter_failed,
    }, indent=2))


def _build_encoded_tree(results_dir: Path):
    """Build a results tree with encoded model/task IDs containing slashes.

    Layout (matches what harness/runner.run_trial writes):
        results/<encoded_model>/<adapter>/<suite>/<encoded_task>/trial-<k>/
    """
    model_id = "nvidia/nemotron-3-ultra-550b-a55b"
    adapter = "pi_vanilla"
    suite = "aider_polyglot"
    task_id = "python/hello"

    base = (
        results_dir
        / encode_model_path(model_id)
        / adapter
        / suite
        / encode_task_path(task_id)
    )

    # k=3: 2 pass, 1 fail -> majority pass
    _write_trial(base / "trial-1", passed=True)
    _write_trial(base / "trial-2", passed=True)
    _write_trial(base / "trial-3", passed=False)

    # A second task that fails majority
    task_id2 = "python/fizz"
    base2 = (
        results_dir
        / encode_model_path(model_id)
        / adapter
        / suite
        / encode_task_path(task_id2)
    )
    _write_trial(base2 / "trial-1", passed=False, task_id=task_id2)
    _write_trial(base2 / "trial-2", passed=False, task_id=task_id2)

    return model_id, adapter, suite, task_id, task_id2


def _make_handler(results_dir: Path):
    """Instantiate a ScoreHandler whose RESULTS_DIR points at a temp tree.

    The viewer lives at view-scores/server.py (hyphenated dir, not a valid
    Python package name), so we load it by path with importlib.
    """
    import importlib.util
    server_path = PROJECT_ROOT / "view-scores" / "server.py"
    spec = importlib.util.spec_from_file_location("view_scores_server", server_path)
    server_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(server_mod)
    server_mod.RESULTS_DIR = results_dir

    h = server_mod.ScoreHandler.__new__(server_mod.ScoreHandler)
    return h, server_mod


def test_get_scores_reads_encoded_tree():
    """get_scores() must aggregate an encoded tree with slashed model/task IDs."""
    with tempfile.TemporaryDirectory() as tmp:
        results_dir = Path(tmp) / "results"
        results_dir.mkdir()
        model_id, adapter, suite, task_id, task_id2 = _build_encoded_tree(results_dir)

        h, _ = _make_handler(results_dir)
        scores = h.get_scores()

    assert len(scores) == 1, f"expected one (model,adapter,suite) row, got {scores}"
    row = scores[0]
    assert row["model"] == model_id, row
    assert row["adapter"] == adapter, row
    assert row["suite"] == suite, row
    # 2 tasks, one passed majority (2/3), one failed majority (0/2)
    assert row["total_tasks"] == 2, row
    assert row["passed_tasks"] == 1, row
    assert 0 < row["pass_rate"] <= 100, row


def test_get_scores_does_not_raise_nameerror():
    """Regression: get_scores() must not raise NameError on decode_task_path."""
    with tempfile.TemporaryDirectory() as tmp:
        results_dir = Path(tmp) / "results"
        results_dir.mkdir()
        _build_encoded_tree(results_dir)
        h, _ = _make_handler(results_dir)
        # Must not raise
        scores = h.get_scores()
    assert isinstance(scores, list)


def test_generate_html_renders_rows_without_keyerror():
    """generate_html() must not crash on total/passed key mismatch."""
    with tempfile.TemporaryDirectory() as tmp:
        results_dir = Path(tmp) / "results"
        results_dir.mkdir()
        _build_encoded_tree(results_dir)
        h, _ = _make_handler(results_dir)
        html = h.generate_html()
    assert "<table>" in html
    assert "nvidia/nemotron-3-ultra-550b-a55b" in html
    assert "pi_vanilla" in html


def test_get_task_details_with_encoded_model_and_task():
    """get_task_details() must locate the encoded dir and decode task IDs."""
    with tempfile.TemporaryDirectory() as tmp:
        results_dir = Path(tmp) / "results"
        results_dir.mkdir()
        model_id, adapter, suite, task_id, task_id2 = _build_encoded_tree(results_dir)

        h, server_mod = _make_handler(results_dir)
        # The viewer receives the *encoded* model via the URL query string
        encoded_model = encode_model_path(model_id)
        details = h.get_task_details(encoded_model, adapter, suite)

    assert "error" not in details, details
    assert details["model"] == model_id, details
    tasks = {t["task_id"]: t for t in details["tasks"]}
    assert task_id in tasks, tasks
    assert task_id2 in tasks, tasks
    # task_id: 2/3 pass -> majority pass
    assert tasks[task_id]["passed"] is True, tasks[task_id]
    assert tasks[task_id]["pass_at_k"] == "2/3"
    # task_id2: 0/2 pass -> majority fail
    assert tasks[task_id2]["passed"] is False, tasks[task_id2]


def test_get_scores_empty_when_no_results():
    """get_scores() returns [] gracefully when results dir is empty/absent."""
    with tempfile.TemporaryDirectory() as tmp:
        h, _ = _make_handler(Path(tmp) / "does-not-exist")
        assert h.get_scores() == []
