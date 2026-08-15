import ast
import concurrent.futures
import csv
import hashlib
import json
import runpy
import tomllib
from collections import Counter
from pathlib import Path

import pytest

from harness.suites import load_suite
from harness.suites import swe_polybench as swe_polybench_module
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


def test_balanced_candidate96_is_nested_and_outcome_blind():
    manifest = json.loads(
        (ROOT / "configs/swe_polybench_balanced_candidate96_v1.json").read_text()
    )
    manifest_path = ROOT / "configs/swe_polybench_balanced_candidate96_v1.json"
    image_lock = json.loads(
        (ROOT / "configs/swe_polybench_balanced_candidate96_images_v1.json").read_text()
    )
    tasks = manifest["tasks"]
    nested64 = [
        task for task in tasks
        if task["panel_membership"] == "balanced64_candidate"
    ]
    pilot_ids = set(SwePolyBenchVerifiedSuite().get_task_ids(ROOT / "vendor"))

    selector = runpy.run_path(str(ROOT / "scripts/select-polybench-panel.py"))
    assert selector["build_manifest"]() == manifest
    assert image_lock["source_manifest_sha256"] == hashlib.sha256(
        manifest_path.read_bytes()
    ).hexdigest()
    assert len(image_lock["images"]) == 96
    assert manifest["selection"]["outcome_blind"] is True
    assert manifest["selection"]["excludes_target_model_outcomes"] is True
    assert len(tasks) == len({task["task_id"] for task in tasks}) == 96
    assert len(nested64) == 64
    assert pilot_ids.issubset(task["task_id"] for task in nested64)
    assert not set(manifest["selection"]["prior_mechanical_exclusions"]).intersection(
        task["task_id"] for task in tasks
    )
    assert {task["language"] for task in tasks} == {
        "java", "javascript", "python", "typescript"
    }
    for language in ("java", "javascript", "python", "typescript"):
        language96 = [task for task in tasks if task["language"] == language]
        language64 = [task for task in nested64 if task["language"] == language]
        assert len(language96) == 24
        assert len(language64) == 16
        assert sorted(
            sum(task["patch_size_tertile"] == tertile for task in language64)
            for tertile in ("small", "medium", "large")
        ) == [5, 5, 6]
        assert all("passed" not in task and "resolved" not in task for task in language96)


def test_balanced_java_extension32_is_outcome_blind_and_disjoint():
    candidate = json.loads(
        (ROOT / "configs/swe_polybench_balanced_candidate96_v1.json").read_text()
    )
    extension = json.loads(
        (ROOT / "configs/swe_polybench_balanced_java_extension32_v1.json").read_text()
    )
    tasks = extension["tasks"]
    candidate_ids = {task["task_id"] for task in candidate["tasks"]}

    assert extension["selection"]["outcome_blind"] is True
    assert extension["selection"]["uses_target_model_outcomes"] is False
    assert len(tasks) == len({task["task_id"] for task in tasks}) == 32
    assert all(task["language"] == "java" for task in tasks)
    assert candidate_ids.isdisjoint(task["task_id"] for task in tasks)
    assert Counter(task["task_type"] for task in tasks) == Counter(
        {"Bug Fix": 20, "Feature": 8, "Refactoring": 4}
    )
    assert Counter(task["patch_size_tertile"] for task in tasks) == Counter(
        {"small": 10, "medium": 11, "large": 11}
    )
    assert max(Counter(task["repository"] for task in tasks).values()) <= 10
    suite_class = getattr(
        swe_polybench_module, "SwePolyBenchBalancedJavaExtension32Suite", None
    )
    assert suite_class is not None, "Java extension32 suite is not implemented"
    suite = suite_class()
    assert suite.get_task_ids(ROOT / "vendor") == [
        task["task_id"] for task in tasks
    ]


def test_balanced_java_strata_extension7_is_outcome_blind_and_disjoint():
    candidate_paths = (
        ROOT / "configs/swe_polybench_balanced_candidate96_v1.json",
        ROOT / "configs/swe_polybench_balanced_java_extension32_v1.json",
    )
    manifest_path = (
        ROOT / "configs/swe_polybench_balanced_java_strata_extension7_v1.json"
    )
    extension = json.loads(manifest_path.read_text())
    image_lock = json.loads(
        (
            ROOT
            / "configs/swe_polybench_balanced_java_strata_extension7_images_v1.json"
        ).read_text()
    )
    tasks = extension["tasks"]
    prior_ids = {
        task["task_id"]
        for path in candidate_paths
        for task in json.loads(path.read_text())["tasks"]
    }

    selector = runpy.run_path(str(ROOT / "scripts/select-polybench-panel.py"))
    assert selector["build_java_strata_extension_manifest"]() == extension
    assert image_lock["source_manifest_sha256"] == hashlib.sha256(
        manifest_path.read_bytes()
    ).hexdigest()
    assert extension["selection"]["outcome_blind"] is True
    assert extension["selection"]["uses_target_model_outcomes"] is False
    assert len(tasks) == len({task["task_id"] for task in tasks}) == 7
    assert prior_ids.isdisjoint(task["task_id"] for task in tasks)
    assert all(task["language"] == "java" for task in tasks)
    assert Counter(task["patch_size_tertile"] for task in tasks) == Counter(
        {"small": 4, "medium": 3}
    )
    assert all(task["task_type"] == "Bug Fix" for task in tasks)
    suite_class = getattr(
        swe_polybench_module,
        "SwePolyBenchBalancedJavaStrataExtension7Suite",
        None,
    )
    assert suite_class is not None, "Java strata extension7 suite is not implemented"
    assert suite_class().get_task_ids(ROOT / "vendor") == [
        task["task_id"] for task in tasks
    ]


def test_balanced64_is_repeat_qualified_and_loadable():
    manifest = json.loads(
        (ROOT / "configs/swe_polybench_verified_balanced64_v1.json").read_text()
    )
    image_lock = json.loads(
        (
            ROOT
            / "configs/swe_polybench_verified_balanced64_images_v1.json"
        ).read_text()
    )
    ledger = json.loads(
        (ROOT / "configs/swe_polybench_balanced_qualification_v1.json").read_text()
    )
    finalizer = runpy.run_path(
        str(ROOT / "scripts/finalize-polybench-panel.py")
    )
    expected_manifest, expected_image_lock = finalizer["build_outputs"]()
    tasks = manifest["tasks"]
    pilot_ids = set(SwePolyBenchVerifiedSuite().get_task_ids(ROOT / "vendor"))

    assert expected_manifest == manifest
    assert expected_image_lock == image_lock
    assert len(ledger["tasks"]) == 135
    assert ledger["summary"]["gold_stable_candidates"] == 82
    assert ledger["summary"]["repeat_qualified_candidates"] == 64
    assert ledger["summary"]["selected_nonpilot_null_resolved"] == 0
    assert image_lock["source_manifest_sha256"] == hashlib.sha256(
        (
            ROOT / "configs/swe_polybench_verified_balanced64_v1.json"
        ).read_bytes()
    ).hexdigest()
    assert manifest["selection"]["uses_target_model_outcomes"] is False
    assert manifest["qualification"]["observations_per_condition"] == 3
    assert manifest["qualification"]["gold_passed"] == 64 * 3
    assert manifest["qualification"]["null_failed"] == 64 * 3
    assert len(tasks) == len({task["task_id"] for task in tasks}) == 64
    assert pilot_ids.issubset(task["task_id"] for task in tasks)
    assert len(image_lock["images"]) == 64
    verifier_limit = manifest["selection"][
        "verifier_outlier_seconds_per_observation"
    ]
    assert all(
        task["qualification"]["gold_verifier_seconds"]
        / task["qualification"]["gold_observations"]
        <= verifier_limit
        for task in tasks
    )

    caps = manifest["selection"]["repository_caps"]
    type_targets = manifest["selection"]["task_type_targets"]
    size_targets = manifest["selection"]["patch_size_targets"]
    for language in ("java", "javascript", "python", "typescript"):
        selected = [task for task in tasks if task["language"] == language]
        assert len(selected) == 16
        assert Counter(task["task_type"] for task in selected) == Counter(
            type_targets[language]
        )
        assert set(type_targets[language]) == {"Bug Fix", "Feature", "Refactoring"}
        assert Counter(task["patch_size_tertile"] for task in selected) == Counter(
            size_targets[language]
        )
        assert max(size_targets[language].values()) - min(
            size_targets[language].values()
        ) <= 2
        assert max(Counter(task["repository"] for task in selected).values()) <= caps[
            language
        ]
        assert all(task["qualification"]["gold_passes"] == 3 for task in selected)
        assert all(task["qualification"]["null_failures"] == 3 for task in selected)

    suite = load_suite("swe_polybench_verified_balanced64")
    assert suite.task_count == 64
    assert suite.get_task_ids(ROOT / "vendor") == [
        task["task_id"] for task in tasks
    ]


def test_balanced_candidate96_materializes_tasks_outside_pilot28(tmp_path):
    suite_class = getattr(
        swe_polybench_module, "SwePolyBenchBalancedCandidate96Suite", None
    )
    assert suite_class is not None, "balanced candidate96 suite is not implemented"
    suite = suite_class()
    pilot_ids = set(SwePolyBenchVerifiedSuite().get_task_ids(ROOT / "vendor"))
    task_ids = suite.get_task_ids(ROOT / "vendor")
    task_id = next(candidate for candidate in task_ids if candidate not in pilot_ids)

    task = suite.materialize_task(task_id, tmp_path / "task", ROOT / "vendor")

    assert suite.task_count == len(task_ids) == 96
    assert task["task_id"] == task_id
    assert task["language"] in {"java", "javascript", "python", "typescript"}
    assert "patch" not in task and "test_patch" not in task
    assert "@sha256:" in task["image_ref"]


def test_suite_registry_loads_swe_polybench_verified():
    suite = load_suite("swe_polybench_verified")
    assert isinstance(suite, SwePolyBenchVerifiedSuite)
    assert suite.task_count == 28


def test_polybench_manifest_retains_only_repeat_qualified_tasks():
    suite = SwePolyBenchVerifiedSuite()
    qualification = suite.pilot["qualification"]
    exclusions = qualification["excluded"]

    assert suite.pilot["status"] == "ready_smoke"
    assert suite.pilot["pilot_size"] == suite.task_count == 28
    assert qualification["screened_size"] == 38
    assert qualification["observations_per_condition"] == 3
    assert {item["id"] for item in exclusions} == {
        "Significant-Gravitas__AutoGPT-4652",
        "angular__angular-37561",
        "apache__dubbo-4567",
        "apache__rocketmq-5008",
        "huggingface__transformers-29311",
        "microsoft__vscode-127071",
        "microsoft__vscode-135805",
        "microsoft__vscode-136347",
        "mrdoob__three.js-20991",
        "trinodb__trino-3859",
    }
    assert len(suite.selected) + len(exclusions) == qualification["screened_size"]
    assert set(suite.selected).isdisjoint(item["id"] for item in exclusions)
    assert all(item["reason"] for item in exclusions)


def test_polybench_dataset_loading_is_safe_across_verifier_threads():
    def load_ids(_):
        return SwePolyBenchVerifiedSuite().get_task_ids(ROOT / "vendor")

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        discovered = list(pool.map(load_ids, range(16)))
    assert all(len(task_ids) == 28 for task_ids in discovered)


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
    assert "git submodule foreach --recursive" in dockerfile
    assert "git ls-files -co --exclude-standard -z" in dockerfile
    assert "/opt/cospa/submodules.sha256" in dockerfile
    instruction = (task_root / "instruction.md").read_text()
    assert row["problem_statement"] in instruction
    assert row["patch"] not in instruction
    assert row["test_patch"] not in instruction
    assert "patch" not in task
    assert "test_patch" not in task

    assert (task_root / "tests" / "test.patch").read_text() == row["test_patch"]
    assert (task_root / "solution" / "gold.patch").read_text() == row["patch"]
    verifier = (task_root / "tests" / "test.sh").read_text()
    capture_at = verifier.index("git diff --ignore-submodules=all --binary")
    hidden_patch_at = verifier.index("git apply --whitespace=nowarn /tests/test.patch")
    model_patch_at = verifier.index(
        "git apply --whitespace=nowarn /logs/verifier/model.patch"
    )
    assert capture_at < hidden_patch_at < model_patch_at
    assert "git submodule foreach --recursive" in verifier
    assert "git ls-files -co --exclude-standard -z" in verifier
    assert "git diff --ignore-submodules=all --binary" in verifier
    assert '"submodule_patch_capturable":%s' in verifier
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


@pytest.mark.parametrize(
    "repo",
    ["mrdoob/three.js", "sveltejs/svelte", "serverless/serverless"],
)
def test_polybench_javascript_parsers_accept_raw_harbor_output(repo):
    output = (
        ROOT / "tests/fixtures/swe_polybench/javascript_mocha.log"
    ).read_text().split("Container exited", 1)[0].rstrip("\n")
    assert "Container exited" not in output
    parsed = parse_polybench_test_output(repo, output, ROOT / "vendor")
    assert parsed["passed_tests"] == ["Source > Maths > Vector3 > length/lengthSq"]
    assert parsed["failed_tests"] == ["Source > Maths > Box3 > intersectsPlane"]


def test_polybench_preserves_pinned_custom_reporter_outside_repository(tmp_path):
    suite = SwePolyBenchVerifiedSuite()
    task_root = tmp_path / "task"
    suite.materialize_task("mui__material-ui-15534", task_root, ROOT / "vendor")

    dockerfile = (task_root / "environment" / "Dockerfile").read_text()
    assert "cp /testbed/custom-reporter.js /opt/cospa/custom-reporter.js" in dockerfile
    assert dockerfile.index("cp /testbed/custom-reporter.js") < dockerfile.index(
        "git clean -fd"
    )
    verifier = (task_root / "tests" / "test.sh").read_text()
    assert "export NODE_PATH=/testbed/node_modules" in verifier
    assert "--reporter /opt/cospa/custom-reporter.js" in verifier
    assert "--reporter /testbed/custom-reporter.js" not in verifier


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


def test_polybench_verify_scores_unapplied_model_patch_as_incorrect(tmp_path):
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
    assert "verifier_failed" not in verdict
    assert verdict["failure_class"] == "incorrect"
