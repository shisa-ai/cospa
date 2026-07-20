"""Tests for the pinned SWE-bench-Live/MultiLang 24-task canary."""

import hashlib
import json
import os
import runpy
import subprocess
import sys
import tomllib
from collections import Counter
from pathlib import Path
from unittest.mock import patch

import pytest

from harness.adapters.pi_vanilla import PiVanillaAdapter
from harness.runner import run_trial
from harness.suites import load_suite


DATASET_REVISION = "608f7ae9ab8ea1f9f0d030fe04562cf6bd1a0c8b"
EVALUATOR_COMMIT = "70ec57e852e3f2d195790fe71f553e272c691833"
EXPECTED_TASK_IDS = [
    "fluent__fluent-bit-11722",
    "libarchive__libarchive-2968",
    "rizinorg__rizin-6079",
    "esphome__esphome-15814",
    "duckdb__duckdb-22152",
    "ChaiScript__ChaiScript-670",
    "MudBlazor__MudBlazor-13109",
    "ErikEJ__EFCorePowerTools-3417",
    "Azure__azure-sdk-for-net-58482",
    "danielmiessler__Fabric-2098",
    "sqlc-dev__sqlc-4383",
    "twpayne__chezmoi-5016",
    "floci-io__floci-463",
    "FasterXML__jackson-databind-5928",
    "langchain4j__langchain4j-4876",
    "usebruno__bruno-7620",
    "gsd-build__get-shit-done-2186",
    "sveltejs__svelte-18039",
    "ruffle-rs__ruffle-23330",
    "Automattic__harper-3112",
    "oxc-project__oxc-21330",
    "kepano__defuddle-243",
    "mnfst__manifest-1635",
    "puppeteer__puppeteer-14826",
]


def _row_hash(row: dict) -> str:
    payload = json.dumps(
        row,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def _fake_row(task: dict) -> dict:
    return {
        "instance_id": task["id"],
        "repo": task["repository"],
        "base_commit": task["base_commit"],
        "created_at": task["created_at"],
        "docker_image": task["source_image"],
        "problem_statement": "Fix the reported regression.",
        "patch": "diff --git a/source.txt b/source.txt\n+GOLD_SENTINEL\n",
        "test_patch": "diff --git a/test.txt b/test.txt\n+TEST_SENTINEL\n",
        "rebuild_cmds": ["true"],
        "test_cmds": ["true"],
        "print_cmds": ["printf 'pass case_a\\npass case_b\\n'"],
        "log_parser": (
            "def parser(log):\n"
            "    return {line.split()[1]: line.split()[0] "
            "for line in log.splitlines() if line.strip()}\n"
        ),
        "FAIL_TO_PASS": ["case_a"],
        "PASS_TO_PASS": ["case_b"],
    }


def _make_fake_vendor(tmp_path: Path, suite) -> tuple[Path, list[dict]]:
    manifest = json.loads(Path(suite.manifest_path).read_text())
    rows = []
    tasks = []
    for task in manifest["tasks"]:
        row = _fake_row(task)
        rows.append(row)
        tasks.append({**task, "row_sha256": _row_hash(row)})
    manifest["tasks"] = tasks
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest))
    suite.manifest_path = manifest_path

    vendor = tmp_path / "vendor"
    dataset_dir = vendor / "swe-bench-live-multilang"
    dataset_dir.mkdir(parents=True)
    (dataset_dir / "REVISION").write_text(DATASET_REVISION + "\n")
    (dataset_dir / "canary24.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in rows)
    )
    return vendor, rows


def test_suite_registry_loads_swe_bench_live_canary24():
    suite = load_suite("swe_bench_live_multilang_canary24")

    assert suite.name == "swe_bench_live_multilang_canary24"
    assert suite.version == "canary24-v1"
    assert suite.task_count == 24


def test_canary_manifest_freezes_balanced_recent_distinct_selection():
    suite = load_suite("swe_bench_live_multilang_canary24")
    manifest = json.loads(Path(suite.manifest_path).read_text())
    tasks = manifest["tasks"]

    assert manifest["dataset"]["revision"] == DATASET_REVISION
    assert manifest["evaluator"]["commit"] == EVALUATOR_COMMIT
    assert [task["id"] for task in tasks] == EXPECTED_TASK_IDS
    assert len(tasks) == len({task["id"] for task in tasks}) == 24
    assert len({task["repository"] for task in tasks}) == 24
    assert Counter(task["language"] for task in tasks) == {
        language: 3
        for language in ("c", "cpp", "cs", "go", "java", "js", "rust", "ts")
    }
    for language in {task["language"] for task in tasks}:
        assert Counter(
            task["patch_bucket"]
            for task in tasks
            if task["language"] == language
        ) == {"small": 1, "medium": 1, "large": 1}
    assert all(task["created_at"] >= "2026-03-01" for task in tasks)
    assert all(task["patch_lines"] <= 500 for task in tasks)
    assert all(task["fail_to_pass_count"] <= 50 for task in tasks)
    assert all(task["pass_to_pass_count"] <= 8000 for task in tasks)
    assert all(task["image_compressed_bytes"] <= 6 * 1024**3 for task in tasks)
    assert all(task["docker_digest"].startswith("sha256:") for task in tasks)
    assert all(len(task["row_sha256"]) == 64 for task in tasks)


def test_discovery_requires_exact_revision_complete_rows_and_hashes(tmp_path):
    suite = load_suite("swe_bench_live_multilang_canary24")
    vendor, rows = _make_fake_vendor(tmp_path, suite)

    assert suite.get_task_ids(vendor) == EXPECTED_TASK_IDS

    revision = vendor / "swe-bench-live-multilang" / "REVISION"
    revision.write_text("mutable-head\n")
    assert suite.get_task_ids(vendor) == []

    revision.write_text(DATASET_REVISION + "\n")
    rows[0]["problem_statement"] = "tampered"
    data_file = vendor / "swe-bench-live-multilang" / "canary24.jsonl"
    data_file.write_text("".join(json.dumps(row) + "\n" for row in rows))
    assert suite.get_task_ids(vendor) == []


def test_fetch_script_check_validates_rows_without_parquet_dependency(tmp_path):
    suite = load_suite("swe_bench_live_multilang_canary24")
    vendor, _ = _make_fake_vendor(tmp_path, suite)
    script = Path(__file__).resolve().parent.parent / "scripts" / "fetch-swe-bench-live.py"
    dataset_dir = vendor / "swe-bench-live-multilang"

    valid = subprocess.run(
        [
            sys.executable,
            str(script),
            "--manifest",
            str(suite.manifest_path),
            "--vendor-dir",
            str(dataset_dir),
            "--check",
        ],
        capture_output=True,
        text=True,
    )
    (dataset_dir / "REVISION").write_text("wrong-revision\n")
    invalid = subprocess.run(
        [
            sys.executable,
            str(script),
            "--manifest",
            str(suite.manifest_path),
            "--vendor-dir",
            str(dataset_dir),
            "--check",
        ],
        capture_output=True,
        text=True,
    )

    assert valid.returncode == 0, valid.stderr
    assert "validated 24" in valid.stdout
    assert invalid.returncode == 1
    assert "revision mismatch" in invalid.stderr


def test_materialize_keeps_test_and_gold_patches_hidden_from_instruction(tmp_path):
    suite = load_suite("swe_bench_live_multilang_canary24")
    vendor, _ = _make_fake_vendor(tmp_path, suite)
    task_id = suite.get_task_ids(vendor)[0]
    workdir = tmp_path / "workdir"

    task_data = suite.materialize_task(task_id, workdir, vendor)

    instruction = (workdir / "instruction.md").read_text()
    assert "TEST_SENTINEL" not in instruction
    assert "GOLD_SENTINEL" not in instruction
    assert "TEST_SENTINEL" in (workdir / "tests" / "test.patch").read_text()
    assert "GOLD_SENTINEL" in (workdir / "solution" / "gold.patch").read_text()
    assert (workdir / "environment").is_dir()
    assert (workdir / "tests" / "grader.py").is_file()
    test_script = (workdir / "tests" / "test.sh").read_text()
    assert "PYTHONNOUSERSITE=1" in test_script
    assert '"$python_bin" -I /tests/grader.py' in test_script
    assert (workdir / "solution" / "solve.sh").is_file()
    assert task_data["language"] == "c"
    assert task_data["dataset_revision"] == DATASET_REVISION

    config = tomllib.loads((workdir / "task.toml").read_text())
    expected_image = (
        task_data["source_image"] + "@" + task_data["docker_digest"]
    )
    assert config["environment"]["docker_image"] == expected_image
    assert config["environment"]["workdir"] == "/testbed"
    assert config["environment"]["network_mode"] == "public"
    assert config["agent"]["network_mode"] == "allowlist"
    assert config["verifier"]["network_mode"] == "no-network"


def test_grader_requires_every_f2p_and_p2p_test_to_be_present_and_pass(tmp_path):
    suite = load_suite("swe_bench_live_multilang_canary24")
    vendor, _ = _make_fake_vendor(tmp_path, suite)
    task_id = suite.get_task_ids(vendor)[0]
    workdir = tmp_path / "workdir"
    suite.materialize_task(task_id, workdir, vendor)
    grader = runpy.run_path(str(workdir / "tests" / "grader.py"))
    score_statuses = grader["score_statuses"]

    passed = score_statuses(
        {"case_a": "pass", "case_b": "pass"},
        fail_to_pass=["case_a"],
        pass_to_pass=["case_b"],
    )
    missing_regression = score_statuses(
        {"case_a": "pass"},
        fail_to_pass=["case_a"],
        pass_to_pass=["case_b"],
    )
    failed_fix = score_statuses(
        {"case_a": "fail", "case_b": "pass"},
        fail_to_pass=["case_a"],
        pass_to_pass=["case_b"],
    )

    assert passed["resolved"] is True
    assert missing_regression["resolved"] is False
    assert missing_regression["pass_to_pass"]["missing"] == ["case_b"]
    assert failed_fix["resolved"] is False
    assert failed_fix["fail_to_pass"]["failed"] == ["case_a"]


def test_hidden_grader_applies_test_patch_and_writes_native_reward(tmp_path):
    suite = load_suite("swe_bench_live_multilang_canary24")
    vendor, _ = _make_fake_vendor(tmp_path, suite)
    task_id = suite.get_task_ids(vendor)[0]
    workdir = tmp_path / "workdir"
    suite.materialize_task(task_id, workdir, vendor)

    repository = tmp_path / "testbed"
    repository.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repository, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=repository,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"], cwd=repository, check=True
    )
    (repository / "source.txt").write_text("base\n")
    subprocess.run(["git", "add", "source.txt"], cwd=repository, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=repository, check=True)

    tests_dir = workdir / "tests"
    (tests_dir / "test.patch").write_text(
        "diff --git a/hidden.txt b/hidden.txt\n"
        "new file mode 100644\n"
        "index 0000000..8b13789\n"
        "--- /dev/null\n"
        "+++ b/hidden.txt\n"
        "@@ -0,0 +1 @@\n"
        "+hidden\n"
    )
    task = json.loads((tests_dir / "task.json").read_text())
    task["rebuild_cmds"] = ["test -f hidden.txt"]
    task["test_cmds"] = ["true"]
    task["print_cmds"] = ["printf 'pass case_a\\npass case_b\\n'"]
    (tests_dir / "task.json").write_text(json.dumps(task))
    logs_dir = tmp_path / "verifier-logs"
    result = subprocess.run(
        [sys.executable, str(tests_dir / "grader.py")],
        env={
            **os.environ,
            "COSPA_TESTS_DIR": str(tests_dir),
            "COSPA_VERIFIER_LOGS_DIR": str(logs_dir),
            "COSPA_TESTBED_DIR": str(repository),
        },
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, (result.stdout, result.stderr)
    assert (repository / "hidden.txt").read_text() == "hidden\n"
    assert (logs_dir / "reward.txt").read_text() == "1\n"
    evaluation = json.loads((logs_dir / "evaluation.json").read_text())
    assert evaluation["resolved"] is True
    assert evaluation["observed_test_count"] == 2
    assert evaluation["infrastructure_error"] is None


def test_harbor_run_enforces_model_only_agent_and_offline_verifier(tmp_path):
    suite = load_suite("swe_bench_live_multilang_canary24")
    vendor, _ = _make_fake_vendor(tmp_path, suite)
    task_id = suite.get_task_ids(vendor)[0]
    workdir = tmp_path / "workdir"
    suite.materialize_task(task_id, workdir, vendor)
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = list(cmd)
        captured["env"] = kwargs["env"]
        task_path = Path(cmd[cmd.index("--path") + 1])
        captured["config"] = tomllib.loads((task_path / "task.toml").read_text())
        return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

    with patch.dict(
        os.environ,
        {"CODING_EVAL_HARBOR_MODEL_BASE_URL": "http://model-relay:8013/v1"},
    ), patch(
        "harness.suites.swe_bench_live.run_command",
        side_effect=fake_run,
    ):
        result = suite.run_harbor_job(
            task_id,
            "test/model",
            "pi_vanilla",
            workdir,
            tmp_path / "jobs",
            vendor_dir=vendor,
            thinking="high",
        )

    assert result["returncode"] == 0
    assert captured["cmd"][:2] == ["harbor", "run"]
    assert captured["cmd"][captured["cmd"].index("--n-attempts") + 1] == "1"
    assert captured["cmd"][captured["cmd"].index("--allow-agent-host") + 1] == (
        "model-relay"
    )
    assert captured["config"]["agent"]["network_mode"] == "allowlist"
    assert captured["config"]["agent"]["allowed_hosts"] == ["model-relay"]
    assert captured["config"]["verifier"]["network_mode"] == "no-network"
    assert captured["env"]["CODING_EVAL_CLEAN_AGENT_PROCESSES"] == "1"


def test_verify_uses_native_strict_result_and_surfaces_infrastructure(tmp_path):
    suite = load_suite("swe_bench_live_multilang_canary24")
    workdir = tmp_path / "trial-1" / "workdir"
    result_dir = tmp_path / "trial-1" / "jobs" / "job" / "task"
    verifier_dir = result_dir / "verifier"
    verifier_dir.mkdir(parents=True)
    (result_dir / "result.json").write_text(json.dumps({
        "verifier_result": {"rewards": {"reward": 1.0}},
        "exception_info": None,
    }))
    (verifier_dir / "evaluation.json").write_text(json.dumps({
        "resolved": False,
        "observed_test_count": 7,
        "infrastructure_error": "parser crashed",
    }))

    verdict = suite.verify({"task_id": "example"}, workdir)

    assert verdict["passed"] is False
    assert verdict["verifier_failed"] is True
    assert verdict["exit_code"] == -1
    assert verdict["native_evaluation"]["infrastructure_error"] == (
        "parser crashed"
    )


def test_manifest_records_dataset_image_task_and_verifier_pins(tmp_path):
    suite = load_suite("swe_bench_live_multilang_canary24")
    vendor, _ = _make_fake_vendor(tmp_path, suite)
    task_id = suite.get_task_ids(vendor)[0]

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
            PiVanillaAdapter(),
            "test/model",
            task_id,
            1,
            tmp_path / "results",
            vendor,
        )

    assert verdict["passed"] is True
    metadata = manifest["suite"]
    assert metadata["dataset_revision"] == DATASET_REVISION
    assert metadata["evaluator_commit"] == EVALUATOR_COMMIT
    assert metadata["language"] == "c"
    assert metadata["repository"] == "fluent/fluent-bit"
    assert metadata["docker_digest"].startswith("sha256:")
    assert metadata["image_compressed_bytes"] <= 6 * 1024**3
    assert len(metadata["dataset_row_sha256"]) == 64
    assert metadata["verifier_policy"] == "hidden-pr-tests-strict-f2p-p2p-v1"


@pytest.mark.requires_vendor
def test_real_pinned_canary_materializes_all_24_hidden_test_tasks(tmp_path):
    suite = load_suite("swe_bench_live_multilang_canary24")
    vendor = Path(__file__).resolve().parent.parent / "vendor"
    dataset = vendor / "swe-bench-live-multilang" / "canary24.jsonl"
    if not dataset.exists():
        pytest.skip("pinned SWE-bench-Live canary vendor data is absent")

    task_ids = suite.get_task_ids(vendor)
    assert task_ids == EXPECTED_TASK_IDS
    seen = Counter()
    for index, task_id in enumerate(task_ids):
        workdir = tmp_path / str(index)
        task_data = suite.materialize_task(task_id, workdir, vendor)
        assert task_data["prompt"].strip()
        assert (workdir / "tests" / "test.patch").stat().st_size > 0
        assert (workdir / "solution" / "gold.patch").stat().st_size > 0
        assert "test_patch" not in task_data
        assert "patch" not in task_data
        seen[task_data["language"]] += 1
    assert seen == {language: 3 for language in suite.languages}
