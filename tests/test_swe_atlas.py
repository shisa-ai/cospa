"""Tests for the pinned SWE Atlas Q&A + Test Writing pilot."""

import json
import os
import subprocess
import tomllib
from collections import Counter
from pathlib import Path
from unittest.mock import patch

import pytest

from harness.adapters.pi_vanilla import PiVanillaAdapter
from harness.runner import run_trial
from harness.suites import load_suite


SWE_ATLAS_COMMIT = "2cac47d64a9123d915b8f6f6f53763391920f574"
JUDGE_MODEL = "anthropic/claude-opus-4-5-20251101"


def _make_pilot_vendor(tmp_path: Path, suite):
    vendor = tmp_path / "vendor"
    manifest = json.loads(Path(suite.manifest_path).read_text())
    for item in manifest["tasks"]:
        task_dir = (
            vendor
            / "swe-atlas"
            / "data"
            / item["upstream_workflow"]
            / item["upstream_task_id"]
        )
        (task_dir / "environment").mkdir(parents=True)
        (task_dir / "tests").mkdir()
        (task_dir / "instruction.md").write_text(
            f"Pinned {item['workflow']} prompt for {item['id']}\n"
        )
        (task_dir / "task.toml").write_text(
            'schema_version = "1.1"\n\n'
            "[task]\n"
            f'name = "scale-ai/{item["upstream_task_id"]}"\n'
        )
        (task_dir / "environment" / "Dockerfile").write_text("FROM scratch\n")
        (task_dir / "tests" / "test.sh").write_text("#!/bin/sh\n")
    return vendor


def test_suite_registry_loads_swe_atlas_pilot12():
    suite = load_suite("swe_atlas_pilot12")

    assert suite.name == "swe_atlas_pilot12"
    assert suite.version == "pilot12-v1"
    assert suite.task_count == 12


def test_pilot_manifest_freezes_balanced_workflow_language_and_category_strata():
    suite = load_suite("swe_atlas_pilot12")
    manifest = json.loads(Path(suite.manifest_path).read_text())
    tasks = manifest["tasks"]

    assert manifest["upstream"]["commit"] == SWE_ATLAS_COMMIT
    assert manifest["judge"]["model"] == JUDGE_MODEL
    assert len(tasks) == len({task["id"] for task in tasks}) == 12
    assert Counter(task["workflow"] for task in tasks) == {
        "test_writing": 8,
        "codebase_qa": 4,
    }
    assert Counter(task["language"] for task in tasks) == {
        "go": 3,
        "python": 3,
        "c": 3,
        "typescript": 3,
    }
    assert {
        task["category"]
        for task in tasks
        if task["workflow"] == "codebase_qa"
    } == {
        "Architecture & system design",
        "Root-cause analysis",
        "Code Onboarding",
        "Security",
    }
    assert {
        task["test_level"]
        for task in tasks
        if task["workflow"] == "test_writing"
    } == {"unit", "integration", "acceptance"}


def test_get_task_ids_requires_all_12_tasks_from_the_pinned_checkout(tmp_path):
    suite = load_suite("swe_atlas_pilot12")
    vendor = _make_pilot_vendor(tmp_path, suite)

    task_ids = suite.get_task_ids(vendor)

    assert len(task_ids) == 12
    assert task_ids == sorted(task_ids)
    assert all(task_id.startswith(("qa/", "tw/")) for task_id in task_ids)

    first = json.loads(Path(suite.manifest_path).read_text())["tasks"][0]
    missing = (
        vendor
        / "swe-atlas"
        / "data"
        / first["upstream_workflow"]
        / first["upstream_task_id"]
    )
    missing.rename(missing.with_name(missing.name + "-missing"))
    assert suite.get_task_ids(vendor) == []


def test_get_task_ids_rejects_a_differently_pinned_git_checkout(tmp_path):
    suite = load_suite("swe_atlas_pilot12")
    vendor = _make_pilot_vendor(tmp_path, suite)
    (vendor / "swe-atlas" / ".git").mkdir()

    with patch("harness.suites.swe_atlas.subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(
            ["git"], 0, stdout="mutable-head\n", stderr=""
        )
        task_ids = suite.get_task_ids(vendor)

    assert task_ids == []


def test_materialize_task_preserves_upstream_harbor_task_and_strata(tmp_path):
    suite = load_suite("swe_atlas_pilot12")
    vendor = _make_pilot_vendor(tmp_path, suite)
    task_id = suite.get_task_ids(vendor)[0]

    workdir = tmp_path / "workdir"
    task_data = suite.materialize_task(task_id, workdir, vendor)

    assert task_data["prompt"].startswith("Pinned ")
    assert task_data["workflow"] in {"codebase_qa", "test_writing"}
    assert task_data["language"] in {"go", "python", "c", "typescript"}
    assert task_data["swe_atlas_pin"] == SWE_ATLAS_COMMIT
    assert task_data["judge_model"] == JUDGE_MODEL
    assert (workdir / "task.toml").is_file()
    assert (workdir / "instruction.md").is_file()
    assert (workdir / "environment" / "Dockerfile").is_file()
    assert (workdir / "tests" / "test.sh").is_file()


def test_run_harbor_job_uses_local_task_custom_agent_and_pinned_judge(tmp_path):
    suite = load_suite("swe_atlas_pilot12")
    vendor = _make_pilot_vendor(tmp_path, suite)
    task_id = suite.get_task_ids(vendor)[0]
    workdir = tmp_path / "workdir"
    suite.materialize_task(task_id, workdir, vendor)
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = list(cmd)
        captured["env"] = kwargs["env"]
        return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

    judge_env = {
        "SWE_ATLAS_JUDGE_API_KEY": "judge-secret",
        "SWE_ATLAS_JUDGE_BASE_URL": "https://judge.example/v1",
    }
    with patch.dict(os.environ, judge_env, clear=False), patch(
        "harness.suites.swe_atlas.run_command", side_effect=fake_run
    ):
        result = suite.run_harbor_job(
            task_id=task_id,
            model_id="test/model",
            adapter_name="pi_vanilla",
            workdir=workdir,
            jobs_dir=tmp_path / "jobs",
            n_attempts=3,
            vendor_dir=vendor,
            thinking="high",
        )

    cmd = captured["cmd"]
    assert result["returncode"] == 0
    assert cmd[:2] == ["harbor", "run"]
    assert cmd[cmd.index("--path") + 1] == str(workdir.resolve())
    assert cmd[cmd.index("--agent") + 1].endswith(":PiVanillaHarborAgent")
    assert cmd[cmd.index("--n-attempts") + 1] == "3"
    assert "migrate" not in cmd
    assert "--verifier-include-logs" in cmd
    assert captured["env"]["OPENAI_API_KEY"] == "judge-secret"
    assert captured["env"]["OPENAI_API_BASE"] == "https://judge.example/v1"
    assert captured["env"]["EVAL_MODEL"] == JUDGE_MODEL


def test_run_harbor_job_fails_before_agent_when_judge_credentials_are_missing(
    tmp_path,
):
    suite = load_suite("swe_atlas_pilot12")
    vendor = _make_pilot_vendor(tmp_path, suite)
    task_id = suite.get_task_ids(vendor)[0]
    workdir = tmp_path / "workdir"
    suite.materialize_task(task_id, workdir, vendor)

    with patch.dict(os.environ, {}, clear=True), patch(
        "harness.suites.swe_atlas.run_command"
    ) as mock_run:
        result = suite.run_harbor_job(
            task_id,
            "test/model",
            "pi_vanilla",
            workdir,
            tmp_path / "jobs",
            vendor_dir=vendor,
        )

    assert result["returncode"] == -1
    assert "judge" in result["stderr"].lower()
    mock_run.assert_not_called()


def test_verify_preserves_test_writing_native_subchecks(tmp_path):
    suite = load_suite("swe_atlas_pilot12")
    workdir = tmp_path / "trial-1" / "workdir"
    result_dir = tmp_path / "trial-1" / "jobs" / "job" / "task"
    verifier_dir = result_dir / "verifier"
    verifier_dir.mkdir(parents=True)
    (result_dir / "result.json").write_text(json.dumps({
        "verifier_result": {"rewards": {"reward": 1.0}},
        "exception_info": None,
    }))
    evaluation = {
        "overall_pass": True,
        "rubrics_pass": True,
        "manifest_pass": True,
        "mutation_pass": True,
        "mutation_testing": {"pass": True},
    }
    (verifier_dir / "evaluation_results.json").write_text(json.dumps(evaluation))

    verdict = suite.verify(
        {"task_id": "tw/task-example", "workflow": "test_writing"},
        workdir,
    )

    assert verdict["passed"] is True
    assert verdict["workflow"] == "test_writing"
    assert verdict["verifier_subchecks"] == {
        "overall": True,
        "rubrics": True,
        "manifest": True,
        "mutation": True,
    }
    assert verdict["native_evaluation"] == evaluation


def test_verify_preserves_codebase_qa_native_subchecks(tmp_path):
    suite = load_suite("swe_atlas_pilot12")
    workdir = tmp_path / "trial-1" / "workdir"
    result_dir = tmp_path / "trial-1" / "jobs" / "job" / "task"
    verifier_dir = result_dir / "verifier"
    verifier_dir.mkdir(parents=True)
    (result_dir / "result.json").write_text(json.dumps({
        "verifier_result": {"rewards": {"reward": 1.0}},
        "exception_info": None,
    }))
    evaluation = {
        "reward": 1,
        "pass": True,
        "agg_score": 0.875,
        "num_scored": 8,
        "num_passed": 7,
    }
    (verifier_dir / "evaluation_results.json").write_text(json.dumps(evaluation))

    verdict = suite.verify(
        {"task_id": "qa/task-example", "workflow": "codebase_qa"},
        workdir,
    )

    assert verdict["passed"] is True
    assert verdict["verifier_subchecks"] == {
        "overall": True,
        "reward": True,
        "rubrics_scored": 8,
        "rubrics_passed": 7,
        "aggregate_score": 0.875,
    }


def test_runner_delegates_every_harbor_suite_not_only_terminal_bench(tmp_path):
    class HarborSuite:
        name = "swe_atlas_pilot12"
        version = "test"
        verify_on_adapter_failure = True

        def materialize_task(self, task_id, workdir, vendor_dir):
            return {"task_id": task_id, "prompt": "prompt"}

        def run_harbor_job(self, **kwargs):
            harbor_calls.append(kwargs)
            return {"returncode": 0, "stdout": "", "stderr": ""}

        def verify(self, task_data, workdir):
            return {"passed": True, "test_count": 1, "exit_code": 0}

    class Adapter(PiVanillaAdapter):
        def run(self, *args, **kwargs):
            adapter_calls.append((args, kwargs))
            raise AssertionError("generic adapter path must not run")

    harbor_calls = []
    adapter_calls = []
    manifest, verdict = run_trial(
        HarborSuite(),
        Adapter(),
        "test/model",
        "qa/task-example",
        1,
        tmp_path / "results",
        tmp_path / "vendor",
    )

    assert len(harbor_calls) == 1
    assert adapter_calls == []
    assert verdict["passed"] is True
    assert manifest["suite"]["version"] == "test"


@pytest.mark.requires_vendor
def test_real_pinned_pilot_materializes_every_language_and_workflow(tmp_path):
    suite = load_suite("swe_atlas_pilot12")
    vendor = Path(__file__).resolve().parent.parent / "vendor"
    if not (vendor / "swe-atlas" / ".git").exists():
        pytest.skip("vendor/swe-atlas not present")

    task_ids = suite.get_task_ids(vendor)
    assert len(task_ids) == 12
    seen = Counter()
    for index, task_id in enumerate(task_ids):
        workdir = tmp_path / str(index)
        task_data = suite.materialize_task(task_id, workdir, vendor)
        upstream_meta = tomllib.loads((workdir / "task.toml").read_text())["metadata"]
        assert task_data["prompt"].strip()
        assert task_data["base_commit"] == upstream_meta["base_commit"]
        assert task_data["repository"] in upstream_meta["repository"]
        assert (workdir / "tests" / "test.sh").is_file()
        assert (workdir / "tests" / "rubrics.json").is_file()
        if task_data["workflow"] == "test_writing":
            assert (workdir / "tests" / "skeleton_code_swap.patch").is_file()
            assert (workdir / "tests" / "run_script.sh").is_file()
        else:
            assert (workdir / "tests" / "evaluate_answer.py").is_file()
        seen[(task_data["workflow"], task_data["language"])] += 1

    assert seen == {
        ("codebase_qa", "go"): 1,
        ("codebase_qa", "python"): 1,
        ("codebase_qa", "c"): 1,
        ("codebase_qa", "typescript"): 1,
        ("test_writing", "go"): 2,
        ("test_writing", "python"): 2,
        ("test_writing", "c"): 2,
        ("test_writing", "typescript"): 2,
    }


def test_runner_records_swe_atlas_pin_judge_and_task_strata(tmp_path):
    suite = load_suite("swe_atlas_pilot12")
    vendor = _make_pilot_vendor(tmp_path, suite)
    task_id = suite.get_task_ids(vendor)[0]
    adapter = PiVanillaAdapter()

    def fake_harbor(**kwargs):
        result_dir = Path(kwargs["jobs_dir"]) / "job" / "task"
        result_dir.mkdir(parents=True)
        (result_dir / "result.json").write_text(json.dumps({
            "verifier_result": {"rewards": {"reward": 1.0}},
            "exception_info": None,
        }))
        return {"returncode": 0, "stdout": "", "stderr": ""}

    with patch.object(suite, "run_harbor_job", side_effect=fake_harbor):
        manifest, verdict = run_trial(
            suite,
            adapter,
            "test/model",
            task_id,
            1,
            tmp_path / "results",
            vendor,
        )

    assert verdict["passed"] is True
    assert manifest["suite"]["upstream_commit"] == SWE_ATLAS_COMMIT
    assert manifest["suite"]["judge_model"] == JUDGE_MODEL
    assert manifest["suite"]["workflow"] in {"codebase_qa", "test_writing"}
    assert manifest["suite"]["language"] in {"go", "python", "c", "typescript"}
