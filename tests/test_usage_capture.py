"""
Tests for model metadata and pi session usage capture.

Cost/intelligence comparisons need more than pass/fail: manifests must carry
model limits/pricing and actual per-trial token/cost usage. pi already writes
JSONL session traces keyed by trial workdir, so the harness should summarize
those traces and preserve the raw response metadata with the trial.
"""

import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from harness.adapters.pi_vanilla import AdapterResult
from harness.adapters.session_utils import trial_session_dir
from harness.runner import run_trial
from harness.subprocess_utils import agent_sandbox_cwd
from harness.telemetry import (
    collect_harbor_pi_session_usage,
    collect_pi_session_usage,
    load_model_metadata,
    pi_session_dir_for_cwd,
    summarize_pi_session,
)
from harness.suites.aider_polyglot import AiderPolyglotSuite


def _write_jsonl(path: Path, events: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(event) for event in events) + "\n")


def _session_events(cwd: Path) -> list[dict]:
    return [
        {
            "type": "session",
            "version": 3,
            "id": "session-123",
            "timestamp": "2026-07-04T14:07:07.921Z",
            "cwd": str(cwd),
        },
        {
            "type": "model_change",
            "provider": "local",
            "modelId": "Ornith-1.0-35B",
        },
        {
            "type": "thinking_level_change",
            "thinkingLevel": "high",
        },
        {
            "type": "message",
            "message": {
                "role": "assistant",
                "api": "openai-completions",
                "provider": "local",
                "model": "Ornith-1.0-35B",
                "responseId": "chatcmpl-one",
                "responseModel": "ornith-35b-fp8-block",
                "usage": {
                    "input": 100,
                    "output": 20,
                    "cacheRead": 30,
                    "cacheWrite": 5,
                    "reasoning": 7,
                    "totalTokens": 162,
                    "cost": {
                        "input": 0.000014,
                        "output": 0.0000208,
                        "cacheRead": 0.0000042,
                        "cacheWrite": 0.0000007,
                        "total": 0.0000397,
                    },
                },
            },
        },
        {
            "type": "message",
            "message": {
                "role": "assistant",
                "api": "openai-completions",
                "provider": "local",
                "model": "Ornith-1.0-35B",
                "responseId": "chatcmpl-two",
                "responseModel": "ornith-35b-fp8-block",
                "usage": {
                    "input": 200,
                    "output": 50,
                    "cacheRead": 60,
                    "cacheWrite": 0,
                    "reasoning": 9,
                    "totalTokens": 319,
                    "cost": {"total": 0.000102},
                },
            },
        },
    ]


def _make_problem(vendor_dir: Path):
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
    (pdir / ".docs" / "instructions.md").write_text("Solve two-fer.")
    (pdir / "two_fer.py").write_text("def two_fer(name=None):\n    pass\n")
    (pdir / "two_fer_test.py").write_text(
        "from two_fer import two_fer\n"
        "def test_two_fer():\n"
        "    assert two_fer() == 'One for you, one for me.'\n"
    )


def test_summarize_pi_session_extracts_usage_cost_and_response_metadata():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        session_file = tmp / "session.jsonl"
        _write_jsonl(session_file, _session_events(tmp / "workdir"))

        summary = summarize_pi_session(session_file)

    assert summary["status"] == "observed"
    assert summary["source"] == "pi-session-jsonl"
    assert summary["response_count"] == 2
    assert summary["prompt_tokens"] == 300
    assert summary["completion_tokens"] == 70
    assert summary["cached_tokens"] == 90
    assert summary["cache_creation_tokens"] == 5
    assert summary["reasoning_tokens"] == 16
    assert summary["total_tokens"] == 481
    assert summary["cost_usd"] == 0.0001417
    assert summary["cost_usd_pi"] == 0.0001417
    assert summary["response_ids"] == ["chatcmpl-one", "chatcmpl-two"]
    assert summary["response_models"] == ["ornith-35b-fp8-block"]
    assert summary["models"] == ["Ornith-1.0-35B"]
    assert summary["thinking"] == "high"


def test_collect_pi_session_usage_copies_raw_trace_by_workdir():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        workdir = tmp / "results" / "trial-1" / "workdir"
        out_dir = tmp / "results" / "trial-1" / "out"
        sessions_root = tmp / "sessions"
        session_dir = pi_session_dir_for_cwd(workdir, sessions_root=sessions_root)
        session_file = session_dir / "2026-07-04T14-07-07Z_session.jsonl"
        _write_jsonl(session_file, _session_events(workdir))

        summary = collect_pi_session_usage(
            workdir,
            out_dir,
            sessions_root=sessions_root,
            start_time=datetime(2026, 7, 4, 14, 7, 0, tzinfo=timezone.utc).timestamp(),
            end_time=datetime(2026, 7, 4, 14, 8, 0, tzinfo=timezone.utc).timestamp(),
        )

        copied_trace = out_dir / "pi_session.jsonl"
        assert copied_trace.exists()
        assert copied_trace.read_text() == session_file.read_text()
        assert summary["status"] == "observed"
        assert summary["trace_files"] == ["out/pi_session.jsonl"]
        assert summary["prompt_tokens"] == 300


def test_trial_session_dir_resolves_relative_result_paths(tmp_path, monkeypatch):
    """Relative --results-dir paths must not write sessions inside workdir."""
    monkeypatch.chdir(tmp_path)

    session_dir = trial_session_dir(Path("results/run/out/session.log"))

    assert session_dir == (tmp_path / "results/run/out/pi-sessions").resolve()
    assert session_dir.is_absolute()


def test_collect_pi_session_usage_reads_explicit_trial_session_dir():
    """--session-dir traces live directly in the supplied directory."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        workdir = tmp / "very" / "long" / "result" / "workdir"
        out_dir = workdir.parent / "out"
        session_dir = out_dir / "pi-sessions"
        session_file = session_dir / "2026-07-04T14-07-07Z_session.jsonl"
        _write_jsonl(session_file, _session_events(workdir))

        summary = collect_pi_session_usage(
            workdir,
            out_dir,
            session_dir=session_dir,
            start_time=datetime(2026, 7, 4, 14, 7, 0, tzinfo=timezone.utc).timestamp(),
            end_time=datetime(2026, 7, 4, 14, 8, 0, tzinfo=timezone.utc).timestamp(),
        )

        assert summary["status"] == "observed"
        assert summary["prompt_tokens"] == 300
        assert (out_dir / "pi_session.jsonl").read_text() == session_file.read_text()


def test_collect_harbor_pi_session_usage_copies_artifact_trace():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        trial_dir = tmp / "trial-1"
        jobs_dir = trial_dir / "jobs"
        out_dir = trial_dir / "out"
        session_file = (
            jobs_dir
            / "2026-07-05__10-00-00"
            / "hello-world__abc123"
            / "artifacts"
            / "pi-sessions"
            / "session.jsonl"
        )
        _write_jsonl(session_file, _session_events(Path("/terminal-bench/workdir")))

        summary = collect_harbor_pi_session_usage(jobs_dir, out_dir)

        copied_trace = out_dir / "pi_session.jsonl"
        assert copied_trace.exists()
        assert copied_trace.read_text() == session_file.read_text()
        assert summary["status"] == "observed"
        assert summary["trace_files"] == ["out/pi_session.jsonl"]
        assert summary["prompt_tokens"] == 300
        assert summary["completion_tokens"] == 70


def test_load_model_metadata_resolves_limits_pricing_without_secrets():
    with tempfile.TemporaryDirectory() as tmp:
        models_json = Path(tmp) / "models.json"
        models_json.write_text(json.dumps({
            "providers": {
                "local": {
                    "baseUrl": "http://localhost:8989/v1",
                    "apiKey": "secret",
                    "models": [
                        {
                            "id": "Ornith-1.0-35B",
                            "name": "Ornith 1.0 35B",
                            "reasoning": True,
                            "input": ["text", "image"],
                            "contextWindow": 262144,
                            "maxTokens": 81920,
                            "cost": {
                                "input": 0.14,
                                "output": 1.04,
                                "cacheRead": 0.14,
                                "cacheWrite": 0.14,
                            },
                        }
                    ],
                }
            }
        }))

        metadata = load_model_metadata(
            "local/ornith-1.0-35b",
            models_json_path=models_json,
        )

    assert metadata["provider_config_model_id"] == "Ornith-1.0-35B"
    assert metadata["name"] == "Ornith 1.0 35B"
    assert metadata["context_window"] == 262144
    assert metadata["max_tokens"] == 81920
    assert metadata["reasoning"] is True
    assert metadata["input_modalities"] == ["text", "image"]
    assert metadata["cost"]["input"] == 0.14
    assert metadata["pricing_unit"] == "usd_per_1m_tokens"
    assert "apiKey" not in json.dumps(metadata)
    assert "secret" not in json.dumps(metadata)


def test_load_model_metadata_prefers_repo_pricing_over_zero_provider_config():
    """Official benchmark pricing should not inherit zero-priced provider stubs."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        models_json = tmp / "models.json"
        models_yaml = tmp / "models.yaml"
        models_json.write_text(json.dumps({
            "providers": {
                "zai": {
                    "baseUrl": "https://api.z.ai/api/paas/v4",
                    "apiKey": "secret",
                    "models": [
                        {
                            "id": "glm-5.2",
                            "name": "GLM 5.2",
                            "contextWindow": 1000000,
                            "maxTokens": 128000,
                            "reasoning": True,
                            "cost": {
                                "input": 0,
                                "output": 0,
                                "cacheRead": 0,
                                "cacheWrite": 0,
                            },
                        }
                    ],
                }
            }
        }))
        models_yaml.write_text(
            "models:\n"
            "  - id: zai/glm-5.2\n"
            "    context_window: 1000000\n"
            "    max_tokens: 128000\n"
            "    reasoning: true\n"
            "    cost:\n"
            "      input: 1.4\n"
            "      cacheRead: 0.26\n"
            "      cacheWrite: 0\n"
            "      output: 4.4\n"
            "    pricing_unit: usd_per_1m_tokens\n"
        )

        metadata = load_model_metadata(
            "zai/glm-5.2",
            models_json_path=models_json,
            models_config_path=models_yaml,
        )

    assert metadata["cost"] == {
        "input": 1.4,
        "cacheRead": 0.26,
        "cacheWrite": 0,
        "output": 4.4,
    }
    assert metadata["pricing_unit"] == "usd_per_1m_tokens"
    assert metadata["context_window"] == 1000000
    assert metadata["max_tokens"] == 128000


def test_repo_models_include_glm_53_pool_metadata(tmp_path):
    """The benchmark matrix should expose the healthy codex-pool GLM 5.3 route."""
    metadata = load_model_metadata(
        "zai/glm-5.3",
        models_json_path=tmp_path / "missing-models.json",
    )

    assert metadata == {
        "name": "GLM 5.3",
        "context_window": 1000000,
        "max_tokens": 128000,
        "reasoning": True,
        "cost": {
            "input": 0,
            "cacheRead": 0,
            "cacheWrite": 0,
            "output": 0,
        },
        "pricing_unit": "usd_per_1m_tokens",
    }


def test_repo_qwen_38_metadata_matches_pool_and_capped_bcb_protocol(tmp_path):
    """Qwen must use pool limits/pricing and preserve BCB's answer budget."""
    metadata = load_model_metadata(
        "local/qwen3.8-27b",
        models_json_path=tmp_path / "missing-models.json",
    )

    assert metadata["name"] == "Qwen 3.8 27B"
    assert metadata["context_window"] == 262144
    assert metadata["max_tokens"] == 131072
    assert metadata["reasoning"] is True
    assert metadata["cost"] == {
        "input": 0.45,
        "cacheRead": 0.45,
        "cacheWrite": 0.45,
        "output": 3.2,
    }
    assert metadata["protocol_overrides"] == {
        "bigcodebench_hard_instruct": {
            "request_overrides": {"reasoning_effort": "none"}
        }
    }


def test_load_model_metadata_has_qwen_36_repo_pricing():
    """Qwen 3.6 27B pricing should come from the benchmark config."""
    with tempfile.TemporaryDirectory() as tmp:
        models_json = Path(tmp) / "models.json"
        models_json.write_text(json.dumps({
            "providers": {
                "aiand": {
                    "models": [
                        {
                            "id": "qwen/qwen3.6-27b",
                            "cost": {
                                "input": 0,
                                "cacheRead": 0,
                                "cacheWrite": 0,
                                "output": 0,
                            },
                        }
                    ],
                }
            }
        }))

        metadata = load_model_metadata(
            "aiand/qwen/qwen3.6-27b",
            models_json_path=models_json,
        )

    assert metadata["cost"] == {
        "input": 0.30,
        "cacheRead": 0.15,
        "cacheWrite": 0,
        "output": 2.40,
    }
    assert metadata["pricing_unit"] == "usd_per_1m_tokens"


def test_load_model_metadata_preserves_long_context_pricing_tiers():
    """GPT-5.5 API-equivalent pricing has short and long context rates."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        models_json = tmp / "models.json"
        models_yaml = tmp / "models.yaml"
        models_json.write_text(json.dumps({
            "providers": {
                "codex": {
                    "baseUrl": "http://localhost:8989/backend-api",
                    "apiKey": "secret",
                    "models": [
                        {
                            "id": "gpt-5.5",
                            "name": "GPT-5.5",
                            "contextWindow": 1050000,
                            "maxTokens": 128000,
                            "reasoning": True,
                            "cost": {
                                "input": 0,
                                "output": 0,
                                "cacheRead": 0,
                                "cacheWrite": 0,
                            },
                        }
                    ],
                }
            }
        }))
        models_yaml.write_text(
            "models:\n"
            "  - id: codex/gpt-5.5\n"
            "    name: GPT-5.5\n"
            "    context_window: 1050000\n"
            "    max_tokens: 128000\n"
            "    reasoning: true\n"
            "    cost:\n"
            "      input: 5.0\n"
            "      cacheRead: 0.5\n"
            "      cacheWrite: 0\n"
            "      output: 30.0\n"
            "      longContextInputThreshold: 272000\n"
            "      longContextInput: 10.0\n"
            "      longContextCacheRead: 1.0\n"
            "      longContextCacheWrite: 0\n"
            "      longContextOutput: 45.0\n"
            "    pricing_unit: usd_per_1m_tokens\n"
        )

        metadata = load_model_metadata(
            "codex/gpt-5.5",
            models_json_path=models_json,
            models_config_path=models_yaml,
        )

    assert metadata["cost"] == {
        "input": 5.0,
        "cacheRead": 0.5,
        "cacheWrite": 0,
        "output": 30.0,
        "longContextInputThreshold": 272000,
        "longContextInput": 10.0,
        "longContextCacheRead": 1.0,
        "longContextCacheWrite": 0,
        "longContextOutput": 45.0,
    }
    assert metadata["pricing_unit"] == "usd_per_1m_tokens"


def test_load_model_metadata_selects_named_cost_profile():
    """Named cost profiles allow old/new pricing without rewriting manifests."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        models_json = tmp / "models.json"
        models_yaml = tmp / "models.yaml"
        models_json.write_text(json.dumps({"providers": {}}))
        models_yaml.write_text(
            "models:\n"
            "  - id: repo/profiled-model\n"
            "    cost:\n"
            "      input: 1.0\n"
            "      output: 2.0\n"
            "    cost_profiles:\n"
            "      new:\n"
            "        input: 10.0\n"
            "        output: 20.0\n"
            "        cacheRead: 1.0\n"
            "    pricing_unit: usd_per_1m_tokens\n"
        )

        metadata = load_model_metadata(
            "repo/profiled-model",
            models_json_path=models_json,
            models_config_path=models_yaml,
            pricing_profile="new",
        )

    assert metadata["cost"] == {
        "input": 10.0,
        "output": 20.0,
        "cacheRead": 1.0,
    }
    assert metadata["pricing_profile"] == "new"


def test_run_trial_records_pi_session_usage_and_trace(monkeypatch):
    suite = AiderPolyglotSuite()

    class SessionWritingAdapter:
        name = "pi_vanilla"
        version = "test"

        def __init__(self, sessions_root: Path):
            self.sessions_root = sessions_root

        def run(self, task_data, workdir, log_file, stderr_file):
            (workdir / "two_fer.py").write_text(
                "def two_fer(name=None):\n"
                "    return 'One for you, one for me.' if name is None else f'One for {name}, one for me.'\n"
            )
            session_dir = pi_session_dir_for_cwd(
                workdir,
                sessions_root=self.sessions_root,
            )
            _write_jsonl(
                session_dir / "2026-07-04T14-07-07Z_session.jsonl",
                _session_events(workdir),
            )
            return AdapterResult(returncode=0)

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        vendor_dir = tmp / "vendor"
        vendor_dir.mkdir()
        _make_problem(vendor_dir)
        results_dir = tmp / "results"
        sessions_root = tmp / "sessions"
        monkeypatch.setenv("CODING_EVAL_PI_SESSIONS_DIR", str(sessions_root))

        manifest, verdict = run_trial(
            suite,
            SessionWritingAdapter(sessions_root),
            "local/ornith-1.0-35b",
            "python/two-fer",
            1,
            results_dir,
            vendor_dir,
            thinking="high",
        )

        assert verdict["passed"] is True
        usage = manifest["token_usage"]
        assert usage["status"] == "observed"
        assert usage["prompt_tokens"] == 300
        assert usage["completion_tokens"] == 70
        assert usage["cost_usd"] == 0.0001417
        assert usage["cost_usd_pi"] == 0.0001417
        assert usage["trace_files"] == ["out/pi_session.jsonl"]
        assert manifest["sampling"]["thinking_token_budget"] == 8192
        trace_path = (
            results_dir
            / "local%2Fornith-1.0-35b"
            / "pi_vanilla"
            / "aider_polyglot"
            / "python%2Ftwo-fer"
            / "trial-1"
            / "out"
            / "pi_session.jsonl"
        )
        assert trace_path.exists()


def test_run_trial_collects_session_from_sandbox_cwd(monkeypatch):
    """Sandboxed pi traces use a virtual cwd but still belong to the host trial."""
    suite = AiderPolyglotSuite()

    class SandboxedSessionAdapter:
        name = "pi_vanilla"
        version = "test"
        uses_workspace_sandbox = True

        def __init__(self, sessions_root: Path):
            self.sessions_root = sessions_root

        def run(self, task_data, workdir, log_file, stderr_file):
            (workdir / "two_fer.py").write_text(
                "def two_fer(name=None):\n"
                "    return 'One for you, one for me.' if name is None else f'One for {name}, one for me.'\n"
            )
            virtual_cwd = agent_sandbox_cwd(workdir, "two-fer")
            session_dir = pi_session_dir_for_cwd(
                virtual_cwd,
                sessions_root=self.sessions_root,
            )
            _write_jsonl(
                session_dir / "2026-07-04T14-07-07Z_session.jsonl",
                _session_events(virtual_cwd),
            )
            return AdapterResult(returncode=0)

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        vendor_dir = tmp / "vendor"
        vendor_dir.mkdir()
        _make_problem(vendor_dir)
        results_dir = tmp / "results"
        sessions_root = tmp / "sessions"
        monkeypatch.setenv("CODING_EVAL_PI_SESSIONS_DIR", str(sessions_root))

        manifest, verdict = run_trial(
            suite,
            SandboxedSessionAdapter(sessions_root),
            "local/ornith-1.0-35b",
            "python/two-fer",
            1,
            results_dir,
            vendor_dir,
            thinking="high",
        )

    assert verdict["passed"] is True
    assert manifest["token_usage"]["status"] == "observed"
    assert manifest["token_usage"]["prompt_tokens"] == 300


def test_run_trial_collects_trial_local_session_from_sandbox_cwd(monkeypatch):
    """Explicit --session-dir traces retain the sandbox's virtual cwd."""
    suite = AiderPolyglotSuite()

    class TrialLocalSandboxedSessionAdapter:
        name = "pi_devstack"
        version = "test"
        uses_workspace_sandbox = True

        def run(self, task_data, workdir, log_file, stderr_file):
            (workdir / "two_fer.py").write_text(
                "def two_fer(name=None):\n"
                "    return 'One for you, one for me.' if name is None else f'One for {name}, one for me.'\n"
            )
            virtual_cwd = agent_sandbox_cwd(workdir, "two-fer")
            session_dir = log_file.parent / "pi-sessions"
            _write_jsonl(
                session_dir / "2026-07-04T14-07-07Z_session.jsonl",
                _session_events(virtual_cwd),
            )
            return AdapterResult(returncode=0)

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        vendor_dir = tmp / "vendor"
        vendor_dir.mkdir()
        _make_problem(vendor_dir)
        results_dir = tmp / "results"

        manifest, verdict = run_trial(
            suite,
            TrialLocalSandboxedSessionAdapter(),
            "local/ornith-1.0-35b",
            "python/two-fer",
            1,
            results_dir,
            vendor_dir,
            thinking="high",
        )

    assert verdict["passed"] is True
    assert manifest["token_usage"]["status"] == "observed"
    assert manifest["token_usage"]["prompt_tokens"] == 300
    assert manifest["token_usage"]["trace_files"] == ["out/pi_session.jsonl"]
