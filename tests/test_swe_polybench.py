import ast
import concurrent.futures
import csv
import json
import tomllib
from pathlib import Path

import pytest

from harness.suites import load_suite
from harness.suites.swe_polybench import (
    SwePolyBenchVerifiedSuite,
    parse_polybench_test_output,
    score_polybench_result,
)


ROOT = Path(__file__).parents[1]


def selected_row(instance_id="google__gson-1989"):
    with (ROOT / "vendor/eval-data/swe-polybench-verified/test.csv").open() as handle:
        for row in csv.DictReader(handle):
            if row["instance_id"] == instance_id:
                return row
    raise AssertionError(instance_id)


def test_suite_registry_loads_swe_polybench_verified():
    suite = load_suite("swe_polybench_verified")
    assert isinstance(suite, SwePolyBenchVerifiedSuite)
    assert suite.task_count == 38


def test_polybench_dataset_loading_is_safe_across_verifier_threads():
    def load_ids(_):
        return SwePolyBenchVerifiedSuite().get_task_ids(ROOT / "vendor")

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        discovered = list(pool.map(load_ids, range(16)))
    assert all(len(task_ids) == 38 for task_ids in discovered)


def test_polybench_discovers_exact_frozen_selected_ids():
    suite = SwePolyBenchVerifiedSuite()
    pilot = json.loads((ROOT / "configs/ornith_runtime_pilot_v1.json").read_text())
    expected = [task["id"] for task in pilot["suites"][suite.name]["tasks"]]
    assert suite.get_task_ids(ROOT / "vendor") == expected


def test_polybench_materializes_harbor_task_with_hidden_verifier_only(tmp_path):
    suite = SwePolyBenchVerifiedSuite()
    row = selected_row()
    task = suite.materialize_task(
        row["instance_id"], tmp_path / "task", ROOT / "vendor"
    )

    task_root = tmp_path / "task"
    config = tomllib.loads((task_root / "task.toml").read_text())
    assert "docker_image" not in config["environment"]
    assert config["environment"]["network_mode"] == "public"
    assert config["agent"]["network_mode"] == "no-network"
    assert config["verifier"]["network_mode"] == "no-network"
    assert "@sha256:" in task["image_ref"]
    dockerfile = (task_root / "environment" / "Dockerfile").read_text()
    assert dockerfile.startswith("FROM " + task["image_ref"] + "\n")
    assert f"git reset --hard {row['base_commit']}" in dockerfile
    assert "git clean -fd" in dockerfile
    instruction = (task_root / "instruction.md").read_text()
    assert row["problem_statement"] in instruction
    assert row["patch"] not in instruction
    assert row["test_patch"] not in instruction
    assert "patch" not in task
    assert "test_patch" not in task

    assert (task_root / "tests" / "test.patch").read_text() == row["test_patch"]
    assert (task_root / "solution" / "gold.patch").read_text() == row["patch"]
    verifier = (task_root / "tests" / "test.sh").read_text()
    capture_at = verifier.index("git diff --binary")
    hidden_patch_at = verifier.index("git apply --whitespace=nowarn /tests/test.patch")
    model_patch_at = verifier.index(
        "git apply --whitespace=nowarn /logs/verifier/model.patch"
    )
    assert capture_at < hidden_patch_at < model_patch_at
    assert '"model_patch_applied":%s' in verifier
    assert "mvn -o clean verify" in verifier
    assert "/logs/verifier/test_output.txt" in verifier
    assert "/logs/verifier/status.json" in verifier
    assert "reward.txt" in verifier


@pytest.mark.parametrize(
    ("repo", "fixture", "passed", "failed"),
    [
        (
            "google/gson",
            "java_maven.log",
            "com.google.gson.GsonTest.testNewJsonWriter_Default",
            "com.google.gson.GsonTest.testNewJsonWriter_Custom",
        ),
        (
            "Significant-Gravitas/AutoGPT",
            "python_pytest.log",
            "tests/unit/test_message_history.py:None:test_message_history_batch_summary",
            "tests/unit/test_message_history.py:None:test_message_history_limit",
        ),
        (
            "mrdoob/three.js",
            "javascript_mocha.log",
            "Source > Maths > Vector3 > length/lengthSq",
            "Source > Maths > Box3 > intersectsPlane",
        ),
        (
            "angular/angular",
            "typescript_bazel.log",
            "/packages/core/test/render3:render3",
            "/packages/compiler/test/selector:selector",
        ),
    ],
)
def test_polybench_pinned_parsers_cover_each_selected_language(
    repo, fixture, passed, failed
):
    output = (ROOT / "tests/fixtures/swe_polybench" / fixture).read_text()
    parsed = parse_polybench_test_output(repo, output, ROOT / "vendor")
    assert passed in parsed["passed_tests"]
    assert failed in parsed["failed_tests"]


def test_polybench_parser_and_score_require_all_f2p_and_no_p2p_failure():
    row = selected_row()
    f2p = ast.literal_eval(row["F2P"])
    p2p = ast.literal_eval(row["P2P"])
    passing_xml = """
<testsuite tests="6" failures="0">
  <testcase classname="com.google.gson.GsonTest" name="testNewJsonWriter_Default"/>
  <testcase classname="com.google.gson.GsonTest" name="testNewJsonWriter_Custom"/>
  <testcase classname="com.google.gson.GsonTest" name="testOverridesDefaultExcluder"/>
  <testcase classname="com.google.gson.GsonTest" name="testClonedTypeAdapterFactoryListsAreIndependent"/>
  <testcase classname="com.google.gson.GsonTest" name="testNewJsonReader_Custom"/>
  <testcase classname="com.google.gson.GsonTest" name="testNewJsonReader_Default"/>
</testsuite>
"""
    parsed = parse_polybench_test_output("google/gson", passing_xml, ROOT / "vendor")
    verdict = score_polybench_result(parsed, f2p=f2p, p2p=p2p)
    assert verdict["passed"] is True
    assert verdict["all_f2p_passed"] is True
    assert verdict["no_p2p_failed"] is True
    assert verdict["test_count"] == 6

    failing_xml = passing_xml.replace(
        '<testcase classname="com.google.gson.GsonTest" name="testNewJsonWriter_Default"/>',
        '<testcase classname="com.google.gson.GsonTest" name="testNewJsonWriter_Default"><failure/></testcase>',
    )
    failed = score_polybench_result(
        parse_polybench_test_output("google/gson", failing_xml, ROOT / "vendor"),
        f2p=f2p,
        p2p=p2p,
    )
    assert failed["passed"] is False
    assert failed["all_f2p_passed"] is False
    assert failed["failure_class"] == "incorrect"


def test_polybench_verify_reads_harbor_verifier_artifacts(tmp_path):
    suite = SwePolyBenchVerifiedSuite()
    task_root = tmp_path / "trial" / "workdir"
    task = suite.materialize_task(
        "google__gson-1989", task_root, ROOT / "vendor"
    )
    artifacts = (
        task_root.parent
        / "jobs"
        / "job-1"
        / "trial-1"
        / "artifacts"
        / "verifier"
    )
    artifacts.mkdir(parents=True)
    (artifacts / "model.patch").write_text("diff --git a/a b/a\n")
    (artifacts / "status.json").write_text(
        json.dumps(
            {
                "test_patch_applied": True,
                "model_patch_applied": True,
                "test_exit_code": 0,
            }
        )
    )
    (artifacts / "test_output.txt").write_text(
        '<testsuite><testcase classname="com.google.gson.GsonTest" '
        'name="testNewJsonWriter_Default"/><testcase '
        'classname="com.google.gson.GsonTest" name="testNewJsonWriter_Custom"/>'
        '<testcase classname="com.google.gson.GsonTest" '
        'name="testOverridesDefaultExcluder"/><testcase '
        'classname="com.google.gson.GsonTest" '
        'name="testClonedTypeAdapterFactoryListsAreIndependent"/>'
        '<testcase classname="com.google.gson.GsonTest" '
        'name="testNewJsonReader_Custom"/><testcase '
        'classname="com.google.gson.GsonTest" '
        'name="testNewJsonReader_Default"/></testsuite>'
    )

    verdict = suite.verify(task, task_root)
    assert verdict["passed"] is True
    assert verdict["failure_class"] == "resolved"
    assert verdict["model_patch_bytes"] > 0


def test_polybench_verify_fails_closed_when_model_patch_did_not_apply(tmp_path):
    suite = SwePolyBenchVerifiedSuite()
    task_root = tmp_path / "trial" / "workdir"
    task = suite.materialize_task(
        "google__gson-1989", task_root, ROOT / "vendor"
    )
    artifacts = task_root.parent / "jobs" / "job-1" / "artifacts" / "verifier"
    artifacts.mkdir(parents=True)
    (artifacts / "model.patch").write_text("invalid patch")
    (artifacts / "status.json").write_text(
        json.dumps(
            {
                "test_patch_applied": True,
                "model_patch_applied": False,
                "test_exit_code": -1,
            }
        )
    )
    (artifacts / "test_output.txt").write_text("Model patch failed to apply")

    verdict = suite.verify(task, task_root)
    assert verdict["passed"] is False
    assert verdict["verifier_failed"] is True
    assert verdict["failure_class"] == "verifier_failed"
