"""Circuit-breaker integration: runner pauses a cell after consecutive
provider outages instead of burning the remaining budget (RUN-MANAGEMENT P1).
"""

import argparse
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import pytest
from harness import runner as runner_mod


def _connection_error_manifest_verdict():
    manifest = {
        "timing": {"wall_clock_seconds": 1},
        "model_id": "codex/gpt-5.6-luna",
        "exit_code": -1,
        "error": (
            "NonZeroAgentExitCodeError: Command failed\n"
            "stdout: Connection error.\n"
            "stderr: None"
        ),
    }
    verdict = {
        "passed": False,
        "adapter_failed": True,
        "verifier_failed": False,
        "failure_class": "connection_error",
    }
    return manifest, verdict


def _run_main(tmp: Path, concurrency: int, no_circuit_breaker: bool):
    args = argparse.Namespace(
        suite="aider_polyglot",
        adapter="pi_vanilla",
        model="codex/gpt-5.6-luna",
        problems=None,
        task_ids=[f"python/t{i}" for i in range(5)],
        k=1,
        concurrency=concurrency,
        retries=0,
        thinking="off",
        results_dir=tmp / "results",
        run_id="run-cb",
        vendor_dir=tmp / "vendor",
        config=Path("/tmp/c"),
        skip_reachability=True,
        breaker_threshold=3,
        no_circuit_breaker=no_circuit_breaker,
    )
    calls = []

    def fake_run_trial(suite, adapter, model, task_id, trial_k, results_dir,
                       vendor_dir, thinking=None, **kwargs):
        calls.append((task_id, trial_k))
        return _connection_error_manifest_verdict()

    with patch.object(runner_mod, "parse_args", return_value=args), \
         patch.object(runner_mod, "load_suite") as mock_suite, \
         patch.object(runner_mod, "load_adapter") as mock_adapter, \
         patch.object(runner_mod, "run_trial_with_retries", side_effect=fake_run_trial):
        mock_suite.return_value.name = "aider_polyglot"
        mock_suite.return_value.get_task_ids.return_value = [
            f"python/t{i}" for i in range(5)
        ]
        mock_adapter.return_value.name = "pi_vanilla"
        runner_mod.main()
    return calls


def _heartbeat(tmp_path):
    results = tmp_path / "results"
    return next(results.rglob(".runner-heartbeat.json"))


def test_breaker_pauses_cell_and_writes_marker(tmp_path):
    """c=1: after threshold consecutive outages, stop and exit with code 3."""
    with pytest.raises(SystemExit) as excinfo:
        _run_main(tmp_path, concurrency=1, no_circuit_breaker=False)
    assert excinfo.value.code == runner_mod.PAUSE_EXIT_CODE == 3

    marker = tmp_path / "results" / ".cell-paused.json"
    assert marker.exists()
    data = json.loads(marker.read_text())
    assert data["state"] == "paused"
    assert data["reason"] == "circuit_breaker"
    assert data["breaker"]["open"] is True
    assert data["breaker"]["consecutive_outages"] == 3

    assert json.loads(_heartbeat(tmp_path).read_text())["state"] == "paused"


def test_breaker_disabled_runs_every_trial(tmp_path):
    """--no-circuit-breaker: all trials run to completion, no pause."""
    calls = _run_main(tmp_path, concurrency=1, no_circuit_breaker=True)
    assert len(calls) == 5
    assert not (tmp_path / "results" / ".cell-paused.json").exists()
    assert json.loads(_heartbeat(tmp_path).read_text())["state"] == "complete"


def test_breaker_bounded_submission_stops_scheduling(tmp_path):
    """c>1: a dead provider stops new trials once the breaker trips."""
    with pytest.raises(SystemExit) as excinfo:
        _run_main(tmp_path, concurrency=2, no_circuit_breaker=False)
    assert excinfo.value.code == runner_mod.PAUSE_EXIT_CODE
    marker = tmp_path / "results" / ".cell-paused.json"
    assert marker.exists()
    data = json.loads(marker.read_text())
    assert data["breaker"]["open"] is True
    assert data["breaker"]["consecutive_outages"] >= 3


def test_wrong_answers_never_trip_breaker(tmp_path):
    """A capability outcome (wrong answer) must not count as an outage."""
    args = argparse.Namespace(
        suite="aider_polyglot",
        adapter="pi_vanilla",
        model="codex/gpt-5.6-luna",
        problems=None,
        task_ids=[f"python/t{i}" for i in range(5)],
        k=1,
        concurrency=1,
        retries=0,
        thinking="off",
        results_dir=tmp_path / "results",
        run_id="run-cb2",
        vendor_dir=tmp_path / "vendor",
        config=Path("/tmp/c"),
        skip_reachability=True,
        breaker_threshold=3,
        no_circuit_breaker=False,
    )
    calls = []

    def fake_run_trial(suite, adapter, model, task_id, trial_k, results_dir,
                       vendor_dir, thinking=None, **kwargs):
        calls.append((task_id, trial_k))
        return (
            {"timing": {"wall_clock_seconds": 1}, "model_id": "codex/gpt-5.6-luna",
             "exit_code": 0, "error": None},
            {"passed": False, "adapter_failed": False, "verifier_failed": False,
             "failure_class": "incorrect"},
        )

    with patch.object(runner_mod, "parse_args", return_value=args), \
         patch.object(runner_mod, "load_suite") as mock_suite, \
         patch.object(runner_mod, "load_adapter") as mock_adapter, \
         patch.object(runner_mod, "run_trial_with_retries", side_effect=fake_run_trial):
        mock_suite.return_value.name = "aider_polyglot"
        mock_suite.return_value.get_task_ids.return_value = [
            f"python/t{i}" for i in range(5)
        ]
        mock_adapter.return_value.name = "pi_vanilla"
        runner_mod.main()

    assert len(calls) == 5, "wrong answers must not pause the cell"
    assert not (tmp_path / "results" / ".cell-paused.json").exists()
