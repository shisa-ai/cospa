import importlib.util
import json
import subprocess
from pathlib import Path
from unittest import mock

import pytest


ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts" / "resolve-eval-images.py"


def load_module():
    spec = importlib.util.spec_from_file_location("resolve_eval_images", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_multi_swe_image_ref_matches_upstream_naming():
    module = load_module()
    assert module.multi_swe_image_ref("BurntSushi__ripgrep-727") == (
        "mswebench/burntsushi_m_ripgrep:pr-727"
    )
    assert module.multi_swe_image_ref("vuejs__core-10874") == (
        "mswebench/vuejs_m_core:pr-10874"
    )


def test_extract_amd64_digest_from_verbose_manifest_list():
    module = load_module()
    data = [
        {
            "Descriptor": {
                "digest": "sha256:" + "a" * 64,
                "platform": {"architecture": "amd64", "os": "linux"},
            }
        },
        {
            "Descriptor": {
                "digest": "sha256:" + "b" * 64,
                "platform": {"architecture": "unknown", "os": "unknown"},
            }
        },
    ]
    assert module.extract_platform_digest(data) == "sha256:" + "a" * 64


def test_extract_digest_from_single_platform_manifest():
    module = load_module()
    data = {"Descriptor": {"digest": "sha256:" + "c" * 64}}
    assert module.extract_platform_digest(data) == "sha256:" + "c" * 64


def test_collect_requests_includes_computed_multi_swe_and_verifier_image():
    module = load_module()
    pilot = {
        "suites": {
            "multi_swe_bench_flash": {
                "tasks": [{"id": "cli__cli-352"}],
            },
            "featurebench_lite": {
                "tasks": [{"id": "f1", "image_ref": "example/feature"}],
            },
            "bigcodebench_hard_instruct": {
                "verifier_image_ref": "example/verifier:v1",
                "tasks": [],
            },
        }
    }
    requests = module.collect_image_requests(pilot)
    assert requests == {
        "example/feature": {
            "suites": ["featurebench_lite"],
            "task_ids": ["f1"],
        },
        "example/verifier:v1": {
            "suites": ["bigcodebench_hard_instruct"],
            "task_ids": ["__verifier__"],
        },
        "mswebench/cli_m_cli:pr-352": {
            "suites": ["multi_swe_bench_flash"],
            "task_ids": ["cli__cli-352"],
        },
    }


def test_resolve_image_uses_docker_verbose_manifest_and_pins_digest():
    module = load_module()
    payload = {
        "Descriptor": {
            "digest": "sha256:" + "d" * 64,
            "platform": {"architecture": "amd64", "os": "linux"},
        }
    }
    completed = subprocess.CompletedProcess(
        args=[], returncode=0, stdout=json.dumps(payload), stderr=""
    )
    with mock.patch.object(module.subprocess, "run", return_value=completed) as run:
        resolved = module.resolve_image("registry:5000/team/image:latest")
    assert resolved == {
        "digest": "sha256:" + "d" * 64,
        "pinned_ref": "registry:5000/team/image@sha256:" + "d" * 64,
    }
    run.assert_called_once_with(
        [
            "docker",
            "manifest",
            "inspect",
            "--verbose",
            "registry:5000/team/image:latest",
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_resolve_image_retries_transient_docker_manifest_failure():
    module = load_module()
    payload = {"Descriptor": {"digest": "sha256:" + "f" * 64}}
    failure = subprocess.CalledProcessError(
        returncode=1,
        cmd=["docker", "manifest", "inspect"],
        stderr="temporary registry failure",
    )
    success = subprocess.CompletedProcess(
        args=[], returncode=0, stdout=json.dumps(payload), stderr=""
    )
    with (
        mock.patch.object(module.subprocess, "run", side_effect=[failure, success]) as run,
        mock.patch.object(module.time, "sleep") as sleep,
    ):
        resolved = module.resolve_image("example/image:latest", attempts=3)
    assert resolved["digest"] == "sha256:" + "f" * 64
    assert run.call_count == 2
    sleep.assert_called_once_with(1)


def test_extract_digest_fails_closed_without_linux_amd64():
    module = load_module()
    with pytest.raises(ValueError, match="linux/amd64"):
        module.extract_platform_digest(
            [
                {
                    "Descriptor": {
                        "digest": "sha256:" + "e" * 64,
                        "platform": {"architecture": "arm64", "os": "linux"},
                    }
                }
            ]
        )


def test_committed_lock_covers_exactly_the_selected_image_requests():
    module = load_module()
    pilot = json.loads((ROOT / "configs" / "ornith_runtime_pilot_v1.json").read_text())
    lock = json.loads(
        (ROOT / "configs" / "ornith_runtime_pilot_images_v1.json").read_text()
    )
    assert set(lock["images"]) == set(module.collect_image_requests(pilot))
