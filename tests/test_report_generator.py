"""Report generator tests: one-sheet Markdown output with trace links."""

import json
import runpy
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from harness.path_utils import encode_model_path, encode_task_path

SCRIPT = PROJECT_ROOT / "scripts" / "generate-report.py"


def _generator():
    return runpy.run_path(str(SCRIPT))


def _write_trial(
    trial_dir: Path,
    *,
    passed: bool,
    task_id: str,
    model_id: str = "local/test-model",
    trial: int = 1,
    wall_clock: float = 10.0,
    thinking: str = "high",
    token_usage: dict | None = None,
    failure_class: str | None = None,
    with_trace: bool = True,
    model_cost: dict | None = None,
    behavior: dict | None = None,
) -> None:
    trial_dir.mkdir(parents=True, exist_ok=True)
    model_block = {
        "id": model_id,
        "provider": model_id.split("/")[0],
        "served_model": model_id,
    }
    if model_cost is not None:
        model_block["cost"] = model_cost
    (trial_dir / "manifest.json").write_text(
        json.dumps(
            {
                "model": model_block,
                "adapter": {"id": "PiVanillaAdapter", "version": "vanilla"},
                "suite": {"id": "ExampleSuite", "task_id": task_id},
                "trial": trial,
                "sampling": {"thinking": thinking},
                "timing": {"wall_clock_seconds": wall_clock},
                "token_usage": token_usage
                or {
                    "prompt_tokens": 100,
                    "cached_tokens": 900,
                    "completion_tokens": 50,
                },
                "exit_code": 0,
                "created_at": "2026-08-16T00:00:00+00:00",
                "run_end_time": "2026-08-16T00:00:10+00:00",
                **({"behavior": behavior} if behavior is not None else {}),
            }
        )
    )
    verdict = {
        "passed": passed,
        "test_count": 1,
        "grader_output": "ok" if passed else "fail",
        "exit_code": 0,
    }
    if failure_class:
        verdict["failure_class"] = failure_class
    (trial_dir / "verdict.json").write_text(json.dumps(verdict))
    if with_trace:
        out_dir = trial_dir / "out"
        out_dir.mkdir(exist_ok=True)
        (out_dir / "pi_session.jsonl").write_text('{"type":"response"}\n')


def _build_tree(results_dir: Path) -> None:
    model = "local/test-model"
    adapter = "pi_vanilla"
    suite = "aider_polyglot"
    base = results_dir / encode_model_path(model) / adapter / suite
    _write_trial(
        base / encode_task_path("python/hello") / "trial-1",
        passed=True,
        task_id="python/hello",
        wall_clock=10.0,
    )
    _write_trial(
        base / encode_task_path("python/hello") / "trial-2",
        passed=False,
        task_id="python/hello",
        wall_clock=12.0,
        failure_class="incorrect",
    )
    _write_trial(
        base / encode_task_path("python/world") / "trial-1",
        passed=False,
        task_id="python/world",
        wall_clock=8.0,
        failure_class="incorrect",
        with_trace=False,
    )


def test_report_renders_summary_table_and_links_to_traces(tmp_path):
    generate_report = _generator()["generate_report"]

    results_dir = tmp_path / "results"
    _build_tree(results_dir)
    output = tmp_path / "reports" / "one-sheet.md"

    markdown = generate_report([results_dir], output)

    # Summary table row for the cell.
    assert "aider_polyglot" in markdown
    assert "local/test-model" in markdown
    assert "high" in markdown
    assert "2" in markdown  # task count
    assert "300" in markdown  # summed uncached prompt tokens (2 trials with usage)

    # Per-task drill-down with relative links to trial dirs and traces.
    assert output.exists()
    text = output.read_text()
    report_dir = output.parent
    for task, trial, has_trace in (
        ("python/hello", "trial-1", True),
        ("python/hello", "trial-2", True),
        ("python/world", "trial-1", False),
    ):
        trial_dir = (
            results_dir
            / encode_model_path("local/test-model")
            / "pi_vanilla"
            / "aider_polyglot"
            / encode_task_path(task)
            / trial
        )
        rel = Path(
            __import__("os").path.relpath(trial_dir, report_dir)
        ).as_posix()
        assert rel in text, f"missing link to {trial_dir}"
        if has_trace:
            trace_rel = Path(
                __import__("os").path.relpath(
                    trial_dir / "out" / "pi_session.jsonl", report_dir
                )
            ).as_posix()
            assert trace_rel in text, f"missing trace link for {trial_dir}"
            assert (report_dir / trace_rel).exists()

    # Failure taxonomy rendered.
    assert "incorrect" in text

    # No trace link rendered for a trial without a trace file.
    world_section = text.split("python/world")[-1]
    assert "pi_session.jsonl" not in world_section.split("\n\n")[0]

    # Generated report equals returned markdown.
    assert text == markdown


def test_report_includes_behavior_table_with_speed_and_capability_columns(tmp_path):
    generate_report = _generator()["generate_report"]

    results_dir = tmp_path / "results"
    model = "local/test-model"
    base = results_dir / encode_model_path(model) / "pi_vanilla" / "aider_polyglot"
    _write_trial(
        base / encode_task_path("python/one") / "trial-1",
        passed=True,
        task_id="python/one",
        wall_clock=120.0,
        token_usage={
            "prompt_tokens": 10_000,
            "cached_tokens": 5_000,
            "completion_tokens": 1_000,
            "response_count": 8,
        },
        behavior={
            "status": "observed",
            "agent_seconds": 100.0,
            "inference_seconds": 70.0,
            "tool_seconds": 20.0,
            "other_seconds": 10.0,
            "tool_calls": 30,
            "search_calls": 4,
        },
    )
    output = tmp_path / "report.md"
    markdown = generate_report([results_dir], output)

    assert "## Speed & behavior" in markdown
    for column in (
        "Avg/task",
        "Turns",
        "LLM%",
        "Tool%",
        "Tool calls",
        "Search calls",
    ):
        assert column in markdown, f"missing behavior column {column}"
    assert "8.0" in markdown  # mean turns from response_count
    assert "70.0%" in markdown  # LLM% = inference/agent
    assert "20.0%" in markdown  # Tool% = tool/agent
    assert "30.0" in markdown  # mean tool calls
    assert "4.0" in markdown  # mean search calls
    assert "2m00s" in markdown  # avg/task wall


def test_report_includes_campaign_elapsed_and_cost(tmp_path):
    generate_report = _generator()["generate_report"]

    results_dir = tmp_path / "results"
    model = "local/test-model"
    base = results_dir / encode_model_path(model) / "pi_vanilla" / "aider_polyglot"
    _write_trial(
        base / encode_task_path("python/one") / "trial-1",
        passed=True,
        task_id="python/one",
        wall_clock=5.0,
        token_usage={
            "prompt_tokens": 1_000_000,
            "cached_tokens": 0,
            "completion_tokens": 200_000,
        },
        model_cost={
            "input": 0.14,
            "output": 0.28,
            "cacheRead": 0.0028,
            "cacheWrite": 0.14,
            "pricing_unit": "usd_per_1m_tokens",
        },
    )
    output = tmp_path / "report.md"
    markdown = generate_report([results_dir], output)

    assert "1.0M" in markdown or "1,000,000" in markdown  # uncached
    assert "200K" in markdown or "200,000" in markdown  # output
    assert "$" in markdown  # cost column rendered


def _build_single_task_tree(
    results_dir: Path,
    *,
    task_id: str,
    passed: bool,
    newer: bool = False,
) -> None:
    base = (
        results_dir
        / encode_model_path("local/test-model")
        / "pi_vanilla"
        / "aider_polyglot"
    )
    trial = base / encode_task_path(task_id) / "trial-1"
    _write_trial(trial, passed=passed, task_id=task_id)
    if newer:
        import os
        stamp = 1787000000.0  # newer than _build_tree defaults
        for p in trial.rglob("*"):
            os.utime(p, (stamp, stamp))


def test_report_prefers_complete_run_over_newer_partial(tmp_path):
    """Duplicate suite keys: latest COMPLETE cell wins; partials go to a
    footnote instead of polluting the summary."""
    module = _generator()
    generate_report = module["generate_report"]
    # Host-independent: force the max-observed heuristic (no canonical size).

    complete_root = tmp_path / "run-complete"
    _build_tree(complete_root)  # 2 tasks: hello, world
    import os
    old = 1786000000.0
    for p in complete_root.rglob("verdict.json"):
        os.utime(p, (old, old))

    partial_root = tmp_path / "run-partial"
    _build_single_task_tree(partial_root, task_id="python/hello", passed=True, newer=True)

    output = tmp_path / "reports" / "one-sheet.md"
    markdown = generate_report(
        [complete_root, partial_root], output, canonical_suite_size=lambda s: None
    )

    # Exactly one summary data row + one speed row for the suite (footnote
    # section may legitimately mention the excluded partial as well).
    pre_footnote = markdown.split("## Excluded partial cells")[0]
    assert pre_footnote.count("| aider_polyglot |") == 2
    # The complete cell's score is shown (hello mixed trials + world fail ->
    # 0/2 by viewer aggregation), not the partial's 1/1.
    assert "0/2 (0.0%)" in markdown
    # The partial run is relegated to an explicit footnote, not silently lost.
    assert "Excluded partial cells" in markdown
    assert "run-partial" in markdown
    # Totals count each task once (no double counting across roots).
    assert "**2**" in markdown  # All-cells task total


def test_report_marks_partial_when_no_complete_run(tmp_path):
    """No complete cell exists for a key: latest partial is shown but marked
    PARTIAL with observed/expected counts."""
    module = _generator()
    generate_report = module["generate_report"]

    partial_root = tmp_path / "run-only-partial"
    _build_single_task_tree(partial_root, task_id="python/hello", passed=True)

    # Canonical size known (2 tasks) -> 1 observed is partial.
    def fake_size(suite: str):
        return 2 if suite == "aider_polyglot" else None
    output = tmp_path / "reports" / "one-sheet.md"
    markdown = generate_report(
        [partial_root], output, canonical_suite_size=fake_size
    )

    assert "**PARTIAL 1/2**" in markdown


def test_report_includes_headline_geomean_per_model_config(tmp_path):
    """Geomean of per-suite rates per (model, adapter, thinking); partial
    cells excluded; continuous diagnostic rates included."""
    generate_report = _generator()["generate_report"]

    model, adapter = "local/test-model", "pi_vanilla"

    def cell(root: Path, suite: str, tasks: list[bool]):
        base = root / encode_model_path(model) / adapter / suite
        for i, passed in enumerate(tasks):
            _write_trial(
                base / encode_task_path(f"t/{suite}{i}") / "trial-1",
                passed=passed,
                task_id=f"t/{suite}{i}",
            )

    root = tmp_path / "run-main"
    cell(root, "aider_polyglot", [True, False])    # 1/2 -> 0.5
    cell(root, "featurebench_lite_pareto12", [True, False, False, False])  # 1/4 -> 0.25

    partial = tmp_path / "run-partial-aider"
    cell(partial, "aider_polyglot", [True])  # newer partial duplicate; excluded

    output = tmp_path / "reports" / "one-sheet.md"
    markdown = generate_report(
        [root, partial], output, canonical_suite_size=lambda s: None
    )

    assert "## Headline geomean" in markdown
    # sqrt(0.5 * 0.25) = 0.35355 -> 35.4%
    assert "35.4%" in markdown
    # Geomean covers 2 cells (partial suite_a duplicate excluded).
    assert "| local/test-model | pi_vanilla | high | 2 | 35.4% |" in markdown


def test_geomean_rate_prefers_continuous_score_over_anyhit_pass_rate():
    """WCC-style rows contribute their headline score, not the inflated
    any-hit pass rate; 0-100 values normalize; binary rows use pass_rate."""
    module = _generator()
    rate = module["_geomean_rate"]
    cont = rate({"score_type": "continuous_non_coding", "score": 9.7, "pass_rate": 83.3})
    assert cont is not None and abs(cont - 0.097) < 1e-9
    assert rate({"score_type": "binary_resolution", "pass_rate": 36.0}) == 0.36
    assert rate({"score_type": "binary_resolution", "pass_rate": 0.5}) == 0.5
    assert rate({"score_type": "binary_resolution"}) is None
