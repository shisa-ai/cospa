import importlib
import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from harness import runner


def _load_harbor_docker():
    path = Path(__file__).parents[1] / "harness" / "harbor_docker.py"
    assert path.is_file(), "harness/harbor_docker.py must implement safe cleanup"
    return importlib.import_module("harness.harbor_docker")


def test_reclaim_stale_harbor_networks_preserves_active_recent_and_unrelated():
    now = datetime(2026, 8, 16, tzinfo=timezone.utc)
    old = (now - timedelta(hours=1)).isoformat()
    recent = (now - timedelta(seconds=30)).isoformat()
    inspected = [
        {
            "Id": "stale-id",
            "Name": "workdir__stale__env_default",
            "Created": old,
            "Containers": {},
        },
        {
            "Id": "active-id",
            "Name": "workdir__active__env_default",
            "Created": old,
            "Containers": {"container-id": {"Name": "active"}},
        },
        {
            "Id": "recent-id",
            "Name": "workdir__recent__env_default",
            "Created": recent,
            "Containers": {},
        },
        {
            "Id": "unrelated-id",
            "Name": "project_default",
            "Created": old,
            "Containers": {},
        },
    ]
    responses = [
        subprocess.CompletedProcess(
            [],
            0,
            stdout="stale-id\nactive-id\nrecent-id\nunrelated-id\n",
            stderr="",
        ),
        subprocess.CompletedProcess(
            [], 0, stdout=json.dumps(inspected), stderr=""
        ),
        subprocess.CompletedProcess([], 0, stdout="stale-id\n", stderr=""),
    ]

    harbor_docker = _load_harbor_docker()
    with patch.object(
        harbor_docker.subprocess, "run", side_effect=responses
    ) as run:
        removed = harbor_docker.reclaim_stale_harbor_networks(
            min_age_seconds=300,
            now=now,
        )

    assert removed == ["workdir__stale__env_default"]
    assert run.call_count == 3
    assert run.call_args_list[-1].args[0] == [
        "docker",
        "network",
        "rm",
        "stale-id",
    ]


def test_prepare_suite_runtime_reclaims_networks_only_for_harbor_suites():
    class HarborSuite:
        def run_harbor_job(self):
            pass

    class LocalSuite:
        pass

    with patch.object(
        runner, "reclaim_stale_harbor_networks", return_value=["old"]
    ) as reclaim:
        assert runner.prepare_suite_runtime(HarborSuite()) == ["old"]
        assert runner.prepare_suite_runtime(LocalSuite()) == []

    reclaim.assert_called_once_with()
