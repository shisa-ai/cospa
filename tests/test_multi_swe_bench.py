import json
import tomllib
from pathlib import Path

import pytest

from harness.suites import load_suite


ROOT = Path(__file__).parents[1]
DATASET = ROOT / "vendor/eval-data/multi-swe-flash/multi_swe_bench_flash.jsonl"


def selected_row(instance_id="jqlang__jq-1793"):
    with DATASET.open() as handle:
        for line in handle:
            row = json.loads(line)
            if row["instance_id"] == instance_id:
                return row
    raise AssertionError(instance_id)


def test_suite_registry_loads_multi_swe_bench_flash():
    suite = load_suite("multi_swe_bench_flash_hermetic25")
    assert suite.name == "multi_swe_bench_flash_hermetic25"
    assert suite.task_count == 25


def test_multi_swe_discovers_exact_frozen_selected_ids():
    suite = load_suite("multi_swe_bench_flash_hermetic25")
    panel = json.loads(
        (ROOT / "configs/multi_swe_bench_flash_hermetic25.json").read_text()
    )
    expected = [task["task_id"] for task in panel["tasks"]]
    assert suite.get_task_ids(ROOT / "vendor") == expected
    assert panel["selection"]["outcome_blind"] is True
    assert panel["selection"]["screened_tasks"] == 30
    assert panel["selection"]["retained_tasks"] == 25


def test_multi_swe_materializes_hidden_harbor_task_from_pinned_image(tmp_path):
    suite = load_suite("multi_swe_bench_flash_hermetic25")
    row = selected_row()
    task_root = tmp_path / "task"
    task = suite.materialize_task(row["instance_id"], task_root, ROOT / "vendor")

    config = tomllib.loads((task_root / "task.toml").read_text())
    assert config["agent"]["network_mode"] == "no-network"
    assert config["verifier"]["network_mode"] == "no-network"
    assert config["environment"]["network_mode"] == "public"
    assert "@sha256:" in task["image_ref"]

    dockerfile = (task_root / "environment/Dockerfile").read_text()
    assert dockerfile.startswith("FROM " + task["image_ref"] + "\n")
    assert f"git checkout --detach {row['base']['sha']}" in dockerfile
    assert "rm -f /home/fix.patch /home/test.patch" in dockerfile
    assert "git ls-files --others --exclude-standard" in dockerfile
    assert "-path '*/.git' -prune -o -type d -empty -printf '%P/\\n'" in dockerfile
    assert "git clean -fd" not in dockerfile
    assert "cat /opt/cospa/baseline-untracked >> .git/info/exclude" in dockerfile
    assert "tar --null -T /opt/cospa/baseline-untracked.z" in dockerfile
    assert "/opt/cospa/baseline-untracked.tar" in dockerfile
    assert "rm -rf .git" in dockerfile
    assert "git init" in dockerfile
    assert "ln -s" in dockerfile and "/testbed" in dockerfile

    instruction = (task_root / "instruction.md").read_text()
    assert row["resolved_issues"][0]["title"] in instruction
    issue_body = row["resolved_issues"][0]["body"].replace("\r\n", "\n").strip()
    assert issue_body in instruction
    assert row["fix_patch"] not in instruction
    assert row["test_patch"] not in instruction
    assert "fix_patch" not in task
    assert "test_patch" not in task
    assert "fix_patch" not in task["row"]
    assert "test_patch" not in task["row"]

    assert (task_root / "tests/test.patch").read_text() == row["test_patch"]
    assert (task_root / "solution/gold.patch").read_text() == row["fix_patch"]
    verifier = (task_root / "tests/test.sh").read_text()
    capture_at = verifier.index("git diff --binary")
    restore_at = verifier.index("tar -xf /opt/cospa/baseline-untracked.tar")
    hidden_at = verifier.index("git apply --whitespace=nowarn /tests/test.patch")
    replay_at = verifier.index(
        "git apply --whitespace=nowarn /logs/verifier/model.patch"
    )
    run_at = verifier.index("bash /home/run.sh")
    assert capture_at < restore_at < hidden_at < replay_at < run_at
    assert "/logs/verifier/status.json" in verifier
    assert "/logs/verifier/test_output.txt" in verifier


def test_multi_swe_pinned_c_parser_reads_real_make_check_output():
    suite = load_suite("multi_swe_bench_flash_hermetic25")
    row = selected_row()
    output = (ROOT / "tests/fixtures/multi_swe/c_make_check.log").read_text()
    parsed = suite.parse_test_output(row, output, ROOT / "vendor")
    assert "tests/utf8test" in parsed["passed_tests"]
    assert parsed["failed_tests"] == ["tests/jqtest"]
    assert parsed["skipped_tests"] == []


@pytest.mark.parametrize(
    ("task_id", "fixture", "passed", "failed"),
    [
        ("fmtlib__fmt-3158", "cpp_ctest.log", "args-test", None),
        (
            "cli__cli-2263",
            "go_test_v.log",
            "TestGraphQL",
            "github.com/cli/cli/git",
        ),
        (
            "google__gson-1555",
            "java_maven.log",
            "com.google.gson.CommentsTest",
            "com.google.gson.functional.JsonAdapterSerializerDeserializerTest",
        ),
        (
            "iamkun__dayjs-1953",
            "javascript_jest.log",
            "test/comparison.test.js:is after day",
            "test/display.test.js:Format Year YY YYYY",
        ),
        (
            "BurntSushi__ripgrep-727",
            "rust_cargo_test.log",
            "after_context",
            "suggest_fixed_strings_for_invalid_regex",
        ),
        (
            "vuejs__core-10218",
            "typescript_vitest.log",
            "packages/compiler-core/__tests__/codegen.spec.ts > compiler: codegen > ArrayExpression",
            "packages/compiler-core/__tests__/transforms/transformSlotOutlet.spec.ts > compiler: transform <slot> outlets > dynamically named slot outlet with v-bind shorthand",
        ),
    ],
)
def test_multi_swe_pinned_parsers_cover_other_real_language_outputs(
    task_id, fixture, passed, failed
):
    suite = load_suite("multi_swe_bench_flash_hermetic25")
    row = selected_row(task_id)
    output = (ROOT / "tests/fixtures/multi_swe" / fixture).read_text()
    parsed = suite.parse_test_output(row, output, ROOT / "vendor")
    assert passed in parsed["passed_tests"]
    if failed is not None:
        assert failed in parsed["failed_tests"]


def test_multi_swe_express_parser_deserializes_real_mocha_json_objects():
    suite = load_suite("multi_swe_bench_flash_hermetic25")
    row = selected_row("expressjs__express-3495")
    output = (
        ROOT / "tests/fixtures/multi_swe/javascript_mocha_json.log"
    ).read_text()
    parsed = suite.parse_test_output(row, output, ROOT / "vendor")
    assert parsed["passed_tests"] == ["Route should work without handlers"]
    assert parsed["failed_tests"] == [
        "req .hostname when trust proxy is enabled should use the first value"
    ]


def test_multi_swe_score_requires_every_transition_and_no_regression():
    suite = load_suite("multi_swe_bench_flash_hermetic25")
    row = selected_row()
    f2p = sorted(row["f2p_tests"])
    p2p = sorted(row["p2p_tests"])
    assert f2p and p2p

    passing = suite.score_result(
        {
            "passed_tests": f2p + p2p,
            "failed_tests": [],
            "skipped_tests": [],
        },
        row,
    )
    assert passing["passed"] is True
    assert passing["all_f2p_passed"] is True
    assert passing["no_p2p_failed"] is True

    failing = suite.score_result(
        {
            "passed_tests": p2p,
            "failed_tests": f2p,
            "skipped_tests": [],
        },
        row,
    )
    assert failing["passed"] is False
    assert failing["failure_class"] == "incorrect"


def test_multi_swe_model_patch_conflict_is_an_incorrect_outcome(tmp_path):
    suite = load_suite("multi_swe_bench_flash_hermetic25")
    task_root = tmp_path / "trial/workdir"
    row = selected_row()
    task = suite.materialize_task(row["instance_id"], task_root, ROOT / "vendor")
    artifacts = task_root.parent / "jobs/job-1/artifacts/verifier"
    artifacts.mkdir(parents=True)
    (artifacts / "model.patch").write_text("invalid model patch\n")
    (artifacts / "status.json").write_text(
        json.dumps(
            {
                "test_patch_applied": True,
                "model_patch_applied": False,
                "test_exit_code": -1,
            }
        )
    )
    (artifacts / "test_output.txt").write_text("Model patch failed to apply\n")

    verdict = suite.verify(task, task_root)

    assert verdict["passed"] is False
    assert verdict["failure_class"] == "incorrect"
    assert verdict["exit_code"] == 1
    assert verdict["model_patch_applied"] is False
    assert verdict["model_patch_bytes"] > 0
    assert not verdict.get("verifier_failed")


def test_multi_swe_verify_reads_harbor_artifacts(tmp_path):
    suite = load_suite("multi_swe_bench_flash_hermetic25")
    task_root = tmp_path / "trial/workdir"
    row = selected_row()
    task = suite.materialize_task(row["instance_id"], task_root, ROOT / "vendor")
    artifacts = task_root.parent / "jobs/job-1/artifacts/verifier"
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
    expected = sorted(row["f2p_tests"] | row["p2p_tests"])
    (artifacts / "test_output.txt").write_text(
        "\n".join(f"PASS: {name}" for name in expected) + "\n"
    )

    verdict = suite.verify(task, task_root)
    assert verdict["passed"] is True
    assert verdict["failure_class"] == "resolved"
    assert verdict["model_patch_bytes"] > 0
