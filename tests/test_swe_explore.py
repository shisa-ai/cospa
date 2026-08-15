"""SWE-Explore continuous localization diagnostic tests."""

import hashlib
import json
import runpy
from pathlib import Path

import pytest

from harness.suites import load_suite


ROOT = Path(__file__).resolve().parent.parent


def test_swe_explore_verified12_suite_is_registered():
    suite = load_suite("swe_explore_verified12")

    assert suite.task_count == 12
    assert suite.panel["task_ids"] == [
        task["task_id"] for task in suite.panel["tasks"]
    ]


@pytest.mark.requires_vendor
def test_swe_explore_verified12_manifest_is_outcome_blind_and_reproducible():
    manifest_path = ROOT / "configs" / "swe_explore_verified12_v1.json"
    manifest = json.loads(manifest_path.read_text())
    builder = runpy.run_path(str(ROOT / "scripts/select-swe-explore-panel.py"))

    assert builder["build_manifest"]() == manifest
    assert manifest["name"] == "swe-explore-verified12-v1"
    assert manifest["selection"]["uses_target_model_outcomes"] is False
    assert manifest["selection"]["source_dataset"] == "verified"
    assert manifest["selection"]["panel_size"] == 12
    assert manifest["selection"]["repository_count"] == 12
    assert manifest["selection"]["tasks_per_repository"] == 1
    assert manifest["protocol"]["top_k_regions"] == 5
    assert manifest["protocol"]["headline_metric"] == "weighted_core_coverage"
    assert manifest["protocol"]["score_type"] == "continuous_non_coding"
    assert len(manifest["task_ids"]) == len(set(manifest["task_ids"])) == 12
    assert len({task["repository"] for task in manifest["tasks"]}) == 12

    suite = load_suite("swe_explore_verified12")
    assert suite.get_task_ids(ROOT / "vendor") == manifest["task_ids"]


@pytest.mark.requires_vendor
def test_swe_explore_materialization_hides_ground_truth_and_pins_snapshot(tmp_path):
    suite = load_suite("swe_explore_verified12")
    task_id = suite.get_task_ids(ROOT / "vendor")[0]
    task = suite.materialize_task(task_id, tmp_path / "workdir", ROOT / "vendor")
    prompt = task["prompt"]
    manifest_task = suite.selected[task_id]

    assert task["problem_statement"] in prompt
    assert "swe_explore_regions.json" in prompt
    assert "at most 5" in prompt
    assert "read_core_regions" not in prompt
    assert manifest_task["ground_truth_sha256"] == hashlib.sha256(
        json.dumps(task["ground_truth"], sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    assert Path(task["snapshot_dir"]).resolve() != (tmp_path / "workdir").resolve()
    assert not (tmp_path / "workdir" / "swe_explore_regions.json").exists()
    assert not list((tmp_path / "workdir").rglob("*ground*truth*"))


@pytest.mark.requires_vendor
def test_swe_explore_scores_null_and_oracle_with_pinned_upstream_metrics(tmp_path):
    suite = load_suite("swe_explore_verified12")
    task_id = suite.get_task_ids(ROOT / "vendor")[0]
    workdir = tmp_path / "workdir"
    task = suite.materialize_task(task_id, workdir, ROOT / "vendor")
    output = workdir / "swe_explore_regions.json"

    output.write_text("[]\n")
    null = suite.verify(task, workdir)
    assert null["passed"] is False
    assert null["failure_class"] == "diagnostic_scored"
    assert null["headline_metric"] == "weighted_core_coverage"
    assert null["score"] == 0.0
    assert all(value == 0.0 for value in null["metrics"].values())

    oracle_regions = task["ground_truth"]["read_core_regions"]
    assert len(oracle_regions) <= 5
    output.write_text(json.dumps(oracle_regions) + "\n")
    oracle = suite.verify(task, workdir)
    assert oracle["passed"] is True
    assert oracle["score"] == pytest.approx(1.0)
    assert oracle["metrics"]["precision"] == pytest.approx(1.0)
    assert oracle["metrics"]["recall"] == pytest.approx(1.0)
    assert oracle["metrics"]["weighted_core_coverage"] == pytest.approx(1.0)
    assert oracle["metrics"]["hit_file_rate"] == pytest.approx(1.0)


@pytest.mark.requires_vendor
def test_swe_explore_rejects_nonexistent_or_over_budget_regions(tmp_path):
    suite = load_suite("swe_explore_verified12")
    task_id = suite.get_task_ids(ROOT / "vendor")[0]
    workdir = tmp_path / "workdir"
    task = suite.materialize_task(task_id, workdir, ROOT / "vendor")
    output = workdir / "swe_explore_regions.json"

    output.write_text(json.dumps([
        {"path": "../hidden.json", "start": 1, "end": 2},
    ]))
    invalid_path = suite.verify(task, workdir)
    assert invalid_path["failure_class"] == "invalid_output"
    assert invalid_path["verifier_failed"] is False
    assert invalid_path["score"] == 0.0
    assert invalid_path["score_type"] == "continuous_non_coding"
    assert invalid_path["headline_metric"] == "weighted_core_coverage"

    output.write_text(json.dumps([
        {"path": task["ground_truth"]["read_core_regions"][0]["path"], "start": 1, "end": 1}
        for _ in range(6)
    ]))
    over_budget = suite.verify(task, workdir)
    assert over_budget["failure_class"] == "invalid_output"
    assert "at most 5" in over_budget["grader_output"]


def test_swe_explore_manifest_metadata_keeps_score_separate_from_resolution():
    suite = load_suite("swe_explore_verified12")
    metadata = suite.manifest_metadata(
        {
            "task_id": suite.panel["task_ids"][0],
            "repository": suite.panel["tasks"][0]["repository"],
            "base_commit": suite.panel["tasks"][0]["base_commit"],
        }
    )

    assert metadata["protocol"] == "swe_explore_top5_localization"
    assert metadata["score_type"] == "continuous_non_coding"
    assert metadata["headline_metric"] == "weighted_core_coverage"
    assert metadata["merge_with_coding_resolution"] is False
    assert metadata["verifier_revision"] == suite.panel["source"]["revision"]
