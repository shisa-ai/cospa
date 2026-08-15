"""Outcome-blind Pareto stability sentinel tests."""

import json
import runpy
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def test_stability32_manifest_is_reproducible_and_outcome_blind():
    manifest_path = ROOT / "configs" / "pareto_stability32_v1.json"
    manifest = json.loads(manifest_path.read_text())
    builder = runpy.run_path(str(ROOT / "scripts" / "select-stability-panel.py"))

    assert builder["build_manifest"]() == manifest
    assert manifest["name"] == "pareto-stability32-v1"
    assert manifest["selection"]["uses_target_model_outcomes"] is False
    assert manifest["selection"]["uses_baseline_outcomes"] is False
    assert manifest["protocol"]["independent_trials_per_task"] == 3
    assert manifest["protocol"]["report_best_of_k"] is False
    assert manifest["protocol"]["primary_stability_metrics"] == [
        "mean_pass_probability",
        "outcome_flip_rate",
    ]

    suites = manifest["suites"]
    assert {name: panel["allocation"] for name, panel in suites.items()} == {
        "bigcodebench_hard_agentic_pareto60": 8,
        "multi_swe_bench_flash_hermetic25": 7,
        "terminal_bench_core_pareto20": 5,
        "swe_polybench_verified_balanced64": 8,
        "featurebench_lite_pareto12": 4,
    }
    assert sum(panel["allocation"] for panel in suites.values()) == 32
    assert all(
        len(panel["task_ids"]) == len(set(panel["task_ids"])) == panel["allocation"]
        for panel in suites.values()
    )


def test_stability32_manifest_preserves_predeclared_strata():
    manifest = json.loads(
        (ROOT / "configs" / "pareto_stability32_v1.json").read_text()
    )
    suites = manifest["suites"]

    bcb = suites["bigcodebench_hard_agentic_pareto60"]["tasks"]
    assert len(
        {(task["library_count_bucket"], task["prompt_size_tertile"]) for task in bcb}
    ) == 8

    multi = suites["multi_swe_bench_flash_hermetic25"]["tasks"]
    assert {task["language"] for task in multi} == {
        "c",
        "c++",
        "go",
        "java",
        "javascript",
        "rust",
        "typescript",
    }

    terminal = suites["terminal_bench_core_pareto20"]["tasks"]
    assert Counter(task["difficulty"] for task in terminal) == {
        "easy": 2,
        "medium": 2,
        "hard": 1,
    }
    assert len({task["category"] for task in terminal}) == 5

    poly = suites["swe_polybench_verified_balanced64"]["tasks"]
    assert Counter(task["language"] for task in poly) == {
        "java": 2,
        "javascript": 2,
        "python": 2,
        "typescript": 2,
    }
    assert all(
        len({task["task_type"] for task in poly if task["language"] == language})
        == 2
        for language in {task["language"] for task in poly}
    )

    feature = suites["featurebench_lite_pareto12"]["tasks"]
    assert len({task["repository"] for task in feature}) == 4
