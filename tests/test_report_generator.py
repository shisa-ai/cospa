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
