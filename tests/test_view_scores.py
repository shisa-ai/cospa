"""
Tests for view-scores/server.py against a real encoded result tree.

These tests exercise the viewer end-to-end against a tree written by the
runner with model IDs and task IDs that BOTH contain slashes (the exact
shape called out in ORNITH-CODER-REVIEW.md findings #3, #13 and audit A).
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from harness.path_utils import encode_model_path, encode_task_path


def _write_trial(trial_dir: Path, *, passed: bool, wall_clock=10.0, exit_code=0,
                 test_count=1, adapter_failed=False, task_id="python/hello",
                 pending=False, model_id="nvidia/nemotron-3-ultra-550b-a55b",
                 token_usage=None, model_cost=None):
    """Write a manifest.json + verdict.json pair into a trial dir."""
    trial_dir.mkdir(parents=True, exist_ok=True)
    (trial_dir / "manifest.json").write_text(json.dumps({
        "model": {
            "id": model_id,
            "provider": model_id.split("/")[0],
            "served_model": model_id,
            **({"cost": model_cost} if model_cost is not None else {}),
        },
        "adapter": {"id": "PiVanillaAdapter", "version": "vanilla"},
        "suite": {"id": "AiderPolyglotSuite", "task_id": task_id},
        "trial": 1,
        "timing": {"wall_clock_seconds": wall_clock},
        "token_usage": token_usage or {},
        "exit_code": exit_code,
    }, indent=2))
    (trial_dir / "verdict.json").write_text(json.dumps({
        "passed": passed,
        "test_count": test_count,
        "grader_output": "ok" if passed else "fail",
        "exit_code": exit_code,
        "adapter_failed": adapter_failed,
        "pending": pending,
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


def _write_single_row(
    results_dir: Path,
    *,
    model_id="local/ornith-1.0-35b",
    adapter="pi_vanilla",
    suite="aider_polyglot",
    task_id="python/hello",
    passed=True,
    wall_clock=12.0,
):
    base = (
        results_dir
        / encode_model_path(model_id)
        / adapter
        / suite
        / encode_task_path(task_id)
    )
    _write_trial(
        base / "trial-1",
        passed=passed,
        wall_clock=wall_clock,
        task_id=task_id,
        model_id=model_id,
    )
    return model_id, adapter, suite, task_id


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


def test_server_adds_project_root_to_pythonpath_for_direct_launch():
    """python view-scores/server.py must be able to import harness.*."""
    import importlib.util

    root = str(PROJECT_ROOT)
    original_path = list(sys.path)
    try:
        sys.path[:] = [entry for entry in sys.path if entry != root]
        server_path = PROJECT_ROOT / "view-scores" / "server.py"
        spec = importlib.util.spec_from_file_location(
            "view_scores_server_direct_launch_test",
            server_path,
        )
        server_mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(server_mod)
        assert root in sys.path
    finally:
        sys.path[:] = original_path


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


def test_get_scores_reads_named_run_wrapper_tree():
    """Named runs may live under results/<run-label>/<encoded-model>/..."""
    with tempfile.TemporaryDirectory() as tmp:
        results_dir = Path(tmp) / "results"
        wrapped_results = results_dir / "ornith-high-terminal-bench"
        wrapped_results.mkdir(parents=True)
        model_id, adapter, suite, task_id, task_id2 = _build_encoded_tree(
            wrapped_results
        )

        h, server_mod = _make_handler(results_dir)
        scores = h.get_scores()
        details = h.get_task_details(
            encode_model_path(model_id),
            adapter,
            suite,
        )

    assert len(scores) == 1, scores
    assert scores[0]["model"] == model_id, scores
    assert scores[0]["total_tasks"] == 2, scores
    assert "error" not in details, details
    assert {task["task_id"] for task in details["tasks"]} == {task_id, task_id2}


def test_get_scores_hides_smoke_runs_by_default_and_all_restores_them():
    """Default terminal view should focus on real runs, with --all for smoke."""
    with tempfile.TemporaryDirectory() as tmp:
        results_dir = Path(tmp) / "results"
        _write_single_row(
            results_dir / "e2e-smoke-terminal-bench",
            adapter="pi_vanilla",
            suite="terminal_bench",
            task_id="hello-world",
        )
        _write_single_row(
            results_dir / "runs" / "ornith-high-20260704",
            adapter="pi_devstack",
            suite="aider_polyglot",
            task_id="python/hello",
        )

        h, _ = _make_handler(results_dir)
        default_scores = h.get_scores()
        all_scores = h.get_scores(include_smoke=True)

    assert {row["adapter"] for row in default_scores} == {"pi_devstack"}
    assert {row["adapter"] for row in all_scores} == {"pi_vanilla", "pi_devstack"}


def test_get_scores_supports_filter_and_exclude_patterns():
    """Pattern filters should operate over run/model/adapter/suite/task text."""
    with tempfile.TemporaryDirectory() as tmp:
        results_dir = Path(tmp) / "results"
        _write_single_row(
            results_dir / "runs" / "ornith-high-20260704",
            adapter="pi_vanilla",
            task_id="python/hello",
        )
        _write_single_row(
            results_dir / "runs" / "ornith-high-20260704",
            adapter="little_coder",
            task_id="python/fizz",
        )
        _write_single_row(
            results_dir / "runs" / "glm-default-20260704",
            model_id="zai/glm-5.2",
            adapter="pi_devstack",
            task_id="python/hello",
        )

        h, _ = _make_handler(results_dir)
        filtered = h.get_scores(filters=["little"])
        excluded = h.get_scores(excludes=["vanilla|devstack"])
        run_filtered = h.get_scores(filters=["ornith-high"], excludes=["vanilla"])

    assert [row["adapter"] for row in filtered] == ["little_coder"]
    assert [row["adapter"] for row in excluded] == ["little_coder"]
    assert [row["adapter"] for row in run_filtered] == ["little_coder"]


def test_get_scores_aggregates_token_usage_and_estimated_cost():
    """Verbose rows should have token totals and best-effort USD cost."""
    with tempfile.TemporaryDirectory() as tmp:
        results_dir = Path(tmp) / "results"
        model_id = "priced/model"
        adapter = "pi_vanilla"
        suite = "aider_polyglot"
        task_id = "python/hello"
        base = (
            results_dir
            / "runs"
            / "priced-run"
            / encode_model_path(model_id)
            / adapter
            / suite
            / encode_task_path(task_id)
        )
        _write_trial(
            base / "trial-1",
            passed=True,
            model_id=model_id,
            task_id=task_id,
            token_usage={
                "prompt_tokens": 1_000_000,
                "completion_tokens": 500_000,
                "cached_tokens": 250_000,
                "cache_creation_tokens": 100_000,
                "reasoning_tokens": 125_000,
                "total_tokens": 1_500_000,
            },
            model_cost={
                "input": 1.0,
                "output": 2.0,
                "cacheRead": 0.5,
                "cacheWrite": 0.25,
            },
        )

        h, _ = _make_handler(results_dir)
        scores = h.get_scores()

    assert len(scores) == 1, scores
    row = scores[0]
    assert row["prompt_tokens"] == 1_000_000
    assert row["completion_tokens"] == 500_000
    assert row["cached_tokens"] == 250_000
    assert row["cache_creation_tokens"] == 100_000
    assert row["reasoning_tokens"] == 125_000
    assert row["total_tokens"] == 1_500_000
    assert row["estimated_cost_usd"] == 2.15
    assert row["cost_per_completed_task_usd"] == 2.15
    assert row["passed_tasks_per_usd"] == 1 / 2.15
    assert row["input_cost_per_million_usd"] == 1.0
    assert row["output_cost_per_million_usd"] == 2.0


def test_get_scores_prefers_direct_usage_cost():
    """Provider-reported usage cost should beat local pricing estimates."""
    with tempfile.TemporaryDirectory() as tmp:
        results_dir = Path(tmp) / "results"
        model_id = "priced/model"
        adapter = "pi_vanilla"
        suite = "aider_polyglot"
        task_id = "python/hello"
        base = (
            results_dir
            / "runs"
            / "priced-run"
            / encode_model_path(model_id)
            / adapter
            / suite
            / encode_task_path(task_id)
        )
        _write_trial(
            base / "trial-1",
            passed=True,
            model_id=model_id,
            task_id=task_id,
            token_usage={
                "prompt_tokens": 1_000_000,
                "completion_tokens": 1_000_000,
                "cost_usd": 0.1234,
            },
            model_cost={"input": 100.0, "output": 100.0},
        )

        h, _ = _make_handler(results_dir)
        scores = h.get_scores()

    assert scores[0]["estimated_cost_usd"] == 0.1234
    assert scores[0]["cost_per_completed_task_usd"] == 0.1234


def test_get_scores_estimates_when_direct_usage_cost_is_zero_with_pricing():
    """Zero provider cost plus tokens should fall back to benchmark pricing."""
    with tempfile.TemporaryDirectory() as tmp:
        results_dir = Path(tmp) / "results"
        model_id = "zai/glm-5.2"
        adapter = "pi_vanilla"
        suite = "aider_polyglot"
        task_id = "python/hello"
        base = (
            results_dir
            / "runs"
            / "priced-run"
            / encode_model_path(model_id)
            / adapter
            / suite
            / encode_task_path(task_id)
        )
        _write_trial(
            base / "trial-1",
            passed=True,
            model_id=model_id,
            task_id=task_id,
            token_usage={
                "prompt_tokens": 1_000_000,
                "completion_tokens": 1_000_000,
                "cached_tokens": 1_000_000,
                "cost_usd": 0,
            },
            model_cost={"input": 1.4, "output": 4.4, "cacheRead": 0.26},
        )

        h, _ = _make_handler(results_dir)
        scores = h.get_scores()

    assert round(scores[0]["estimated_cost_usd"], 2) == 6.06
    assert round(scores[0]["cost_per_completed_task_usd"], 2) == 6.06


def test_get_scores_does_not_mark_pricing_only_rows_as_costed():
    """Pricing metadata without observed usage is not cost coverage."""
    with tempfile.TemporaryDirectory() as tmp:
        results_dir = Path(tmp) / "results"
        model_id = "priced/model"
        adapter = "pi_vanilla"
        suite = "terminal_bench"
        task_id = "hello-world"
        base = (
            results_dir
            / "runs"
            / "priced-run"
            / encode_model_path(model_id)
            / adapter
            / suite
            / encode_task_path(task_id)
        )
        _write_trial(
            base / "trial-1",
            passed=True,
            model_id=model_id,
            task_id=task_id,
            token_usage={},
            model_cost={"input": 1.0, "output": 2.0},
        )

        h, _ = _make_handler(results_dir)
        scores = h.get_scores()

    row = scores[0]
    assert row["estimated_cost_usd"] is None
    assert row["costed_trials"] == 0
    assert row["completed_trials"] == 1
    assert row["cost_per_completed_task_usd"] is None
    assert row["passed_tasks_per_usd"] is None


def test_get_scores_marks_partial_cost_coverage_and_suppresses_ratios():
    """Cost/task and pass/$ must not use partial cost coverage."""
    with tempfile.TemporaryDirectory() as tmp:
        results_dir = Path(tmp) / "results"
        model_id = "priced/model"
        adapter = "pi_vanilla"
        suite = "aider_polyglot"

        for task_id, token_usage in [
            ("python/with-cost", {"prompt_tokens": 1000, "cost_usd": 0.01}),
            ("python/no-cost", {}),
        ]:
            base = (
                results_dir
                / "runs"
                / "priced-run"
                / encode_model_path(model_id)
                / adapter
                / suite
                / encode_task_path(task_id)
            )
            _write_trial(
                base / "trial-1",
                passed=True,
                model_id=model_id,
                task_id=task_id,
                token_usage=token_usage,
            )

        h, _ = _make_handler(results_dir)
        scores = h.get_scores()

    row = scores[0]
    assert row["estimated_cost_usd"] == 0.01
    assert row["costed_trials"] == 1
    assert row["completed_trials"] == 2
    assert row["has_partial_cost"] is True
    assert row["cost_per_completed_task_usd"] is None
    assert row["passed_tasks_per_usd"] is None


def test_get_scores_ignores_pending_verdicts():
    """Incomplete smoke attempts should not count as benchmark failures."""
    with tempfile.TemporaryDirectory() as tmp:
        results_dir = Path(tmp) / "results"
        model_id = "local/ornith-1.0-35b"
        adapter = "pi_vanilla"
        suite = "terminal_bench"
        task_id = "hello-world"

        pending_base = (
            results_dir
            / "old-smoke"
            / encode_model_path(model_id)
            / adapter
            / suite
            / encode_task_path(task_id)
        )
        passing_base = (
            results_dir
            / "new-smoke"
            / encode_model_path(model_id)
            / adapter
            / suite
            / encode_task_path(task_id)
        )
        _write_trial(
            pending_base / "trial-1",
            passed=False,
            pending=True,
            model_id=model_id,
        )
        _write_trial(passing_base / "trial-1", passed=True, model_id=model_id)

        h, _ = _make_handler(results_dir)
        scores = h.get_scores(include_smoke=True)
        details = h.get_task_details(encode_model_path(model_id), adapter, suite)

    assert len(scores) == 1, scores
    assert scores[0]["total_tasks"] == 1, scores
    assert scores[0]["passed_tasks"] == 1, scores
    assert details["tasks"][0]["pass_at_k"] == "1/1", details


def test_get_scores_ignores_manifest_model_path_mismatch():
    """Pre-encoding artifacts with slashed model paths are malformed rows."""
    with tempfile.TemporaryDirectory() as tmp:
        results_dir = Path(tmp) / "results"
        malformed_base = (
            results_dir
            / "nvidia"
            / "nemotron-3-ultra-550b-a55b"
            / "pi_vanilla"
            / "aider_polyglot"
            / "python"
            / "hello"
        )
        _write_trial(malformed_base / "trial-1", passed=True)

        h, _ = _make_handler(results_dir)
        scores = h.get_scores()
        warnings = h.get_warnings()

    assert scores == []
    assert len(warnings) == 1, warnings
    assert warnings[0]["code"] == "malformed_result_path"
    assert "unknown adapter" in warnings[0]["message"]


def test_get_scores_warns_on_manifest_model_path_mismatch():
    """Valid-shaped rows with mismatched manifest/path model IDs are skipped."""
    with tempfile.TemporaryDirectory() as tmp:
        results_dir = Path(tmp) / "results"
        path_model = "local/path-model"
        manifest_model = "local/manifest-model"
        task_id = "python/hello"
        base = (
            results_dir
            / encode_model_path(path_model)
            / "pi_vanilla"
            / "aider_polyglot"
            / encode_task_path(task_id)
        )
        _write_trial(
            base / "trial-1",
            passed=True,
            task_id=task_id,
            model_id=manifest_model,
        )

        h, _ = _make_handler(results_dir)
        scores = h.get_scores()
        warnings = h.get_warnings()

    assert scores == []
    assert len(warnings) == 1, warnings
    assert warnings[0]["code"] == "malformed_result_path"
    assert "manifest model" in warnings[0]["message"]


def test_get_scores_warns_and_skips_malformed_started_trial_dirs():
    """Malformed legacy trial dirs must not affect status accounting."""
    with tempfile.TemporaryDirectory() as tmp:
        results_dir = Path(tmp) / "results"
        _write_single_row(
            results_dir / "runs" / "ornith-high-20260704",
            adapter="pi_devstack",
            suite="aider_polyglot",
            task_id="python/hello",
        )
        malformed_trial = (
            results_dir
            / "runs"
            / "local"
            / "ornith-1.0-35b-ornith-high-20260704"
            / "local"
            / "ornith-1.0-35b"
            / "pi_devstack"
            / "aider_polyglot"
            / "rust"
            / "poker"
            / "trial-1"
        )
        malformed_trial.mkdir(parents=True)

        h, _ = _make_handler(results_dir)
        scores = h.get_scores()
        warnings = h.get_warnings()

    assert len(scores) == 1, scores
    assert scores[0]["adapter"] == "pi_devstack"
    assert scores[0]["status"] == "complete"
    assert len(warnings) == 1, warnings
    assert warnings[0]["code"] == "malformed_result_path"
    assert "unknown adapter" in warnings[0]["message"]


def test_get_scores_ignores_trial_like_workdir_cache_dirs():
    """Only runner trial-N leaves should be considered started trials."""
    with tempfile.TemporaryDirectory() as tmp:
        results_dir = Path(tmp) / "results"
        model_id, adapter, suite, task_id = _write_single_row(results_dir)
        trial_dir = (
            results_dir
            / encode_model_path(model_id)
            / adapter
            / suite
            / encode_task_path(task_id)
            / "trial-1"
        )
        (trial_dir / "workdir" / "trial-cache").mkdir(parents=True)

        h, _ = _make_handler(results_dir)
        scores = h.get_scores()
        warnings = h.get_warnings()

    assert len(scores) == 1, scores
    assert scores[0]["status"] == "complete"
    assert warnings == []


def test_format_scores_terminal_surfaces_malformed_result_warnings():
    """Parsing problems should be visible, not silently counted as failures."""
    import importlib.util

    server_path = PROJECT_ROOT / "view-scores" / "server.py"
    spec = importlib.util.spec_from_file_location(
        "view_scores_server_warning_test", server_path
    )
    server_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(server_mod)

    output = server_mod.format_scores_terminal(
        [
            {
                "model": "local/ornith-1.0-35b",
                "adapter": "pi_devstack",
                "suite": "aider_polyglot",
                "pass_rate": 100.0,
                "passed_tasks": 1,
                "total_tasks": 1,
                "ci_lower": 20.7,
                "ci_upper": 100.0,
            }
        ],
        results_dir=Path("/tmp/results"),
        warnings=[
            {
                "code": "malformed_result_path",
                "message": "malformed result path skipped: /tmp/bad/trial-1",
            }
        ],
    )

    assert "Warnings:" in output
    assert "malformed result path skipped" in output


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
    assert "<th>Score</th>" in html
    assert "<th>95% CI</th>" not in html


def test_generate_html_includes_default_cost_efficiency_columns():
    """The browser default table should include cost efficiency fields."""
    with tempfile.TemporaryDirectory() as tmp:
        results_dir = Path(tmp) / "results"
        model_id = "priced/model"
        base = (
            results_dir
            / "runs"
            / "priced-run"
            / encode_model_path(model_id)
            / "pi_vanilla"
            / "aider_polyglot"
            / encode_task_path("python/hello")
        )
        _write_trial(
            base / "trial-1",
            passed=True,
            model_id=model_id,
            token_usage={"prompt_tokens": 1_000_000, "cost_usd": 0.1234},
        )

        h, _ = _make_handler(results_dir)
        html = h.generate_html()

    assert "<th>Cost</th>" in html
    assert "<th>$/Task</th>" in html
    assert "<th>Pass/$</th>" in html
    assert "$0.1234" in html


def test_generate_html_escapes_result_metadata_and_quotes_detail_links():
    """Viewer HTML must not render result metadata as executable markup.

    Results are durable local artifacts, but they can contain model IDs from
    external config/provider names. Treat them as data when rendering HTML.
    """
    with tempfile.TemporaryDirectory() as tmp:
        results_dir = Path(tmp) / "results"
        results_dir.mkdir()
        model_id = '<script>alert("x")</script>&model=evil'
        adapter = "pi_vanilla"
        suite = "aider_polyglot"
        base = (
            results_dir
            / encode_model_path(model_id)
            / adapter
            / suite
            / encode_task_path("python/hello")
        )
        _write_trial(base / "trial-1", passed=True, model_id=model_id)

        h, _ = _make_handler(results_dir)
        html = h.generate_html()

    assert '<script>alert("x")</script>' not in html
    assert '&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt;&amp;model=evil' in html
    assert 'model=%3Cscript%3Ealert%28%22x%22%29%3C%2Fscript%3E%26model%3Devil' in html
    assert 'adapter=pi_vanilla' in html
    assert 'suite=aider_polyglot' in html


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


def test_format_scores_terminal_uses_color_and_task_counts():
    """Terminal score output should be readable without opening the web UI."""
    with tempfile.TemporaryDirectory() as tmp:
        results_dir = Path(tmp) / "results"
        results_dir.mkdir()
        model_id, adapter, suite, task_id, task_id2 = _build_encoded_tree(results_dir)

        h, server_mod = _make_handler(results_dir)
        scores = h.get_scores()
        output = server_mod.format_scores_terminal(
            scores,
            results_dir=results_dir,
            color=True,
        )

    assert "\x1b[" in output
    assert model_id in output
    assert adapter in output
    assert suite in output
    assert "1/2" in output
    assert "50.0%" in output


def test_format_scores_terminal_default_includes_cost_efficiency():
    """Default terminal rows should show cost, cost/task, and passed/$."""
    import importlib.util

    server_path = PROJECT_ROOT / "view-scores" / "server.py"
    spec = importlib.util.spec_from_file_location("view_scores_server_cost_test", server_path)
    server_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(server_mod)

    output = server_mod.format_scores_terminal(
        [
            {
                "model": "local/ornith-1.0-35b",
                "adapter": "pi_vanilla",
                "suite": "aider_polyglot",
                "pass_rate": 50.0,
                "passed_tasks": 5,
                "total_tasks": 10,
                "estimated_cost_usd": 0.1234,
                "cost_per_completed_task_usd": 0.01234,
                "passed_tasks_per_usd": 40.5186,
            }
        ],
        results_dir=Path("/tmp/results"),
        color=False,
    )

    assert "Cost" in output
    assert "$/Task" in output
    assert "Pass/$" in output
    assert "$0.1234" in output
    assert "$0.0123" in output
    assert "40.5" in output


def test_format_scores_terminal_verbose_includes_status_and_timing():
    """Verbose table should surface runtime and ETA columns."""
    import importlib.util

    server_path = PROJECT_ROOT / "view-scores" / "server.py"
    spec = importlib.util.spec_from_file_location("view_scores_server_verbose_test", server_path)
    server_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(server_mod)

    output = server_mod.format_scores_terminal(
        [
            {
                "model": "local/ornith-1.0-35b",
                "adapter": "little_coder",
                "suite": "aider_polyglot",
                "pass_rate": 50.0,
                "passed_tasks": 5,
                "total_tasks": 10,
                "completed_tasks": 10,
                "expected_tasks": 20,
                "status": "running",
                "total_wall_clock_seconds": 600,
                "mean_wall_clock_seconds": 60,
                "prompt_tokens": 1000,
                "completion_tokens": 500,
                "total_tokens": 1500,
                "estimated_cost_usd": 0.0123,
                "input_cost_per_million_usd": 0.14,
                "output_cost_per_million_usd": 1.04,
                "costed_trials": 9,
                "completed_trials": 10,
                "estimated_remaining_seconds": 600,
            }
        ],
        results_dir=Path("/tmp/results"),
        verbose=True,
    )

    assert "Status" in output
    assert "Runtime" in output
    assert "Tok In" in output
    assert "Tok Out" in output
    assert "$/M In" in output
    assert "$/M Out" in output
    assert "Costed" in output
    assert "9/10" in output
    assert "Cost" in output
    assert "ETA" in output
    assert "running" in output
    assert "10m" in output
    assert "$0.1400" in output
    assert "$1.04" in output
    assert "$0.0123" in output


def test_root_view_entrypoint_prints_terminal_scores():
    """./view should be the easy root-level way to inspect score rows."""
    with tempfile.TemporaryDirectory() as tmp:
        results_dir = Path(tmp) / "results"
        results_dir.mkdir()
        model_id, adapter, suite, task_id, task_id2 = _build_encoded_tree(results_dir)

        result = subprocess.run(
            [
                str(PROJECT_ROOT / "view"),
                "--results-dir",
                str(results_dir),
                "--color",
                "always",
            ],
            capture_output=True,
            text=True,
        )

    assert result.returncode == 0, result.stderr
    assert "\x1b[" in result.stdout
    assert model_id in result.stdout
    assert "50.0%" in result.stdout


def test_root_view_entrypoint_supports_verbose_flag():
    """./view -v should print the timing/status table variant."""
    with tempfile.TemporaryDirectory() as tmp:
        results_dir = Path(tmp) / "results"
        results_dir.mkdir()
        _build_encoded_tree(results_dir)

        result = subprocess.run(
            [
                str(PROJECT_ROOT / "view"),
                "--results-dir",
                str(results_dir),
                "--color",
                "never",
                "-v",
            ],
            capture_output=True,
            text=True,
        )

    assert result.returncode == 0, result.stderr
    assert "Status" in result.stdout
    assert "Runtime" in result.stdout
    assert "ETA" in result.stdout


def test_view_cli_accepts_results_dir_before_subcommand():
    """--results-dir should work in normal argparse position before command."""
    with tempfile.TemporaryDirectory() as tmp:
        results_dir = Path(tmp) / "results"
        results_dir.mkdir()
        model_id, adapter, suite, task_id, task_id2 = _build_encoded_tree(results_dir)

        result = subprocess.run(
            [
                sys.executable,
                str(PROJECT_ROOT / "view-scores" / "server.py"),
                "--results-dir",
                str(results_dir),
                "table",
                "--color",
                "never",
            ],
            capture_output=True,
            text=True,
        )

    assert result.returncode == 0, result.stderr
    assert model_id in result.stdout
    assert "50.0%" in result.stdout
