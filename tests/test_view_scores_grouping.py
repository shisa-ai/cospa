"""
Tests for multi-dimensional score grouping.

cospa's central axis is capability-per-cost, and the same model can be
served at multiple effort levels (default / high / xhigh) and by multiple
providers (aiand's quant vs local nvfp4 vs nvidia hosted). The viewer
MUST distinguish these — otherwise two runs at different thinking levels
(or different providers) silently merge into one row, corrupting the
score and the cost comparison.

Grouping key must be:
    (model_id, adapter, suite, thinking, provider)

These tests are RED against the current (model, adapter, suite) grouping.
"""

import json
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from harness.path_utils import encode_model_path, encode_task_path


def _write_trial_v2(trial_dir: Path, *, passed=True, model_id, adapter,
                    suite="aider_polyglot", task_id="python/hello",
                    thinking=None, provider=None, wall_clock=10.0):
    """Write a manifest + verdict with explicit thinking/provider fields."""
    trial_dir.mkdir(parents=True, exist_ok=True)
    provider = provider or model_id.split("/")[0]
    manifest = {
        "model": {
            "id": model_id,
            "provider": provider,
            "served_model": model_id,
        },
        "adapter": {"id": f"{adapter}Adapter", "version": adapter},
        "suite": {"id": f"{suite}Suite", "task_id": task_id},
        "trial": 1,
        "sampling": {
            "temperature": "server-default",
            "top_p": "server-default",
            "max_tokens": "server-default",
            "thinking": thinking or "default",
        },
        "timing": {"wall_clock_seconds": wall_clock},
        "token_usage": {},
        "exit_code": 0,
    }
    (trial_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
    (trial_dir / "verdict.json").write_text(json.dumps({
        "passed": passed,
        "test_count": 1,
        "grader_output": "ok" if passed else "fail",
        "exit_code": 0,
        "adapter_failed": False,
        "pending": False,
    }, indent=2))


def _make_handler(results_dir: Path):
    import importlib.util
    server_path = PROJECT_ROOT / "view-scores" / "server.py"
    spec = importlib.util.spec_from_file_location("view_scores_server", server_path)
    server_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(server_mod)
    server_mod.RESULTS_DIR = results_dir
    h = server_mod.ScoreHandler.__new__(server_mod.ScoreHandler)
    return h, server_mod


def _build_run(results_dir, *, run_label, model_id, adapter, thinking, provider,
               passed=True, task_id="python/hello"):
    """Write one trial under results/<run_label>/<encoded_model>/<adapter>/..."""
    base = (
        results_dir / run_label
        / encode_model_path(model_id)
        / adapter / "aider_polyglot"
        / encode_task_path(task_id)
    )
    _write_trial_v2(
        base / "trial-1", passed=passed, model_id=model_id, adapter=adapter,
        thinking=thinking, provider=provider, task_id=task_id,
    )


def test_viewer_distinguishes_same_model_at_different_thinking_levels():
    """RED: two runs differing only in --thinking must produce TWO rows.

    Without thinking in the grouping key, the high-effort run silently
    merges with the default run, corrupting both scores.
    """
    with tempfile.TemporaryDirectory() as tmp:
        results_dir = Path(tmp) / "results"
        results_dir.mkdir()

        # Default-effort run
        _build_run(
            results_dir, run_label="full-20260704",
            model_id="aiand/qwen/qwen3.6-27b", adapter="pi_devstack_superpowers",
            thinking="default", provider="aiand", passed=True,
        )
        # High-effort run — same model/adapter/suite, different thinking
        _build_run(
            results_dir, run_label="full-20260704-high",
            model_id="aiand/qwen/qwen3.6-27b", adapter="pi_devstack_superpowers",
            thinking="high", provider="aiand", passed=False,
        )

        h, _ = _make_handler(results_dir)
        scores = h.get_scores()

    # Must be TWO rows, not one.
    assert len(scores) == 2, (
        f"expected separate rows for default vs high thinking; got {len(scores)} "
        f"row(s): {[(s.get('model'), s.get('thinking')) for s in scores]}"
    )
    thinkings = {s.get("thinking") for s in scores}
    assert thinkings == {"default", "high"}, (
        f"expected thinking levels default+high; got {thinkings}"
    )


def test_viewer_distinguishes_same_model_at_different_providers():
    """RED: same model id served by different providers must produce TWO rows.

    aiand's qwen quant and a local nvfp4 quant are different model/serving
    configurations; conflating them would hide provider-specific capability
    and cost differences.
    """
    with tempfile.TemporaryDirectory() as tmp:
        results_dir = Path(tmp) / "results"
        results_dir.mkdir()

        # aiand-served qwen
        _build_run(
            results_dir, run_label="full-20260704-aiand",
            model_id="aiand/qwen/qwen3.6-27b", adapter="pi_devstack",
            thinking="default", provider="aiand", passed=True,
        )
        # locally-served qwen (nvfp4) — same model id, different provider
        _build_run(
            results_dir, run_label="full-20260704-local",
            model_id="aiand/qwen/qwen3.6-27b", adapter="pi_devstack",
            thinking="default", provider="local", passed=False,
        )

        h, _ = _make_handler(results_dir)
        scores = h.get_scores()

    assert len(scores) == 2, (
        f"expected separate rows for aiand vs local provider; got {len(scores)} "
        f"row(s): {[(s.get('model'), s.get('provider')) for s in scores]}"
    )
    providers = {s.get("provider") for s in scores}
    assert providers == {"aiand", "local"}, (
        f"expected providers aiand+local; got {providers}"
    )


def test_viewer_groups_same_thinking_and_provider_across_run_dirs():
    """RED: trials for the same (model, adapter, suite, thinking, provider)
    spread across multiple run dirs (e.g., resumed runs) must still aggregate
    into ONE row. Resume shouldn't fragment the display.
    """
    with tempfile.TemporaryDirectory() as tmp:
        results_dir = Path(tmp) / "results"
        results_dir.mkdir()

        # Original run — one task
        _build_run(
            results_dir, run_label="full-20260704",
            model_id="aiand/qwen/qwen3.6-27b", adapter="pi_devstack",
            thinking="default", provider="aiand", passed=True,
            task_id="python/hello",
        )
        # Resume under a different run label — same dimensions, different task
        _build_run(
            results_dir, run_label="full-20260704-resume",
            model_id="aiand/qwen/qwen3.6-27b", adapter="pi_devstack",
            thinking="default", provider="aiand", passed=True,
            task_id="python/fizz",
        )

        h, _ = _make_handler(results_dir)
        scores = h.get_scores()

    assert len(scores) == 1, (
        f"trials for same (model,adapter,suite,thinking,provider) across "
        f"run dirs must aggregate into ONE row; got {len(scores)}"
    )
    row = scores[0]
    assert row["total_tasks"] == 2, (
        f"both tasks should be counted; got {row['total_tasks']}"
    )


def test_viewer_thinking_filter_returns_only_matching_rows():
    """--thinking filter should only return rows at that level."""
    with tempfile.TemporaryDirectory() as tmp:
        results_dir = Path(tmp) / "results"
        results_dir.mkdir()
        _build_run(
            results_dir, run_label="r1",
            model_id="aiand/qwen/qwen3.6-27b", adapter="pi_devstack",
            thinking="default", provider="aiand", passed=True,
        )
        _build_run(
            results_dir, run_label="r2",
            model_id="aiand/qwen/qwen3.6-27b", adapter="pi_devstack",
            thinking="high", provider="aiand", passed=False,
        )
        _build_run(
            results_dir, run_label="r3",
            model_id="aiand/qwen/qwen3.6-27b", adapter="pi_devstack",
            thinking="xhigh", provider="aiand", passed=False,
        )
        h, _ = _make_handler(results_dir)
        high_only = h.get_scores(thinking_filter="high")
        all_levels = h.get_scores(thinking_filter="all")
        unfiltered = h.get_scores()
    assert len(high_only) == 1, f"high filter: expected 1 row, got {len(high_only)}"
    assert high_only[0]["thinking"] == "high"
    assert len(all_levels) == 3, f"--thinking all should return all 3, got {len(all_levels)}"
    assert len(unfiltered) == 3, f"no filter should return all 3, got {len(unfiltered)}"


def test_viewer_provider_filter_returns_only_matching_rows():
    """--provider filter should only return rows for that provider."""
    with tempfile.TemporaryDirectory() as tmp:
        results_dir = Path(tmp) / "results"
        results_dir.mkdir()
        _build_run(
            results_dir, run_label="r1",
            model_id="aiand/qwen/qwen3.6-27b", adapter="pi_devstack",
            thinking="default", provider="aiand", passed=True,
        )
        _build_run(
            results_dir, run_label="r2",
            model_id="aiand/qwen/qwen3.6-27b", adapter="pi_devstack",
            thinking="default", provider="local", passed=False,
        )
        h, _ = _make_handler(results_dir)
        aiand_only = h.get_scores(provider_filter="aiand")
        local_only = h.get_scores(provider_filter="local")
        all_prov = h.get_scores(provider_filter="all")
    assert len(aiand_only) == 1, f"aiand filter: expected 1, got {len(aiand_only)}"
    assert aiand_only[0]["provider"] == "aiand"
    assert len(local_only) == 1
    assert local_only[0]["provider"] == "local"
    assert len(all_prov) == 2


def test_viewer_status_dead_higheffort_runner_not_marked_running_when_default_alive():
    """RED: a dead high-effort runner must NOT show as 'running' just because
    a default-effort runner for the same (model, adapter, suite) is alive.
    The fallback _has_live_runner_process must also match --thinking and
    --run-id, not just (model, adapter, suite)."""
    with tempfile.TemporaryDirectory() as tmp:
        results_dir = Path(tmp) / "results"
        results_dir.mkdir()
        # High-effort run: heartbeat says running but PID is dead
        high_dir = (
            results_dir / "full-high"
            / encode_model_path("aiand/qwen/qwen3.6-27b")
            / "pi_devstack" / "aider_polyglot"
        )
        _write_trial_v2(
            high_dir / encode_task_path("python/hello") / "trial-1",
            passed=True, model_id="aiand/qwen/qwen3.6-27b", adapter="pi_devstack",
            thinking="high", provider="aiand",
        )
        # Heartbeat: state=running, but PID is bogus (dead)
        import time as _time
        (high_dir / ".runner-heartbeat.json").write_text(json.dumps({
            "state": "running",
            "pid": 999999,  # bogus — guaranteed not running
            "ppid": 999999,
            "hostname": "test",
            "started_at": "2026-01-01T00:00:00+00:00",
            "updated_at": _time.time(),  # fresh
            "updated_at_epoch": _time.time(),
            "run_id": "full-high",
            "model": "aiand/qwen/qwen3.6-27b",
            "adapter": "pi_devstack",
            "suite": "aider_polyglot",
            "thinking": "high",
            "current_task": "python/hello",
            "current_trial": 1,
            "completed_trials": 1,
            "total_trials": 225,
            "command": ["runner.py", "--model", "aiand/qwen/qwen3.6-27b",
                        "--adapter", "pi_devstack", "--suite", "aider_polyglot",
                        "--thinking", "high", "--run-id", "full-high"],
        }))
        h, _ = _make_handler(results_dir)
        scores = h.get_scores()
    high_scores = [s for s in scores if s.get("thinking") == "high"]
    assert len(high_scores) == 1, f"expected 1 high row, got {len(high_scores)}"
    status = high_scores[0].get("status")
    # PID is dead (999999) so this should NOT be "running" — it should be
    # "partial" (1/225, no incomplete, no live process).
    assert status != "running", (
        f"dead high-effort runner must not show 'running'; got '{status}'. "
        f"Fallback process match is probably ignoring --thinking/--run-id."
    )
