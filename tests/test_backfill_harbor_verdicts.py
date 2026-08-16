"""Harbor verdict-backfill tests.

These mirror the two real featurebench mislabels: the pytorch-lightning
``AgentTimeoutError`` recorded pre-``531d457`` as a generic adapter failure,
and the sympy ``NonZeroAgentExitCodeError`` whose embedded command hides a
provider ``Connection error.``.
"""

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from harness.backfill_harbor_verdicts import (  # noqa: E402
    backfill_results,
    derive_corrected,
)

PYTORCH_MANIFEST = {
    "exit_code": -1,
    "error": "AgentTimeoutError: Agent execution timed out after 3600.0 seconds",
    "budget_exhausted": None,
    "harbor_agent_exception": {
        "exception_type": "AgentTimeoutError",
        "exception_message": "Agent execution timed out after 3600.0 seconds",
    },
}
PYTORCH_VERDICT = {
    "passed": False,
    "test_count": 0,
    "grader_output": (
        "Adapter failed with exit code -1: AgentTimeoutError: Agent execution "
        "timed out after 3600.0 seconds"
    ),
    "exit_code": -1,
    "adapter_failed": True,
}

SYMPY_MANIFEST = {
    "exit_code": -1,
    "error": (
        "NonZeroAgentExitCodeError: Command failed (exit 1): bash -lc 'pi --print "
        "--thinking high # Benchmark execution context ... You are forbidden to "
        "access the following URLs: black_links ...' 2>&1 | tee /logs/x.txt\n"
        "stdout: Connection error.\n"
        "stderr: None"
    ),
    "budget_exhausted": None,
    "harbor_agent_exception": {
        "exception_type": "NonZeroAgentExitCodeError",
        "exception_message": "Command failed (exit 1): bash -lc '...'",
    },
}
SYMPY_VERDICT = {
    "passed": False,
    "test_count": 0,
    "grader_output": "Adapter failed with exit code -1: NonZeroAgentExitCodeError: ...",
    "exit_code": -1,
    "adapter_failed": True,
}


def test_timeout_derives_budget_exhausted():
    new_manifest, new_verdict = derive_corrected(PYTORCH_MANIFEST, PYTORCH_VERDICT)
    assert new_verdict["failure_class"] == "budget_exhausted"
    assert new_verdict["budget_exhausted"] is True
    assert new_verdict["exit_code"] == 124
    assert new_verdict["grader_output"] == PYTORCH_MANIFEST["error"]
    assert new_manifest["exit_code"] == 124
    assert new_manifest["budget_exhausted"] is True
    assert new_manifest["backfill"]["script"] == "backfill-harbor-verdicts"


def test_connection_error_derives_reclassification():
    new_manifest, new_verdict = derive_corrected(SYMPY_MANIFEST, SYMPY_VERDICT)
    assert new_verdict["failure_class"] == "connection_error"
    assert new_verdict["backfilled_failure_class"] is True
    # Raw error text is preserved; only the classification is added.
    assert new_manifest["error"] == SYMPY_MANIFEST["error"]


def test_no_agent_exception_is_untouched():
    manifest = {"exit_code": 0, "error": None, "budget_exhausted": None}
    verdict = {"passed": False, "failure_class": "incorrect"}
    assert derive_corrected(manifest, verdict) is None


def test_already_budget_is_unchanged():
    manifest = dict(PYTORCH_MANIFEST)
    manifest["exit_code"] = 124
    manifest["budget_exhausted"] = True
    verdict = {
        "passed": False,
        "test_count": 0,
        "grader_output": PYTORCH_MANIFEST["error"],
        "exit_code": 124,
        "budget_exhausted": True,
        "failure_class": "budget_exhausted",
    }
    assert derive_corrected(manifest, verdict) is None


def test_already_reclassified_is_unchanged():
    verdict = dict(SYMPY_VERDICT)
    verdict["failure_class"] = "connection_error"
    assert derive_corrected(SYMPY_MANIFEST, verdict) is None


def _write_trial(root: Path, task: str, manifest: dict, verdict: dict) -> None:
    trial = root / task / "trial-1"
    trial.mkdir(parents=True)
    (trial / "manifest.json").write_text(json.dumps(manifest))
    (trial / "verdict.json").write_text(json.dumps(verdict))


def test_backfill_results_writes_and_is_idempotent(tmp_path):
    root = tmp_path / "run"
    _write_trial(root, "pytorch-lightning", PYTORCH_MANIFEST, PYTORCH_VERDICT)
    _write_trial(root, "sympy", SYMPY_MANIFEST, SYMPY_VERDICT)
    # A verifier-graded incorrect with no agent exception must stay untouched.
    _write_trial(
        root,
        "plain-incorrect",
        {"exit_code": 0, "error": None, "budget_exhausted": None},
        {"passed": False, "failure_class": "incorrect", "grader_output": "1 failed"},
    )

    # Dry run: reports both updates, writes nothing.
    summary = backfill_results(root, dry_run=True)
    assert summary["scanned"] == 3
    assert summary["updated"] == 2
    assert (
        json.loads((root / "pytorch-lightning/trial-1/verdict.json").read_text()).get(
            "failure_class"
        )
        != "budget_exhausted"
    )

    # Real run: both mislabels fixed.
    summary = backfill_results(root)
    assert summary["updated"] == 2
    pt_verdict = json.loads((root / "pytorch-lightning/trial-1/verdict.json").read_text())
    assert pt_verdict["failure_class"] == "budget_exhausted"
    pt_manifest = json.loads((root / "pytorch-lightning/trial-1/manifest.json").read_text())
    assert pt_manifest["exit_code"] == 124
    assert pt_manifest["budget_exhausted"] is True
    sy_verdict = json.loads((root / "sympy/trial-1/verdict.json").read_text())
    assert sy_verdict["failure_class"] == "connection_error"
    plain = json.loads((root / "plain-incorrect/trial-1/verdict.json").read_text())
    assert plain["failure_class"] == "incorrect"

    # Idempotent: a second run changes nothing.
    summary = backfill_results(root)
    assert summary["updated"] == 0
    assert summary["unchanged"] == 3
