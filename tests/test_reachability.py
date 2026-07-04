"""
Tests for model reachability enforcement.

PLAN.md (lines 137-138) says the runner refuses to start if a model in the
matrix is unreachable. The runner never calls any model check. These tests
pin the contract for an in-process reachability check wired into runner
startup with a --skip-reachability opt-out.

We stub the reachability check rather than hitting real endpoints.
"""

import sys
import tempfile
import json
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from harness.runner import check_model_reachable, should_run_reachability_check


def test_check_model_reachable_returns_bool():
    """check_model_reachable must return a bool for a model id."""
    with patch("subprocess.run") as mock:
        import subprocess as sp
        mock.return_value = sp.CompletedProcess(
            args=[], returncode=0, stdout='{"data":[]}', stderr=""
        )
        result = check_model_reachable("test/model")
    assert isinstance(result, bool), result


def test_check_model_reachable_sends_provider_api_key(monkeypatch, tmp_path):
    """Reachability probes must authenticate with apiKey from models.json."""
    models_json = tmp_path / ".pi" / "agent" / "models.json"
    models_json.parent.mkdir(parents=True)
    models_json.write_text(json.dumps({
        "providers": {
            "test": {
                "baseUrl": "http://provider.test/v1",
                "apiKey": "secret-key",
                "models": [{"id": "test/model-one"}],
            }
        }
    }))
    monkeypatch.setenv("HOME", str(tmp_path))

    requests = []

    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    def fake_urlopen(req, timeout):
        requests.append(req)
        return FakeResponse()

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        assert check_model_reachable("test/model-one") is True

    assert requests, "expected one reachability request"
    assert requests[0].headers.get("Authorization") == "Bearer secret-key"
    assert json.loads(requests[0].data.decode())["model"] == "test/model-one"


def test_should_run_reachability_check_default_true():
    """By default (no --skip-reachability), the check is enabled."""
    assert should_run_reachability_check(skip=False) is True


def test_should_run_reachability_check_disabled_by_flag():
    """--skip-reachability disables the check."""
    assert should_run_reachability_check(skip=True) is False


def test_runner_main_aborts_when_model_unreachable():
    """main() must refuse to start when the model is unreachable."""
    import argparse
    from harness import runner as runner_mod

    # Build a fake args namespace
    args = argparse.Namespace(
        suite="aider_polyglot",
        adapter="pi_vanilla",
        model="test/unreachable-model",
        problems=1,
        k=1,
        results_dir=Path("/tmp/x"),
        vendor_dir=Path("/tmp/v"),
        config=Path("/tmp/c"),
        skip_reachability=False,
    )

    with patch.object(runner_mod, "parse_args", return_value=args), \
         patch.object(runner_mod, "check_model_reachable", return_value=False), \
         patch.object(runner_mod, "load_suite") as mock_suite, \
         patch.object(runner_mod, "load_adapter") as mock_adapter:
        # main() should exit nonzero WITHOUT calling load_suite/load_adapter
        try:
            runner_mod.main()
        except SystemExit as e:
            assert e.code != 0, f"expected nonzero exit, got {e.code}"
        else:
            assert False, "main() must exit when model is unreachable"

    mock_suite.assert_not_called()
    mock_adapter.assert_not_called()


def test_runner_main_proceeds_with_skip_reachability():
    """main() must proceed past the reachability check when --skip-reachability."""
    import argparse
    from harness import runner as runner_mod

    args = argparse.Namespace(
        suite="aider_polyglot",
        adapter="pi_vanilla",
        model="test/unreachable-model",
        problems=1,
        k=1,
        results_dir=Path(tempfile.mkdtemp()),
        vendor_dir=Path(tempfile.mkdtemp()),
        config=Path("/tmp/c"),
        skip_reachability=True,
    )

    check_called = []

    def fake_check(model, **kwargs):
        check_called.append(model)
        return False

    with patch.object(runner_mod, "parse_args", return_value=args), \
         patch.object(runner_mod, "check_model_reachable", side_effect=fake_check), \
         patch.object(runner_mod, "load_suite") as mock_suite, \
         patch.object(runner_mod, "load_adapter") as mock_adapter, \
         patch.object(runner_mod, "run_trial") as mock_run_trial:
        # Make load_suite return something with get_task_ids
        fake_suite = mock_suite.return_value
        fake_suite.get_task_ids.return_value = []
        try:
            runner_mod.main()
        except SystemExit:
            pass

    # With skip_reachability=True, main must NOT abort before load_suite
    mock_suite.assert_called()


def test_runner_main_aborts_when_suite_has_no_tasks():
    """Missing/empty datasets must fail loudly instead of producing a green no-op run."""
    import argparse
    from harness import runner as runner_mod

    args = argparse.Namespace(
        suite="aider_polyglot",
        adapter="pi_vanilla",
        model="test/model",
        problems=1,
        k=1,
        results_dir=Path(tempfile.mkdtemp()),
        vendor_dir=Path(tempfile.mkdtemp()),
        config=Path("/tmp/c"),
        skip_reachability=True,
    )

    with patch.object(runner_mod, "parse_args", return_value=args), \
         patch.object(runner_mod, "load_suite") as mock_suite, \
         patch.object(runner_mod, "load_adapter") as mock_adapter, \
         patch.object(runner_mod, "run_trial") as mock_run_trial:
        fake_suite = mock_suite.return_value
        fake_suite.get_task_ids.return_value = []

        try:
            runner_mod.main()
        except SystemExit as e:
            assert e.code != 0, f"expected nonzero exit, got {e.code}"
        else:
            assert False, "main() must exit when no tasks are discovered"

    mock_adapter.assert_called()
    mock_run_trial.assert_not_called()
