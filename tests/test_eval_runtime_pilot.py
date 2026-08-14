import hashlib
import json
import subprocess
from collections import Counter
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[1]
PILOT_PATH = ROOT / "configs" / "ornith_runtime_pilot_v1.json"
IMAGE_LOCK_PATH = ROOT / "configs" / "ornith_runtime_pilot_images_v1.json"


def load_pilot():
    return json.loads(PILOT_PATH.read_text())


def test_first_wave_has_every_non_eliminated_candidate():
    pilot = load_pilot()
    assert list(pilot["suites"]) == [
        "aider_cospa_source",
        "terminal_bench_core_0_1_1",
        "swe_atlas_pilot12",
        "multi_swe_bench_flash",
        "swe_bench_multilingual",
        "swe_polybench_verified",
        "featurebench_lite",
        "bigcodebench_hard_instruct",
    ]
    assert {
        name: suite["pilot_size"] for name, suite in pilot["suites"].items()
    } == {
        "aider_cospa_source": 23,
        "terminal_bench_core_0_1_1": 8,
        "swe_atlas_pilot12": 12,
        "multi_swe_bench_flash": 30,
        "swe_bench_multilingual": 30,
        "swe_polybench_verified": 38,
        "featurebench_lite": 6,
        "bigcodebench_hard_instruct": 15,
    }


def test_runtime_policy_targets_safe_c16_and_twelve_hour_result():
    policy = load_pilot()["runtime_policy"]
    assert policy["concurrency_ladder"] == [1, 2, 4, 8, 16]
    assert policy["intended_production_concurrency"] == 16
    assert policy["routine_wall_target_hours"] == 12
    assert policy["campaign_budget_hours"] == 9.6
    assert policy["independent_trials"] == 1
    assert policy["adapter"] == "pi_vanilla"
    assert policy["model"] == "shisa/ornith-35b-fp8-block"


def test_aider_execution_remains_blocked_on_contract_review():
    suite = load_pilot()["suites"]["aider_cospa_source"]
    assert suite["status"] == "blocked_contract_audit"
    assert suite["task_ids"] == []
    assert suite["selection_after_audit"] == {
        "count": 23,
        "stratify_by": ["language", "concept_multiplicity", "category"],
        "outcome_blind": True,
    }


def test_frozen_task_ids_are_unique_and_match_declared_sizes():
    for name, suite in load_pilot()["suites"].items():
        if "tasks" not in suite:
            continue
        tasks = suite["tasks"]
        ids = [task["id"] for task in tasks]
        assert len(ids) == suite["pilot_size"], name
        assert len(ids) == len(set(ids)), name


def test_repository_pilots_cover_declared_language_strata():
    suites = load_pilot()["suites"]
    expected = {
        "multi_swe_bench_flash": {
            "c": 4,
            "c++": 4,
            "go": 5,
            "java": 4,
            "javascript": 5,
            "rust": 4,
            "typescript": 4,
        },
        "swe_bench_multilingual": {
            "c": 3,
            "c++": 1,
            "go": 4,
            "java": 4,
            "javascript": 3,
            "php": 4,
            "ruby": 5,
            "rust": 4,
            "typescript": 2,
        },
        "swe_polybench_verified": {
            "java": 7,
            "javascript": 10,
            "python": 11,
            "typescript": 10,
        },
    }
    for name, language_counts in expected.items():
        observed = Counter(task["language"] for task in suites[name]["tasks"])
        assert dict(sorted(observed.items())) == language_counts


def test_selection_manifest_contains_no_target_model_outcomes():
    forbidden = {"passed", "resolved", "score", "verdict", "model_outcome"}
    for suite in load_pilot()["suites"].values():
        for task in suite.get("tasks", []):
            assert forbidden.isdisjoint(task)


def test_polybench_preserves_task_type_mix():
    tasks = load_pilot()["suites"]["swe_polybench_verified"]["tasks"]
    assert Counter(task["task_type"] for task in tasks) == {
        "Bug Fix": 30,
        "Feature": 7,
        "Refactoring": 1,
    }


def test_external_artifacts_are_content_pinned():
    for name, suite in load_pilot()["suites"].items():
        source = suite["source"]
        assert len(source["revision"]) == 40, name
        if "dataset" in suite:
            dataset = suite["dataset"]
            assert len(dataset["revision"]) == 40, name
            assert len(dataset["sha256"]) == 64, name


def test_selected_images_are_digest_pinned_before_model_runs():
    pilot_bytes = PILOT_PATH.read_bytes()
    pilot = json.loads(pilot_bytes)
    lock = json.loads(IMAGE_LOCK_PATH.read_text())
    suites = pilot["suites"]
    selected_task_count = 0

    for name in (
        "multi_swe_bench_flash",
        "swe_bench_multilingual",
        "swe_polybench_verified",
        "featurebench_lite",
        "bigcodebench_hard_instruct",
    ):
        assert suites[name]["image_digest_status"] == "resolved"
        if name != "bigcodebench_hard_instruct":
            assert suites[name]["status"] == "blocked_gold_null_validation"
        selected_task_count += sum(
            1 for task in suites[name].get("tasks", []) if task.get("image_ref")
        )

    # Multi-SWE image names are computed by the resolver; BigCodeBench adds one
    # verifier image. Every selected task/verifier must have one immutable pin.
    selected_task_count += suites["multi_swe_bench_flash"]["pilot_size"]
    selected_task_count += 1
    assert len(lock["images"]) == selected_task_count == 105
    assert lock["source_manifest_sha256"] == hashlib.sha256(pilot_bytes).hexdigest()
    assert lock["platform"] == {"os": "linux", "architecture": "amd64"}
    for image in lock["images"].values():
        assert image["digest"].startswith("sha256:")
        assert len(image["digest"]) == 71
        assert image["pinned_ref"].endswith("@" + image["digest"])


@pytest.mark.requires_vendor
def test_present_vendor_artifacts_match_frozen_revisions_and_hashes():
    vendor = ROOT / "vendor"
    if not (vendor / "polyglot-benchmark" / ".git").exists():
        pytest.skip("external evaluation sources are not vendored")

    source_dirs = {
        "aider_cospa_source": "polyglot-benchmark",
        "terminal_bench_core_0_1_1": "terminal-bench",
        "swe_atlas_pilot12": "swe-atlas",
        "multi_swe_bench_flash": "multi-swe-bench",
        "swe_bench_multilingual": "swe-bench",
        "swe_polybench_verified": "swe-polybench",
        "featurebench_lite": "featurebench",
        "bigcodebench_hard_instruct": "bigcodebench",
    }
    suites = load_pilot()["suites"]
    for name, directory in source_dirs.items():
        repo = vendor / directory
        if not (repo / ".git").exists():
            pytest.fail(f"missing vendored source for {name}: {repo}")
        actual = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        assert actual == suites[name]["source"]["revision"], name

    for name, suite in suites.items():
        dataset = suite.get("dataset")
        if not dataset:
            continue
        path = ROOT / dataset["local_path"]
        assert path.is_file(), name
        assert hashlib.sha256(path.read_bytes()).hexdigest() == dataset["sha256"]

    terminal_tasks = vendor / "terminal-bench" / "tasks"
    for task in suites["terminal_bench_core_0_1_1"]["tasks"]:
        assert (terminal_tasks / task["id"]).is_dir(), task["id"]
