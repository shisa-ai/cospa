"""
runner.py — Single load-bearing component of the coding-eval harness.

Takes (suite, model, adapter, trial_k) and runs one task:
  1. Spawns the adapter as a subprocess
  2. Captures stdout/stderr/exit
  3. Runs the suite's verifier
  4. Writes results/runs/<model-run>/<model>/<adapter>/<suite>/<task_id>/trial-<k>/{manifest.json, out/, verdict.json}

Usage:
  mamba run -n cospa python harness/runner.py \
    --suite aider_polyglot \
    --adapter pi_vanilla \
    --model nvidia/nemotron-3-ultra-550b-a55b \
    --problems 5 \
    --k 1
"""

import argparse
import json
import os
import socket
import shutil
import subprocess
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

# Add project root to path so we can import harness modules
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from harness.adapters import load_adapter
from harness.adapters.session_utils import behavior_trace_file
from harness.behavior import (
    summarize_behavior_events,
    summarize_pi_session_behavior,
)
from harness.suites import load_suite
from harness.path_utils import encode_path_component
from harness.subprocess_utils import (
    agent_sandbox_cwd,
    register_termination_callback,
    resolve_model_base_url,
    unregister_termination_callback,
)
from harness.telemetry import (
    collect_harbor_pi_session_usage,
    collect_pi_session_usage,
    load_model_metadata,
    thinking_sampling_metadata,
)


def parse_args():
    parser = argparse.ArgumentParser(description="Run a single eval trial")
    parser.add_argument(
        "--suite",
        required=True,
        help="Suite name registered in harness.suites.SUITES",
    )
    parser.add_argument(
        "--adapter",
        required=True,
        help=(
            "Adapter name (pi_vanilla, pi_devstack, "
            "pi_devstack_superpowers, little_coder, "
            "pi_superpowers, little_coder_superpowers, "
            "bigcodebench_openai)"
        ),
    )
    parser.add_argument("--model", required=True, help="Model ID (e.g. nvidia/nemotron-3-ultra-550b-a55b)")
    parser.add_argument("--problems", type=int, default=None, help="Number of problems to run (None = all)")
    parser.add_argument("--k", type=int, default=1, help="Number of trials per problem")
    parser.add_argument(
        "--concurrency",
        type=int,
        default=1,
        help="Maximum number of task trials to run concurrently (default: 1)",
    )
    parser.add_argument(
        "--results-dir",
        default=None,
        help=(
            "Exact results output root. If omitted, a unique "
            "results/runs/<encoded-model>-<run-id> directory is used."
        ),
    )
    parser.add_argument(
        "--run-id",
        default=None,
        help=(
            "Run id for the default results wrapper. Ignored when "
            "--results-dir is supplied. Defaults to a timestamp plus random suffix."
        ),
    )
    parser.add_argument("--vendor-dir", default=PROJECT_ROOT / "vendor", help="Vendored datasets directory")
    parser.add_argument("--config", default=PROJECT_ROOT / "configs" / "models.yaml", help="Models config file")
    parser.add_argument(
        "--skip-reachability",
        action="store_true",
        default=False,
        help="Skip the pre-run model reachability check (use for offline/smoke runs)",
    )
    parser.add_argument(
        "--thinking",
        default=None,
        choices=[
            "off",
            "minimal",
            "low",
            "medium",
            "high",
            "xhigh",
            "max",
        ],
        help=(
            "Thinking/effort level passed through to the adapter "
            "(pi --thinking). When unset, the adapter invokes pi with no "
            "--thinking flag and the model/provider default applies."
        ),
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=2,
        help=(
            "Retry infrastructure failures this many times per trial. "
            "Wrong answers are not retried."
        ),
    )
    return parser.parse_args()


def validate_args(args) -> None:
    """Validate parsed CLI arguments before loading suites or adapters."""
    if args.k < 1:
        print("✗ --k must be a positive integer", file=sys.stderr)
        sys.exit(2)
    if args.problems is not None and args.problems < 1:
        print("✗ --problems must be a positive integer", file=sys.stderr)
        sys.exit(2)
    if getattr(args, "retries", 2) < 0:
        print("✗ --retries must be zero or greater", file=sys.stderr)
        sys.exit(2)
    if getattr(args, "concurrency", 1) < 1:
        print("✗ --concurrency must be a positive integer", file=sys.stderr)
        sys.exit(2)


def validate_required_adapter(task_data: dict, adapter) -> None:
    """Fail closed when a suite requires a protocol-specific adapter."""
    required = task_data.get("required_adapter")
    actual = getattr(adapter, "name", None)
    if required and actual != required:
        raise ValueError(
            f"Suite protocol requires adapter {required!r}; received {actual!r}"
        )


def generate_run_id() -> str:
    """Generate a path-safe run id for default CLI output isolation."""
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    return f"{timestamp}-{os.getpid()}-{uuid.uuid4().hex[:8]}"


def resolve_results_dir(
    model_id: str,
    requested_results_dir: Path | str | None,
    run_id: str | None = None,
) -> tuple[Path, str | None]:
    """Resolve the effective results root for a CLI invocation.

    Direct run_trial() callers and explicit --results-dir users keep exact
    control of the output root. The CLI default is isolated by model + run id
    so two identical commands do not race on the same trial paths.
    """
    if requested_results_dir is not None:
        return Path(requested_results_dir), None

    resolved_run_id = run_id or generate_run_id()
    run_component = (
        f"{encode_path_component(model_id)}-"
        f"{encode_path_component(resolved_run_id)}"
    )
    return PROJECT_ROOT / "results" / "runs" / run_component, resolved_run_id


def run_with_tty_updates(fn, label: str, interval: float = 5.0):
    """Run fn while printing lightweight progress in interactive terminals."""
    if not sys.stdout.isatty():
        return fn()

    result_box = []
    error_box = []

    def target():
        try:
            result_box.append(fn())
        except BaseException as exc:
            error_box.append(exc)

    worker = threading.Thread(target=target, daemon=True)
    worker.start()

    start = time.monotonic()
    last_line_len = 0
    while worker.is_alive():
        elapsed = int(time.monotonic() - start)
        line = f"{label} running {elapsed}s..."
        print("\r" + line, end="", flush=True)
        last_line_len = max(last_line_len, len(line))
        worker.join(interval)

    if last_line_len:
        print("\r" + (" " * last_line_len) + "\r", end="", flush=True)

    if error_box:
        raise error_box[0]
    return result_box[0]


@lru_cache(maxsize=1)
def get_env_hash():
    """Return a short hash identifying the current Python environment.

    This combines the interpreter path with the sorted list of installed
    packages and returns a SHA-256 digest, so two environments that look
    identical but differ in installed packages produce different hashes.
    Previously this returned the raw `sys.executable` string, which is a
    path — not a hash — and breaks manifest comparability (review #10).
    """
    import hashlib
    try:
        parts = [sys.executable, sys.version]
        # Include installed distributions so the hash reflects the env contents
        try:
            import importlib.metadata as md
            dists = sorted(
                f"{d.metadata['Name']}=={d.version}"
                for d in md.distributions()
            )
            parts.extend(dists)
        except Exception:
            pass
        payload = "\n".join(parts).encode()
        return hashlib.sha256(payload).hexdigest()[:16]
    except Exception:
        return "unknown"


@lru_cache(maxsize=1)
def get_pi_version():
    """Get pi version if available."""
    try:
        result = subprocess.run(
            ["pi", "--version"],
            capture_output=True, text=True, timeout=5
        )
        return result.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


@lru_cache(maxsize=1)
def get_little_coder_version():
    """Get little-coder version if available."""
    try:
        result = subprocess.run(
            ["little-coder", "--version"],
            capture_output=True, text=True, timeout=5
        )
        return result.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


@lru_cache(maxsize=1)
def get_harbor_version():
    """Get Harbor version if available."""
    try:
        result = subprocess.run(
            ["harbor", "--version"],
            capture_output=True, text=True, timeout=5
        )
        return result.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def get_terminal_bench_pin(vendor_dir: Path) -> str:
    """Return the checked-in Terminal-Bench Core 0.1.1 commit pin.

    The upstream dataset commit predates registry.json, so the immutable
    cospa manifest—not a mutable vendored head registry—is authoritative.
    """
    manifest_file = PROJECT_ROOT / "configs" / "terminal_bench_core_0.1.1.json"
    try:
        with open(manifest_file) as f:
            manifest = json.load(f)
        pin = manifest.get("commit_hash")
        return str(pin) if pin else "unknown"
    except Exception:
        return "unknown"


def _manifest_sampling(
    task_data: dict,
    *,
    model_metadata: dict | None = None,
) -> dict:
    """Return the explicit per-model sampling profile recorded in the manifest.

    Pi receives sampling values through the selected model's ``samplingParams``
    (validated by pi-backed adapters before each call).  The manifest mirrors
    that profile rather than claiming an unverified server default.
    """
    profile = task_data.get("sampling_params")
    if not isinstance(profile, dict) and isinstance(model_metadata, dict):
        profile = model_metadata.get("sampling_params")
    if not isinstance(profile, dict):
        profile = {}

    def value(key: str) -> int | float | str:
        explicit = task_data.get(key)
        if explicit is not None:
            return explicit
        configured = profile.get(key)
        return configured if configured is not None else "server-default"

    sampling = {
        "temperature": value("temperature"),
        "top_p": value("top_p"),
        "top_k": value("top_k"),
        "max_tokens": value("max_tokens"),
    }
    source = task_data.get("sampling_source") or (
        model_metadata.get("sampling_source") if isinstance(model_metadata, dict) else None
    )
    if source:
        sampling["source"] = source
    rationale = task_data.get("sampling_rationale") or (
        model_metadata.get("sampling_rationale") if isinstance(model_metadata, dict) else None
    )
    if rationale:
        sampling["rationale"] = rationale
    sampling.update(
        thinking_sampling_metadata(
            task_data.get("thinking"),
            model_id=task_data.get("model_id"),
            model_metadata=model_metadata,
        )
    )
    request_overrides = task_data.get("request_overrides")
    if isinstance(request_overrides, dict):
        reasoning_effort = request_overrides.get("reasoning_effort")
        if isinstance(reasoning_effort, str):
            sampling["reasoning_effort"] = reasoning_effort
            sampling["reasoning_effort_source"] = "model_protocol_override"
    return sampling


def _manifest_tool_call_parser(task_data: dict) -> str:
    """Return the best available tool-call parser/config identifier."""
    return (
        task_data.get("tool_call_parser")
        or os.environ.get("CODING_EVAL_TOOL_CALL_PARSER")
        or "server-config-unobserved"
    )


def should_run_reachability_check(skip: bool = False) -> bool:
    """Decide whether to run the model reachability check at startup.

    Enabled by default. The CLI exposes --skip-reachability for offline or
    smoke runs where the user explicitly accepts the risk.
    """
    return not skip


def check_model_reachable(model_id: str, timeout: float = 10.0) -> bool:
    """Best-effort reachability probe for a model id.

    Reads ~/.pi/agent/models.json to find the provider's baseUrl for the
    model's provider, then issues a 1-token completion. Returns True if the
    endpoint responds HTTP 200, False otherwise (including unknown provider
    or missing config). Never raises.

    This is the same logic as scripts/check-models.sh but in-process so the
    runner can call it before starting a matrix (PLAN.md #137-138).
    """
    import urllib.request
    import urllib.error

    provider = model_id.split("/")[0] if "/" in model_id else None
    model_name = model_id.split("/", 1)[1] if "/" in model_id else model_id
    if provider is None:
        return False

    models_json = Path.home() / ".pi" / "agent" / "models.json"
    if not models_json.exists():
        return False

    try:
        with open(models_json) as f:
            data = json.load(f)
    except Exception:
        return False

    providers = data.get("providers", data) if isinstance(data, dict) else {}
    prov_cfg = providers.get(provider) if isinstance(providers, dict) else None
    if not isinstance(prov_cfg, dict):
        return False
    base_url = prov_cfg.get("baseUrl") or prov_cfg.get("base_url")
    if not base_url:
        return False
    api_key = prov_cfg.get("apiKey") or prov_cfg.get("api_key")
    api_key_env = (
        prov_cfg.get("apiKeyEnv")
        or prov_cfg.get("api_key_env")
        or prov_cfg.get("apiKeyEnvVar")
        or prov_cfg.get("api_key_env_var")
    )
    if api_key_env and os.environ.get(api_key_env):
        api_key = os.environ[api_key_env]

    api = prov_cfg.get("api")
    if api and api != "openai-completions":
        env = os.environ.copy()
        env["PI_OFFLINE"] = "1"
        try:
            result = subprocess.run(
                [
                    "pi",
                    "--no-extensions",
                    "--no-skills",
                    "--no-session",
                    "--print",
                    "--model",
                    model_id,
                    "Reply with exactly: OK",
                ],
                capture_output=True,
                text=True,
                timeout=timeout,
                env=env,
            )
        except (OSError, subprocess.SubprocessError):
            return False
        return result.returncode == 0

    provider_models = []
    for item in prov_cfg.get("models", []):
        if isinstance(item, dict):
            value = item.get("id") or item.get("name")
        else:
            value = item
        if isinstance(value, str):
            provider_models.append(value)
    resolved_model = model_name
    if model_id in provider_models:
        resolved_model = model_id
    elif model_name in provider_models:
        resolved_model = model_name

    payload = json.dumps({
        "model": resolved_model,
        "messages": [{"role": "user", "content": "hi"}],
        "max_tokens": 1,
    }).encode()
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = urllib.request.Request(
        f"{base_url.rstrip('/')}/chat/completions",
        data=payload,
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status == 200
    except urllib.error.HTTPError as e:
        return e.code == 200
    except Exception:
        return False


def _latest_harbor_agent_exception(jobs_dir: Path | str) -> dict | None:
    """Return the newest Harbor trial exception, ignoring job summaries."""
    jobs_dir = Path(jobs_dir)
    candidates: list[tuple[float, dict]] = []
    if not jobs_dir.exists():
        return None
    for result_file in jobs_dir.rglob("result.json"):
        try:
            payload = json.loads(result_file.read_text())
            if not isinstance(payload, dict) or "exception_info" not in payload:
                continue
            candidates.append((result_file.stat().st_mtime, payload))
        except (OSError, json.JSONDecodeError):
            continue
    if not candidates:
        return None
    payload = max(candidates, key=lambda item: item[0])[1]
    exception = payload.get("exception_info")
    return exception if isinstance(exception, dict) and exception else None


def run_trial(
    suite,
    adapter,
    model_id,
    task_id,
    trial_k,
    results_dir,
    vendor_dir,
    thinking=None,
    *,
    force=False,
    retry_attempt=1,
    max_attempts=1,
):
    """Run a single trial of a single task."""
    from harness.path_utils import encode_model_path, encode_task_path

    # Normalize path inputs (argparse and callers may hand us strings)
    results_dir = Path(results_dir)
    vendor_dir = Path(vendor_dir)

    # Create output directory with URL-encoded model and task IDs
    # This handles IDs containing slashes (e.g., "nvidia/nemotron-...")
    encoded_model = encode_model_path(model_id)
    encoded_task = encode_task_path(task_id)
    trial_dir = Path(results_dir) / encoded_model / adapter.name / suite.name / encoded_task / f"trial-{trial_k}"

    # Resume: skip only fully durable completed trials. A killed run can leave
    # partial artifacts (for example verdict.json without manifest.json); those
    # need to be re-run so later aggregation has both files.
    verdict_path = trial_dir / "verdict.json"
    manifest_path = trial_dir / "manifest.json"
    if not force and verdict_path.exists() and manifest_path.exists():
        try:
            with open(verdict_path) as vf:
                prior_verdict = json.load(vf)
            with open(manifest_path) as mf:
                prior_manifest = json.load(mf)
            print(f"[resume] skip {model_id}/{adapter.name}/{suite.name}/{task_id}/trial-{trial_k} (artifacts complete: passed={prior_verdict.get('passed')})")
            return prior_manifest, prior_verdict
        except (json.JSONDecodeError, OSError):
            # Corrupt verdict/manifest: fall through and re-run.
            print(f"[resume] existing artifacts unreadable for {task_id}; re-running")
    elif not force and (verdict_path.exists() or manifest_path.exists()):
        print(f"[resume] incomplete artifacts for {task_id}; re-running")

    trial_dir.mkdir(parents=True, exist_ok=True)

    # Create workdir for this trial
    workdir = trial_dir / "workdir"
    workdir.mkdir(exist_ok=True)

    # Materialize the task into the workdir
    task_data = suite.materialize_task(task_id, workdir, vendor_dir)
    validate_required_adapter(task_data, adapter)

    model_metadata = load_model_metadata(model_id)

    # Override model_id with the actual model from args.
    task_data["model_id"] = model_id
    task_data["model_base_url"] = resolve_model_base_url(model_id)
    # Pi-backed adapters validate this profile against pi's model-level
    # samplingParams before starting the agent.
    if isinstance(model_metadata.get("sampling_params"), dict):
        task_data["sampling_params"] = model_metadata["sampling_params"]
    # Pi sends a model entry's maxTokens as max_tokens; carry it into the
    # manifest so it records the actual request cap rather than a default.
    if (
        model_metadata.get("max_tokens") is not None
        and task_data.get("max_tokens") is None
    ):
        task_data["max_tokens"] = model_metadata["max_tokens"]
    for key in ("sampling_source", "sampling_rationale"):
        if key in model_metadata and key not in task_data:
            task_data[key] = model_metadata[key]
    protocol_overrides = model_metadata.get("protocol_overrides")
    if isinstance(protocol_overrides, dict):
        override_name = getattr(suite, "protocol_override_name", suite.name)
        suite_overrides = protocol_overrides.get(override_name)
        if isinstance(suite_overrides, dict):
            request_overrides = suite_overrides.get("request_overrides")
            if isinstance(request_overrides, dict):
                task_data["request_overrides"] = dict(request_overrides)
    # Propagate agent thinking/effort only for protocols that support it. The
    # non-agentic BigCodeBench arm records agent thinking as not applicable;
    # any model-specific request override is recorded separately in sampling.
    task_data["thinking"] = (
        "not_applicable"
        if task_data.get("thinking_policy") == "not_applicable"
        else thinking
    )
    prepare_dependencies = getattr(suite, "prepare_agent_dependencies", None)

    # Parse provider from model_id (e.g., "nvidia/nemotron-..." -> provider="nvidia")
    provider = model_id.split("/")[0] if "/" in model_id else "unknown"
    model_manifest = {
        "id": model_id,
        "provider": provider,
        "served_model": (
            task_data.get("served_model")
            or os.environ.get("CODING_EVAL_SERVED_MODEL")
            or model_id
        ),
    }
    model_manifest.update(model_metadata)

    # Build manifest with all required fields. Suites may add immutable
    # dataset/evaluator pins and predeclared task strata.
    suite_manifest = {
        "id": suite.__class__.__name__,
        "version": getattr(suite, "version", "unknown"),
        "task_id": task_id,
    }
    manifest_metadata = getattr(suite, "manifest_metadata", None)
    if callable(manifest_metadata):
        extra_suite_metadata = manifest_metadata(task_data)
        if isinstance(extra_suite_metadata, dict):
            suite_manifest.update(extra_suite_metadata)

    manifest = {
        "model": model_manifest,
        "adapter": {
            "id": adapter.__class__.__name__,
            "version": getattr(adapter, "version", "unknown"),
        },
        "suite": suite_manifest,
        "trial": trial_k,
        "sampling": _manifest_sampling(task_data, model_metadata=model_metadata),
        # Identifier for the tool-call parser/config the adapter uses.
        # pi/little-coder use their built-in tool-call handling; adapters may
        # override via task_data["tool_call_parser"].
        "tool_call_parser": _manifest_tool_call_parser(task_data),
        "env": {
            "hash": get_env_hash(),
            "pi_version": get_pi_version(),
            "little_coder_version": get_little_coder_version(),
            "harbor_version": get_harbor_version(),
            "terminal_bench_pin": get_terminal_bench_pin(vendor_dir),
        },
        "timing": {},
        "token_usage": {},
        "exit_code": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "run_end_time": None,  # Set after adapter completes
    }
    if retry_attempt > 1:
        manifest["retry"] = {
            "attempt": retry_attempt,
            "max_attempts": max_attempts,
        }

    # Run the adapter
    out_dir = trial_dir / "out"
    out_dir.mkdir(exist_ok=True)

    log_file = out_dir / "session.log"
    stderr_file = out_dir / "stderr.log"

    # Harbor-backed suites own execution and scoring. The generic adapter path
    # does not apply because Harbor runs the selected custom agent inside the
    # task environment and invokes the benchmark-native verifier.
    start_time = time.time()
    adapter_failed = False
    harbor_result = None
    is_harbor_suite = callable(getattr(suite, "run_harbor_job", None))
    if callable(prepare_dependencies):
        try:
            prepare_dependencies(task_data, workdir)
        except Exception as e:
            manifest["exit_code"] = -1
            manifest["timing"]["wall_clock_seconds"] = time.time() - start_time
            manifest["run_end_time"] = datetime.now(timezone.utc).isoformat()
            manifest["error"] = f"Dependency preparation failed: {e}"
            adapter_failed = True
            with open(stderr_file, "a") as f:
                f.write(f"{manifest['error']}\n")

    if adapter_failed:
        pass
    elif is_harbor_suite:
        jobs_dir = trial_dir / "jobs"
        jobs_dir.mkdir(exist_ok=True)
        try:
            harbor_result = suite.run_harbor_job(
                task_id=task_id,
                model_id=model_id,
                adapter_name=adapter.name,
                workdir=workdir,
                jobs_dir=jobs_dir,
                n_attempts=1,
                vendor_dir=vendor_dir,
                thinking=thinking,
            )
            manifest["exit_code"] = harbor_result.get("returncode", -1)
            manifest["timing"]["wall_clock_seconds"] = time.time() - start_time
            manifest["run_end_time"] = datetime.now(timezone.utc).isoformat()
            if harbor_result.get("stderr"):
                with open(stderr_file, "w") as sf:
                    sf.write(harbor_result["stderr"])
            if harbor_result.get("stdout"):
                with open(log_file, "w") as lf:
                    lf.write(harbor_result["stdout"])
            if harbor_result.get("returncode", -1) != 0:
                adapter_failed = True
                manifest["error"] = harbor_result.get("stderr") or (
                    f"Harbor job exited with code {harbor_result.get('returncode')}"
                )
            else:
                agent_exception = _latest_harbor_agent_exception(jobs_dir)
                if agent_exception is not None:
                    exception_type = str(
                        agent_exception.get("exception_type") or "HarborAgentError"
                    )
                    exception_message = str(
                        agent_exception.get("exception_message") or "agent phase failed"
                    )
                    manifest["exit_code"] = -1
                    manifest["error"] = f"{exception_type}: {exception_message}"
                    manifest["harbor_agent_exception"] = {
                        "exception_type": exception_type,
                        "exception_message": exception_message,
                    }
                    adapter_failed = True
        except Exception as e:
            manifest["exit_code"] = -1
            manifest["timing"]["wall_clock_seconds"] = time.time() - start_time
            manifest["run_end_time"] = datetime.now(timezone.utc).isoformat()
            manifest["error"] = f"Harbor job raised: {e}"
            adapter_failed = True
    else:
        try:
            # Run adapter as subprocess
            result = adapter.run(task_data, workdir, log_file, stderr_file)
            manifest["exit_code"] = result.returncode
            manifest["timing"]["wall_clock_seconds"] = time.time() - start_time
            manifest["run_end_time"] = datetime.now(timezone.utc).isoformat()

            # Capture error if adapter reported one
            if hasattr(result, "error") and result.error:
                manifest["error"] = result.error
                adapter_failed = True

            # Any nonzero return code is an adapter failure unless the suite
            # explicitly opts into verification after failure. This prevents
            # false passes from starter code that already satisfies a weak or
            # disconnected verifier (review finding #6 / audit item C).
            if result.returncode != 0:
                adapter_failed = True
                if "error" not in manifest:
                    manifest["error"] = f"Adapter exited with code {result.returncode}"

            # Capture token usage if available
            if hasattr(result, "usage") and result.usage:
                manifest["token_usage"] = {
                    "prompt_tokens": getattr(result.usage, "prompt_tokens", None),
                    "completion_tokens": getattr(result.usage, "completion_tokens", None),
                    "total_tokens": getattr(result.usage, "total_tokens", None),
                }
            if getattr(result, "inference_seconds", None) is not None:
                manifest["timing"]["provider_inference_seconds"] = (
                    result.inference_seconds
                )
            if isinstance(getattr(result, "behavior", None), dict):
                manifest["behavior"] = result.behavior
        except Exception as e:
            manifest["exit_code"] = -1
            manifest["timing"]["wall_clock_seconds"] = time.time() - start_time
            manifest["run_end_time"] = datetime.now(timezone.utc).isoformat()
            manifest["error"] = str(e)
            adapter_failed = True

            # Write error to log
            with open(log_file, "a") as f:
                f.write(f"\n[ERROR] {e}\n")

    manifest["timing"]["agent_wall_seconds"] = manifest["timing"].get(
        "wall_clock_seconds", time.time() - start_time
    )

    if not getattr(adapter, "uses_pi_session", True):
        session_usage = {"status": "not_applicable_nonagentic"}
    elif is_harbor_suite:
        session_usage = collect_harbor_pi_session_usage(trial_dir / "jobs", out_dir)
        if session_usage.get("status") != "observed":
            session_usage = collect_pi_session_usage(
                workdir,
                out_dir,
                start_time=start_time,
                end_time=time.time(),
            )
    else:
        session_usage = collect_pi_session_usage(
            workdir,
            out_dir,
            session_dir=out_dir / "pi-sessions",
            start_time=start_time,
            end_time=time.time(),
        )
        # Preserve compatibility with custom/test adapters and artifacts from
        # before trial-local --session-dir was introduced.
        if session_usage.get("status") != "observed":
            fallback_workdir = (
                agent_sandbox_cwd(workdir, task_data.get("problem"))
                if getattr(adapter, "uses_workspace_sandbox", False)
                else workdir
            )
            session_usage = collect_pi_session_usage(
                fallback_workdir,
                out_dir,
                session_dir=out_dir / "pi-sessions",
                start_time=start_time,
                end_time=time.time(),
            )
            if session_usage.get("status") != "observed":
                session_usage = collect_pi_session_usage(
                    fallback_workdir,
                    out_dir,
                    start_time=start_time,
                    end_time=time.time(),
                )
    if session_usage.get("status") == "observed":
        manifest["token_usage"] = session_usage
        response_models = session_usage.get("response_models")
        if isinstance(response_models, list) and response_models:
            manifest["model"]["served_model"] = response_models[-1]
        # Harbor agents export durable pi sessions but run in benchmark-owned
        # containers where the host adapter's compact trace extension is not
        # loaded. Recover counts and message-bound wall timings from the copied
        # session so tool behavior is still comparable across adapter arms.
        requested_thinking = task_data.get("thinking")
        observed_thinking = session_usage.get("thinking")
        if (
            requested_thinking
            and requested_thinking != "default"
            and observed_thinking
            and observed_thinking != requested_thinking
        ):
            manifest["thinking_mismatch"] = {
                "requested": requested_thinking,
                "observed": observed_thinking,
            }
            manifest["exit_code"] = -1
            manifest["error"] = (
                "Thinking level mismatch: requested "
                f"{requested_thinking}, observed {observed_thinking}"
            )
            adapter_failed = True
        if is_harbor_suite:
            trace_files = session_usage.get("trace_files")
            if isinstance(trace_files, list):
                for relative_trace in reversed(trace_files):
                    if not isinstance(relative_trace, str):
                        continue
                    session_behavior = summarize_pi_session_behavior(
                        trial_dir / relative_trace
                    )
                    if session_behavior.get("status") != "unavailable":
                        session_behavior["trace_file"] = relative_trace
                        manifest["behavior"] = session_behavior
                        break

    behavior_file = behavior_trace_file(log_file)
    if behavior_file.exists():
        behavior = summarize_behavior_events(
            behavior_file,
            trial_wall_seconds=manifest.get("timing", {}).get("wall_clock_seconds"),
        )
        try:
            behavior["trace_file"] = str(behavior_file.relative_to(trial_dir))
        except ValueError:
            behavior["trace_file"] = str(behavior_file)
        manifest["behavior"] = behavior

    # Run the suite's verifier only if the adapter succeeded. A suite may
    # explicitly opt into post-failure verification by setting
    # `verify_on_adapter_failure = True` (e.g. for suites whose verifier is
    # the source of truth, like a Harbor-scored Terminal-Bench trial).
    verify_on_failure = getattr(
        suite, "verify_on_adapter_failure", False
    )
    if manifest.get("harbor_agent_exception") or manifest.get("thinking_mismatch"):
        # A benchmark-native verifier may grade useful work after a generic
        # adapter exit, but Harbor setup/agent exceptions and protocol drift are
        # infrastructure. Do not turn either into a model score.
        verify_on_failure = False
    verifier_started = time.time()
    if not adapter_failed or verify_on_failure:
        try:
            verdict = suite.verify(task_data, workdir)
        except Exception as e:
            manifest["error"] = f"Verifier raised: {e}"
            verdict = {
                "passed": False,
                "test_count": 0,
                "grader_output": f"Verifier raised: {e}",
                "exit_code": -1,
                "verifier_failed": True,
            }
    else:
        verdict = {
            "passed": False,
            "test_count": 0,
            "grader_output": (
                f"Adapter failed with exit code {manifest.get('exit_code', -1)}"
                + (f": {manifest.get('error', '')}" if manifest.get("error") else "")
            ),
            "exit_code": manifest.get("exit_code", -1),
            "adapter_failed": True,
        }
    manifest["timing"]["verifier_seconds"] = time.time() - verifier_started
    manifest["timing"]["total_wall_seconds"] = time.time() - start_time

    # Write verdict
    verdict_path = trial_dir / "verdict.json"
    with open(verdict_path, "w") as f:
        json.dump(verdict, f, indent=2)

    # Write manifest
    manifest_path = trial_dir / "manifest.json"
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)

    # Copy workdir state (git diff vs initial)
    if (workdir / ".git").exists():
        diff_file = out_dir / "workdir_diff.patch"
        subprocess.run(
            ["git", "diff"],
            cwd=workdir,
            stdout=open(diff_file, "w"),
            stderr=subprocess.DEVNULL,
        )

    return manifest, verdict


def _is_retryable_infra_failure(manifest: dict, verdict: dict) -> bool:
    """Return True for failures that are infrastructure, not model quality."""
    if verdict.get("verifier_failed"):
        return True
    if verdict.get("adapter_failed") and manifest.get("exit_code") == -1:
        return True
    if manifest.get("exit_code") == -1 and manifest.get("error"):
        return True
    return False


def run_trial_with_retries(
    suite,
    adapter,
    model_id,
    task_id,
    trial_k,
    results_dir,
    vendor_dir,
    thinking=None,
    *,
    retries=2,
):
    """Run a trial, retrying only infrastructure-shaped failures."""
    max_attempts = max(1, int(retries) + 1)
    last_manifest = None
    last_verdict = None
    for attempt in range(1, max_attempts + 1):
        manifest, verdict = run_trial(
            suite,
            adapter,
            model_id,
            task_id,
            trial_k,
            results_dir,
            vendor_dir,
            thinking=thinking,
            force=attempt > 1,
            retry_attempt=attempt,
            max_attempts=max_attempts,
        )
        last_manifest = manifest
        last_verdict = verdict
        if not _is_retryable_infra_failure(manifest, verdict):
            return manifest, verdict
        if attempt < max_attempts:
            print(
                f"[retry] infrastructure failure for {task_id}/trial-{trial_k}; "
                f"retrying attempt {attempt + 1}/{max_attempts}"
            )
    return last_manifest, last_verdict


class RunHeartbeat:
    """Cell-level runner heartbeat for liveness-aware score views."""

    filename = ".runner-heartbeat.json"

    def __init__(
        self,
        *,
        results_dir: Path,
        model_id: str,
        adapter_name: str,
        suite_name: str,
        run_id: str | None,
        total_trials: int,
        concurrency: int = 1,
        interval_seconds: float = 10.0,
    ):
        from harness.path_utils import encode_model_path

        self.path = (
            Path(results_dir)
            / encode_model_path(model_id)
            / adapter_name
            / suite_name
            / self.filename
        )
        now = datetime.now(timezone.utc).isoformat()
        self.data = {
            "state": "starting",
            "pid": os.getpid(),
            "ppid": os.getppid(),
            "hostname": socket.gethostname(),
            "started_at": now,
            "updated_at": now,
            "updated_at_epoch": time.time(),
            "run_id": run_id,
            "model": model_id,
            "adapter": adapter_name,
            "suite": suite_name,
            "current_task": None,
            "current_trial": None,
            "completed_trials": 0,
            "total_trials": total_trials,
            "concurrency": concurrency,
            "active_trials": 0,
            "command": sys.argv,
        }
        self.interval_seconds = interval_seconds
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._termination_callback = self.interrupt

    def start(self) -> None:
        self.update(state="running")
        register_termination_callback(self._termination_callback)
        self._thread.start()

    def update(self, **fields) -> None:
        with self._lock:
            self.data.update(fields)
            self.data["updated_at"] = datetime.now(timezone.utc).isoformat()
            self.data["updated_at_epoch"] = time.time()
            self._write_locked()

    def finish(self, state: str, **fields) -> None:
        unregister_termination_callback(self._termination_callback)
        self._stop.set()
        self.update(state=state, **fields)
        if self._thread.is_alive():
            self._thread.join(timeout=1)

    def interrupt(self, signum: int) -> None:
        """Flush an honest terminal state before the process is signaled."""
        self.finish(
            "interrupted",
            termination_signal=int(signum),
            active_trials=0,
        )

    def _loop(self) -> None:
        while not self._stop.wait(self.interval_seconds):
            self.update()

    def _write_locked(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        temp_path.write_text(json.dumps(self.data, indent=2) + "\n")
        temp_path.replace(self.path)


def main():
    args = parse_args()

    # Coerce CLI path args to Path (argparse returns strings for user input).
    # If --results-dir is omitted, isolate this CLI invocation under a unique
    # model-prefixed run wrapper to avoid accidental parallel writes.
    args.results_dir, args.run_id = resolve_results_dir(
        args.model,
        getattr(args, "results_dir", None),
        getattr(args, "run_id", None),
    )
    args.vendor_dir = Path(args.vendor_dir)
    args.config = Path(args.config)
    validate_args(args)

    # Pre-run reachability check (PLAN.md #137-138). Refuse to start the
    # matrix if the model can't be pinged, unless the user opts out with
    # --skip-reachability. This prevents silent all-fail runs against an
    # unreachable provider.
    if should_run_reachability_check(skip=args.skip_reachability):
        if not check_model_reachable(args.model):
            print(
                f"✗ Model '{args.model}' is unreachable. Aborting.\n"
                f"  (pass --skip-reachability to bypass this check for offline/smoke runs)",
                file=sys.stderr,
            )
            sys.exit(1)
        print(f"✓ Model '{args.model}' is reachable.")

    # Load suite and adapter
    suite = load_suite(args.suite)
    adapter = load_adapter(args.adapter)

    # Get task list from suite
    task_ids = suite.get_task_ids(vendor_dir=args.vendor_dir)

    # Filter by --problems if specified
    if args.problems:
        task_ids = task_ids[:args.problems]

    if not task_ids:
        print(
            f"✗ No tasks discovered for suite '{args.suite}' in {args.vendor_dir}. "
            "Run scripts/setup.sh or provide a valid --vendor-dir.",
            file=sys.stderr,
        )
        sys.exit(1)

    concurrency = getattr(args, "concurrency", 1)
    print(f"Running {len(task_ids)} tasks x {args.k} trials = {len(task_ids) * args.k} total trials")
    print(f"Suite: {args.suite}, Adapter: {args.adapter}, Model: {args.model}")
    print(f"Concurrency: {concurrency}")
    if args.run_id:
        print(f"Run ID: {args.run_id}")
    print(f"Results dir: {args.results_dir}")
    print()

    total_trials = len(task_ids) * args.k
    heartbeat = RunHeartbeat(
        results_dir=args.results_dir,
        model_id=args.model,
        adapter_name=adapter.name,
        suite_name=suite.name,
        run_id=args.run_id,
        total_trials=total_trials,
        concurrency=concurrency,
    )
    completed_trials = 0
    heartbeat.start()

    jobs = [
        (task_id, trial_k)
        for task_id in task_ids
        for trial_k in range(1, args.k + 1)
    ]

    def execute_trial(task_id, trial_k):
        return run_trial_with_retries(
            suite,
            adapter,
            args.model,
            task_id,
            trial_k,
            args.results_dir,
            args.vendor_dir,
            thinking=getattr(args, "thinking", None),
            retries=getattr(args, "retries", 2),
        )

    # Preserve the simple ordered output path at c=1. At c>1, one worker owns
    # each complete task trial (including any infrastructure retries), so the
    # configured bound applies to actual endpoint/Harbor load rather than only
    # to the first attempt.
    try:
        if concurrency == 1:
            for task_id, trial_k in jobs:
                print(f"── Task: {task_id} ──")
                heartbeat.update(
                    state="running",
                    current_task=task_id,
                    current_trial=trial_k,
                    active_trials=1,
                    completed_trials=completed_trials,
                )
                trial_label = f"  Trial {trial_k}/{args.k}"
                print(f"{trial_label}...", end=" ", flush=True)
                try:
                    manifest, verdict = run_with_tty_updates(
                        lambda task_id=task_id, trial_k=trial_k: execute_trial(
                            task_id, trial_k
                        ),
                        trial_label,
                    )
                    completed_trials += 1
                    heartbeat.update(completed_trials=completed_trials)
                    status = "✓" if verdict.get("passed") else "✗"
                    print(
                        f"{status} "
                        f"({manifest['timing'].get('wall_clock_seconds', 0):.1f}s)"
                    )
                except Exception as exc:
                    print(f"ERROR: {exc}")
                print()
        else:
            finished_futures = 0
            with ThreadPoolExecutor(
                max_workers=concurrency,
                thread_name_prefix="cospa-trial",
            ) as executor:
                futures = {
                    executor.submit(execute_trial, task_id, trial_k): (
                        task_id,
                        trial_k,
                    )
                    for task_id, trial_k in jobs
                }
                heartbeat.update(
                    state="running",
                    current_task=None,
                    current_trial=None,
                    active_trials=min(concurrency, len(jobs)),
                    queued_trials=max(0, len(jobs) - concurrency),
                )
                for future in as_completed(futures):
                    task_id, trial_k = futures[future]
                    finished_futures += 1
                    try:
                        manifest, verdict = future.result()
                        completed_trials += 1
                        status = "✓" if verdict.get("passed") else "✗"
                        print(
                            f"── {task_id} trial {trial_k}/{args.k}: {status} "
                            f"({manifest['timing'].get('wall_clock_seconds', 0):.1f}s)"
                        )
                    except Exception as exc:
                        print(
                            f"── {task_id} trial {trial_k}/{args.k}: "
                            f"ERROR: {exc}"
                        )
                    remaining = len(jobs) - finished_futures
                    heartbeat.update(
                        completed_trials=completed_trials,
                        active_trials=min(concurrency, remaining),
                        queued_trials=max(0, remaining - concurrency),
                    )
    except BaseException:
        heartbeat.finish(
            "failed",
            completed_trials=completed_trials,
            active_trials=0,
        )
        raise

    heartbeat.finish(
        "complete",
        current_task=None,
        current_trial=None,
        completed_trials=completed_trials,
        active_trials=0,
        queued_trials=0,
    )
    print("Done.")


if __name__ == "__main__":
    main()
