"""FeatureBench campaign suite tests."""

import hashlib
import json
import os
import runpy
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from harness.suites import load_suite
from harness.suites.featurebench import (
    FeatureBenchLiteCandidateSuite,
    parse_featurebench_test_output,
    score_featurebench_result,
)


ROOT = Path(__file__).resolve().parent.parent


def test_featurebench_lite30_manifest_is_official_outcome_blind_split():
    manifest_path = ROOT / "configs/featurebench_lite30_v1.json"
    manifest = json.loads(manifest_path.read_text())
    builder = runpy.run_path(
        str(ROOT / "scripts/select-featurebench-panel.py")
    )

    assert builder["build_manifest"]() == manifest
    assert manifest["selection"]["official_split"] == "lite"
    assert manifest["selection"]["uses_target_model_outcomes"] is False
    assert len(manifest["tasks"]) == 30
    assert len({task["task_id"] for task in manifest["tasks"]}) == 30
    assert len({task["repository"] for task in manifest["tasks"]}) == 13
    assert sum(task["level"] == 1 for task in manifest["tasks"]) == 26
    assert sum(task["level"] == 2 for task in manifest["tasks"]) == 4

    suite = FeatureBenchLiteCandidateSuite()
    assert suite.task_count == 30
    assert suite.get_task_ids(ROOT / "vendor") == manifest["task_ids"]
    assert all(
        "@sha256:" in suite.image_lock[task["image_ref"]]["pinned_ref"]
        for task in manifest["tasks"]
    )


def test_featurebench_pareto12_is_repeat_qualified_and_registered():
    manifest_path = ROOT / "configs/featurebench_lite_pareto12_v1.json"
    image_lock_path = ROOT / "configs/featurebench_lite_pareto12_images_v1.json"
    manifest = json.loads(manifest_path.read_text())
    image_lock = json.loads(image_lock_path.read_text())
    finalizer = runpy.run_path(
        str(ROOT / "scripts/finalize-featurebench-panel.py")
    )

    assert finalizer["build_manifest"]() == manifest
    assert finalizer["build_image_lock"](manifest) == image_lock
    assert manifest["selection"]["uses_target_model_outcomes"] is False
    assert manifest["selection"]["mechanical_qualification_only"] is True
    assert manifest["selection"]["panel_size"] == 12
    assert manifest["selection"]["repository_count"] == 11
    assert manifest["selection"]["maximum_tasks_per_repository"] == 2
    assert manifest["qualification"]["status"] == "repeat_qualified"
    assert manifest["qualification"]["gold_passed"] == 36
    assert manifest["qualification"]["null_failed"] == 36
    assert len(manifest["tasks"]) == 12
    assert all(task["level"] == 1 for task in manifest["tasks"])
    assert all(task["qualification"]["gold_passes"] == 3 for task in manifest["tasks"])
    assert all(task["qualification"]["null_failures"] == 3 for task in manifest["tasks"])
    assert image_lock["source_manifest_sha256"] == hashlib.sha256(
        manifest_path.read_bytes()
    ).hexdigest()

    suite = load_suite("featurebench_lite_pareto12")
    assert suite.task_count == 12
    assert suite.get_task_ids(ROOT / "vendor") == manifest["task_ids"]
    assert all(
        "@sha256:" in suite.image_lock[task["image_ref"]]["pinned_ref"]
        for task in manifest["tasks"]
    )


def test_featurebench_pilot6_is_registered_and_discovers_real_pinned_rows():
    suite = load_suite("featurebench_lite_pilot6")
    pilot = json.loads(
        (ROOT / "configs/ornith_runtime_pilot_v1.json").read_text()
    )["suites"]["featurebench_lite"]
    expected_ids = [task["id"] for task in pilot["tasks"]]

    assert suite.name == "featurebench_lite_pilot6"
    assert suite.task_count == 6
    assert suite.get_task_ids(ROOT / "vendor") == expected_ids


@pytest.mark.requires_vendor
def test_featurebench_pilot6_materializes_hidden_oracles_outside_prompt(tmp_path):
    suite = load_suite("featurebench_lite_pilot6")
    task_id = suite.get_task_ids(ROOT / "vendor")[0]
    task = suite.materialize_task(task_id, tmp_path, ROOT / "vendor")

    assert task["prompt"].startswith("# Benchmark execution context")
    assert task["problem_statement"] in task["prompt"]
    assert task["fail_to_pass"] not in task["prompt"]
    assert task["image_ref"].startswith(
        "libercoders/featurebench-specs_"
    )
    assert "@sha256:" in task["image_ref"]
    assert (tmp_path / "task.toml").is_file()
    assert (tmp_path / "environment" / "Dockerfile").is_file()
    assert (tmp_path / "tests" / "test.sh").is_file()
    assert (tmp_path / "tests" / "test.patch").is_file()
    assert (tmp_path / "solution" / "solve.sh").is_file()
    assert (tmp_path / "solution" / "gold.patch").is_file()
    assert task["fail_to_pass"] not in (tmp_path / "instruction.md").read_text()


def test_featurebench_score_separates_resolution_from_f2p_partial_credit():
    verdict = score_featurebench_result(
        f2p_status_maps=[
            {
                "test_a": "PASSED",
                "test_b": "XFAIL",
                "test_c": "FAILED",
                "test_d": "SKIPPED",
            }
        ],
        p2p_status_maps=[{"test_e": "PASSED"}],
        f2p_exit_codes=[1],
        p2p_exit_codes=[0],
    )

    assert verdict["passed"] is False
    assert verdict["failure_class"] == "incorrect"
    assert verdict["f2p_test_count"] == 3
    assert verdict["f2p_tests_passed"] == 2
    assert verdict["f2p_tests_failed"] == 1
    assert verdict["f2p_tests_skipped"] == 1
    assert verdict["f2p_pass_rate"] == pytest.approx(2 / 3, abs=0.0001)
    assert verdict["p2p_tests_passed"] == 1


def test_featurebench_score_requires_f2p_execution_for_binary_resolution():
    assert score_featurebench_result(
        f2p_status_maps=[],
        p2p_status_maps=[],
        f2p_exit_codes=[],
        p2p_exit_codes=[],
    )["passed"] is False
    assert score_featurebench_result(
        f2p_status_maps=[{"test_a": "PASSED"}],
        p2p_status_maps=[{"test_b": "PASSED"}],
        f2p_exit_codes=[0],
        p2p_exit_codes=[0],
    )["passed"] is True


def test_featurebench_parser_uses_pinned_upstream_pytest_semantics():
    output = """================ short test summary info ================
PASSED tests/test_feature.py::test_one
FAILED tests/test_feature.py::test_two - AssertionError
================ 1 failed, 1 passed ================
"""
    assert parse_featurebench_test_output(
        "mlflow/mlflow", output, ROOT / "vendor"
    ) == {
        "tests/test_feature.py::test_one": "PASSED",
        "tests/test_feature.py::test_two": "FAILED",
    }


@pytest.mark.requires_vendor
def test_featurebench_real_materializations_are_shell_valid_and_level_aware(
    tmp_path,
):
    suite = load_suite("featurebench_lite_pilot6")
    tasks = {}

    def fake_original_archive(_image_ref, destination):
        destination.write_bytes(b"hidden original")

    with patch.object(
        suite,
        "_write_hidden_original_archive",
        side_effect=fake_original_archive,
    ):
        for task_id in suite.get_task_ids(ROOT / "vendor"):
            task_root = tmp_path / task_id
            tasks[task_id] = suite.materialize_task(
                task_id, task_root, ROOT / "vendor"
            )
            for script in task_root.rglob("*.sh"):
                checked = subprocess.run(
                    ["bash", "-n", str(script)], capture_output=True, text=True
                )
                assert checked.returncode == 0, checked.stderr

    level1 = next(task for task in tasks.values() if task["level"] == 1)
    level2 = next(task for task in tasks.values() if task["level"] == 2)
    level1_root = tmp_path / level1["task_id"]
    level2_root = tmp_path / level2["task_id"]
    lightning = next(
        task for task in tasks.values() if task["repository"].startswith("Lightning-AI/")
    )
    lightning_toml = (
        tmp_path / lightning["task_id"] / "task.toml"
    ).read_text()
    task_name = lightning_toml.split('name = "', 1)[1].split('"', 1)[0]
    assert task_name == task_name.lower()
    assert "/" in task_name

    assert (level1_root / "solution" / "gold.patch").stat().st_size > 0
    assert "git apply --reverse" in (level1_root / "tests" / "test.sh").read_text()
    baseline = (level1_root / "environment" / "baseline.sh").read_text()
    assert "rm -rf -- /root/my_repo" in baseline
    assert "rm -f -- /opt/cospa/mask.patch /opt/cospa/baseline.sh" in baseline
    assert "-name __pycache__" in baseline
    assert "-name '*.py[co]'" in baseline
    assert "/root/my_repo" not in (level2_root / "tests" / "test.sh").read_text()
    assert "/tests/original-repo.tar.gz" in (
        level2_root / "tests" / "test.sh"
    ).read_text()
    assert (level2_root / "tests" / "original-repo.tar.gz").is_file()
    assert (level2_root / "solution" / "gold.patch").stat().st_size == 0
    assert "no released gold patch" in (
        level2_root / "solution" / "solve.sh"
    ).read_text()
    assert "pip install --no-deps ." in (
        level2_root / "tests" / "test.sh"
    ).read_text()
    assert level2["pass_to_pass_paths"] == []

    gpu_task = next(task for task in tasks.values() if task["runtime"]["need_gpu"])
    gpu_root = tmp_path / gpu_task["task_id"]
    assert "gpus = 0" in (gpu_root / "task.toml").read_text()
    assert "gpus: all" in (
        gpu_root / "environment" / "docker-compose.yaml"
    ).read_text()


def test_featurebench_level2_archive_export_is_offline_and_digest_pinned(tmp_path):
    destination = tmp_path / "original-repo.tar.gz"
    image_ref = "example/featurebench@sha256:" + "a" * 64

    def fake_run(command, **kwargs):
        kwargs["stdout"].write(b"archive")
        return subprocess.CompletedProcess(command, 0, b"", b"")

    with patch(
        "harness.suites.featurebench.subprocess.run", side_effect=fake_run
    ) as run:
        suite = load_suite("featurebench_lite_pilot6")
        suite._write_hidden_original_archive(image_ref, destination)

    command = run.call_args.args[0]
    assert command[:6] == [
        "docker",
        "run",
        "--rm",
        "--network",
        "none",
        "--entrypoint",
    ]
    assert image_ref in command
    assert command[-5:] == ["-C", "/root", "-czf", "-", "my_repo"]
    assert destination.read_bytes() == b"archive"


@pytest.mark.requires_vendor
def test_featurebench_harbor_run_allows_agent_plus_long_verifier(tmp_path):
    suite = load_suite("featurebench_lite_pilot6")
    task_id = suite.get_task_ids(ROOT / "vendor")[0]
    workdir = tmp_path / "workdir"
    suite.materialize_task(task_id, workdir, ROOT / "vendor")
    captured = {}

    def fake_run(command, **kwargs):
        if command[:2] == ["harbor", "run"]:
            captured["timeout"] = kwargs["timeout"]
        return subprocess.CompletedProcess(command, 0, "", "")

    with patch(
        "harness.suites.terminal_bench.run_command", side_effect=fake_run
    ), patch.dict(
        os.environ,
        {"CODING_EVAL_HARBOR_MODEL_BASE_URL": "http://model-relay:8013/v1"},
    ):
        result = suite.run_harbor_job(
            task_id=task_id,
            model_id="local/test-model",
            adapter_name="pi_vanilla",
            workdir=workdir,
            jobs_dir=tmp_path / "jobs",
            vendor_dir=ROOT / "vendor",
        )

    assert result["returncode"] == 0
    assert captured["timeout"] >= 3 * 3600
