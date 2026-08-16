"""
Tests for runner failure semantics.

A nonzero adapter return code MUST be treated as adapter failure and skip
suite verification. This prevents false passes when starter code already
satisfies a (broken or absent) verifier.

These tests use a fake adapter that returns a nonzero return code with no
error string, exactly the failure mode called out in
ORNITH-CODER-REVIEW.md finding #6 / follow-up audit item C.
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from harness.adapters.pi_vanilla import PiVanillaAdapter, AdapterResult
from harness.suites.aider_polyglot import AiderPolyglotSuite
from harness.runner import run_trial, run_trial_with_retries


class FakeFailingAdapter:
    """Adapter whose subprocess exits nonzero without setting `error`."""

    name = "fake_failing"
    version = "test"

    def run(self, task_data, workdir, log_file, stderr_file):
        # Exactly the regression shape from the audit: nonzero rc, no error
        return AdapterResult(returncode=1, error=None)


class FakePassingAdapter:
    """Adapter whose subprocess exits successfully."""

    name = "fake_passing"
    version = "test"

    def run(self, task_data, workdir, log_file, stderr_file):
        return AdapterResult(returncode=0, error=None)


class FakeFlakyInfraAdapter:
    """Adapter that fails once like an infrastructure error, then succeeds."""

    name = "fake_flaky_infra"
    version = "test"

    def __init__(self):
        self.calls = 0

    def run(self, task_data, workdir, log_file, stderr_file):
        self.calls += 1
        if self.calls == 1:
            return AdapterResult(returncode=-1, error="adapter timed out")
        return AdapterResult(returncode=0, error=None)


class FakeWorkspaceTimeoutAdapter:
    """Workspace adapter that reaches the declared agent wall deadline."""

    name = "fake_workspace_timeout"
    version = "test"

    def __init__(self):
        self.calls = 0

    def run(self, task_data, workdir, log_file, stderr_file):
        self.calls += 1
        return type(
            "TimeoutResult",
            (),
            {
                "returncode": -1,
                "error": "Agent capability budget exhausted",
                "budget_exhausted": True,
                "usage": None,
            },
        )()


class FakeHarborTimeoutSuite:
    """Harbor suite whose agent reaches its declared capability deadline."""

    name = "fake_harbor_timeout"
    verify_on_adapter_failure = True

    def __init__(self):
        self.run_calls = 0
        self.verify_calls = 0

    def materialize_task(self, task_id, workdir, vendor_dir):
        return {"prompt": "solve it", "task_id": task_id}

    def run_harbor_job(self, **kwargs):
        self.run_calls += 1
        result_dir = Path(kwargs["jobs_dir"]) / "run" / "trial"
        result_dir.mkdir(parents=True)
        (result_dir / "result.json").write_text(json.dumps({
            "exception_info": {
                "exception_type": "AgentTimeoutError",
                "exception_message": "Agent timed out after 3600 seconds",
            }
        }))
        return {"returncode": 0, "stdout": "", "stderr": ""}

    def verify(self, task_data, workdir):
        self.verify_calls += 1
        raise AssertionError("timeout must not invoke the benchmark verifier")


class FakeWrongAnswerSuite:
    """Minimal suite for retry behavior tests."""

    name = "fake_suite"

    def __init__(self, passed: bool):
        self.passed = passed
        self.verify_calls = 0

    def materialize_task(self, task_id, workdir, vendor_dir):
        return {"prompt": "solve it", "task_id": task_id}

    def verify(self, task_data, workdir):
        self.verify_calls += 1
        return {
            "passed": self.passed,
            "test_count": 1,
            "grader_output": "ok" if self.passed else "wrong answer",
            "exit_code": 0,
        }


def _make_aider_problem(vendor_dir: Path):
    """Build a real-shaped polyglot-benchmark problem."""
    pdir = (
        vendor_dir
        / "polyglot-benchmark"
        / "python"
        / "exercises"
        / "practice"
        / "two-fer"
    )
    pdir.mkdir(parents=True)
    (pdir / ".docs").mkdir()
    (pdir / ".docs" / "instructions.md").write_text("Write a two-fer function")
    (pdir / "two_fer.py").write_text("def two_fer(name=None):\n    pass\n")
    (pdir / "two_fer_test.py").write_text(
        "from two_fer import two_fer\n"
        "def test_two_fer():\n    assert two_fer() == 'One for you, one for me.'"
    )


def test_nonzero_adapter_return_code_marks_failure_and_skips_verify(monkeypatch):
    """A nonzero adapter rc with no error must skip verification and record failure."""
    suite = AiderPolyglotSuite()
    adapter = FakeFailingAdapter()

    # Track whether suite.verify() was called — it must NOT be.
    verify_calls = []
    original_verify = suite.verify

    def spy_verify(task_data, workdir):
        verify_calls.append(task_data)
        return original_verify(task_data, workdir)

    monkeypatch.setattr(suite, "verify", spy_verify)

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        vendor_dir = tmp / "vendor"
        vendor_dir.mkdir()
        _make_aider_problem(vendor_dir)
        results_dir = tmp / "results"

        manifest, verdict = run_trial(
            suite, adapter, "test/model", "python/two-fer", 1,
            results_dir, vendor_dir,
        )

    # Verification must not have run for a failed adapter
    assert verify_calls == [], (
        f"suite.verify() must not run after adapter failure, got {verify_calls}"
    )

    # Verdict must reflect adapter failure
    assert verdict["passed"] is False, (
        f"verdict.passed must be False after adapter failure, got {verdict}"
    )
    assert verdict.get("adapter_failed") is True, (
        f"verdict.adapter_failed must be True, got {verdict}"
    )

    # Manifest exit code reflects the real nonzero rc
    assert manifest["exit_code"] == 1, (
        f"manifest.exit_code must be the adapter's nonzero rc, got {manifest['exit_code']}"
    )


def test_verify_exception_records_failed_verdict_and_manifest(monkeypatch):
    """Verifier crashes must produce durable failure artifacts."""
    suite = AiderPolyglotSuite()
    adapter = FakePassingAdapter()

    def boom(task_data, workdir):
        raise FileNotFoundError("workdir disappeared")

    monkeypatch.setattr(suite, "verify", boom)

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        vendor_dir = tmp / "vendor"
        vendor_dir.mkdir()
        _make_aider_problem(vendor_dir)
        results_dir = tmp / "results"

        manifest, verdict = run_trial(
            suite, adapter, "test/model", "python/two-fer", 1,
            results_dir, vendor_dir,
        )
        trial_dir = (
            results_dir
            / "test%2Fmodel"
            / "fake_passing"
            / "aider_polyglot"
            / "python%2Ftwo-fer"
            / "trial-1"
        )
        manifest_exists = (trial_dir / "manifest.json").exists()
        verdict_exists = (trial_dir / "verdict.json").exists()

    assert verdict["passed"] is False
    assert verdict["verifier_failed"] is True
    assert "workdir disappeared" in verdict["grader_output"]
    assert manifest["error"] == "Verifier raised: workdir disappeared"
    assert manifest_exists
    assert verdict_exists


def test_retry_retries_infrastructure_failure_then_records_success():
    """Infra failures should be retried before recording the final verdict."""
    suite = FakeWrongAnswerSuite(passed=True)
    adapter = FakeFlakyInfraAdapter()

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        manifest, verdict = run_trial_with_retries(
            suite,
            adapter,
            "test/model",
            "task/one",
            1,
            tmp / "results",
            tmp / "vendor",
            retries=2,
        )

    assert adapter.calls == 2
    assert verdict["passed"] is True
    assert manifest["retry"]["attempt"] == 2
    assert manifest["retry"]["max_attempts"] == 3


def test_pi_vanilla_marks_subprocess_timeout_as_budget_exhausted(tmp_path):
    """The real workspace adapter must distinguish its wall deadline from infra."""
    adapter = PiVanillaAdapter()
    with (
        patch("harness.adapters.pi_vanilla.validate_pi_sampling_params"),
        patch(
            "harness.adapters.pi_vanilla.run_command",
            side_effect=subprocess.TimeoutExpired(["pi"], 30),
        ),
    ):
        result = adapter.run(
            {
                "model_id": "test/model",
                "prompt": "solve it",
                "problem": "task-one",
                "timeout": 30,
            },
            tmp_path,
            tmp_path / "session.log",
            tmp_path / "stderr.log",
        )

    assert result.returncode == -1
    assert result.budget_exhausted is True


def test_retry_does_not_retry_workspace_agent_budget_exhaustion():
    """A workspace-agent wall deadline is capability signal, not infrastructure."""
    suite = FakeWrongAnswerSuite(passed=True)
    adapter = FakeWorkspaceTimeoutAdapter()

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        manifest, verdict = run_trial_with_retries(
            suite,
            adapter,
            "test/model",
            "task/one",
            1,
            tmp / "results",
            tmp / "vendor",
            retries=2,
        )

    assert adapter.calls == 1
    assert suite.verify_calls == 0
    assert manifest["exit_code"] == 124
    assert manifest["budget_exhausted"] is True
    assert "retry" not in manifest
    assert verdict["passed"] is False
    assert verdict["failure_class"] == "budget_exhausted"
    assert verdict["budget_exhausted"] is True
    assert verdict.get("adapter_failed") is not True


def test_retry_does_not_retry_harbor_agent_budget_exhaustion():
    """A declared agent deadline is capability signal, not retryable infrastructure."""
    suite = FakeHarborTimeoutSuite()
    adapter = FakePassingAdapter()

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        manifest, verdict = run_trial_with_retries(
            suite,
            adapter,
            "test/model",
            "task/one",
            1,
            tmp / "results",
            tmp / "vendor",
            retries=2,
        )

    assert suite.run_calls == 1
    assert suite.verify_calls == 0
    assert manifest["exit_code"] == 124
    assert manifest["budget_exhausted"] is True
    assert "retry" not in manifest
    assert verdict["passed"] is False
    assert verdict["failure_class"] == "budget_exhausted"
    assert verdict["budget_exhausted"] is True
    assert verdict.get("adapter_failed") is not True


def test_retry_does_not_retry_normal_wrong_answer():
    """A valid but wrong solution is benchmark signal, not infrastructure."""
    suite = FakeWrongAnswerSuite(passed=False)
    adapter = FakePassingAdapter()

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        manifest, verdict = run_trial_with_retries(
            suite,
            adapter,
            "test/model",
            "task/one",
            1,
            tmp / "results",
            tmp / "vendor",
            retries=2,
        )

    assert suite.verify_calls == 1
    assert verdict["passed"] is False
    assert "retry" not in manifest


def test_zero_adapter_return_code_still_runs_verify():
    """Sanity: when the adapter succeeds, verification runs as normal."""
    suite = AiderPolyglotSuite()
    adapter = PiVanillaAdapter()

    verify_calls = []
    original_verify = suite.verify

    def spy_verify(task_data, workdir):
        verify_calls.append(task_data)
        return original_verify(task_data, workdir)

    suite.verify = spy_verify

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        vendor_dir = tmp / "vendor"
        vendor_dir.mkdir()
        _make_aider_problem(vendor_dir)
        results_dir = tmp / "results"

        with patch("harness.adapters.pi_vanilla.run_command") as mock_run:
            mock_run.return_value.__class__ = lambda x: x  # noqa
            # Use a real CompletedProcess-like object
            import subprocess as sp
            mock_run.return_value = sp.CompletedProcess(
                args=[], returncode=0, stdout="ok", stderr=""
            )
            run_trial(
                suite, adapter, "test/model", "python/two-fer", 1,
                results_dir, vendor_dir,
            )

    assert len(verify_calls) == 1, "verify() should run once when adapter succeeds"
    suite.verify = original_verify
