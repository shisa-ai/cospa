"""Pareto stability metric and artifact-validation tests."""

import json
import runpy
from pathlib import Path

import pytest

from harness.path_utils import encode_model_path, encode_task_path


ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "analyze-stability-panel.py"


def _analyzer():
    return runpy.run_path(str(SCRIPT))


def test_stability_summary_reports_task_macro_probability_and_flip_rate():
    summarize_suite = _analyzer()["summarize_suite"]

    summary = summarize_suite(
        {
            "mixed": [True, False, True],
            "always-fail": [False, False, False],
            "always-pass": [True, True, True],
        },
        expected_k=3,
    )

    assert summary["attempts"] == 9
    assert summary["passed_attempts"] == 5
    assert summary["mean_pass_probability"] == pytest.approx(5 / 9)
    assert summary["outcome_flip_tasks"] == 1
    assert summary["outcome_flip_rate"] == pytest.approx(1 / 3)
    assert summary["pairwise_disagreement_rate"] == pytest.approx(2 / 9)
    assert {
        row["task_id"]: (row["passes"], row["pass_probability"], row["flipped"])
        for row in summary["tasks"]
    } == {
        "always-fail": (0, 0.0, False),
        "always-pass": (3, 1.0, False),
        "mixed": (2, pytest.approx(2 / 3), True),
    }


def test_stability_summary_rejects_incomplete_k2_or_k3_tasks():
    summarize_suite = _analyzer()["summarize_suite"]

    with pytest.raises(ValueError, match="expected 3 outcomes"):
        summarize_suite({"incomplete": [True, False]}, expected_k=3)
    with pytest.raises(ValueError, match="expected 2 outcomes"):
        summarize_suite({"incomplete": [True]}, expected_k=2)


def test_analyzer_fails_closed_on_non_authoritative_or_missing_trials(tmp_path):
    analyze_results = _analyzer()["analyze_results"]
    model = "local/test-model"
    adapter = "pi_vanilla"
    suite = "example_suite"
    manifest_path = tmp_path / "panel.json"
    results_dir = tmp_path / "results"
    manifest_path.write_text(
        json.dumps(
            {
                "execution": {
                    "model": model,
                    "adapter": adapter,
                    "thinking": "high",
                },
                "protocol": {"independent_trials_per_task": 3},
                "suites": {suite: {"task_ids": ["task/one"]}},
            }
        )
    )
    task_dir = (
        results_dir
        / encode_model_path(model)
        / adapter
        / suite
        / encode_task_path("task/one")
    )
    for trial, verdict in (
        (1, {"passed": True}),
        (2, {"passed": False, "adapter_failed": True}),
    ):
        trial_dir = task_dir / f"trial-{trial}"
        trial_dir.mkdir(parents=True)
        (trial_dir / "manifest.json").write_text(
            json.dumps(
                {
                    "model": {"id": model},
                    "suite": {"task_id": "task/one"},
                    "sampling": {"thinking": "high"},
                    "trial": trial,
                    "exit_code": -1 if trial == 2 else 0,
                }
            )
        )
        (trial_dir / "verdict.json").write_text(json.dumps(verdict))

    analysis = analyze_results(manifest_path, results_dir)

    assert analysis["complete"] is False
    assert analysis["expected_attempts"] == 3
    assert analysis["authoritative_attempts"] == 1
    assert analysis["suites"][suite]["metrics"] is None
    assert {issue["kind"] for issue in analysis["issues"]} == {
        "missing_artifact",
        "non_authoritative_verdict",
    }
