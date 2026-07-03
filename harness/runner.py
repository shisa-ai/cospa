"""
runner.py — Single load-bearing component of the coding-eval harness.

Takes (suite, model, adapter, trial_k) and runs one task:
  1. Spawns the adapter as a subprocess
  2. Captures stdout/stderr/exit
  3. Runs the suite's verifier
  4. Writes results/<model>/<adapter>/<suite>/<task_id>/trial-<k>/{manifest.json, out/, verdict.json}

Usage:
  mamba run -n coding-eval python harness/runner.py \
    --suite aider_polyglot \
    --adapter pi_vanilla \
    --model nvidia/nemotron-3-ultra-550b-a55b \
    --problems 5 \
    --k 1
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Add project root to path so we can import harness modules
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from harness.adapters import load_adapter
from harness.suites import load_suite


def parse_args():
    parser = argparse.ArgumentParser(description="Run a single eval trial")
    parser.add_argument("--suite", required=True, help="Suite name (aider_polyglot, terminal_bench)")
    parser.add_argument("--adapter", required=True, help="Adapter name (pi_vanilla, pi_devstack, little_coder)")
    parser.add_argument("--model", required=True, help="Model ID (e.g. nvidia/nemotron-3-ultra-550b-a55b)")
    parser.add_argument("--problems", type=int, default=None, help="Number of problems to run (None = all)")
    parser.add_argument("--k", type=int, default=1, help="Number of trials per problem")
    parser.add_argument("--results-dir", default=PROJECT_ROOT / "results", help="Results output directory")
    parser.add_argument("--vendor-dir", default=PROJECT_ROOT / "vendor", help="Vendored datasets directory")
    parser.add_argument("--config", default=PROJECT_ROOT / "configs" / "models.yaml", help="Models config file")
    parser.add_argument(
        "--skip-reachability",
        action="store_true",
        default=False,
        help="Skip the pre-run model reachability check (use for offline/smoke runs)",
    )
    return parser.parse_args()


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
    """Get the Terminal-Bench pin/patch hash from the registry."""
    registry_file = Path(vendor_dir) / "terminal-bench" / "registry.json"
    if not registry_file.exists():
        return "unknown"

    try:
        with open(registry_file) as f:
            registry = json.load(f)

        # Look for the head version's commit hash. The registry uses
        # `commit_hash` (not `pin`); fall back to `pin` for older schemas.
        for entry in registry:
            if entry.get("version") == "head":
                pin = entry.get("commit_hash") or entry.get("pin") or "unknown"
                if pin != "head":
                    return pin

                # The vendored registry currently uses the symbolic string
                # "head". Resolve it to the actual local git commit so the
                # manifest contains an immutable dataset pin.
                result = subprocess.run(
                    ["git", "-C", str(registry_file.parent), "rev-parse", "HEAD"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if result.returncode == 0 and result.stdout.strip():
                    return result.stdout.strip()
                return pin

        return "unknown"
    except Exception:
        return "unknown"


def _manifest_sampling(task_data: dict) -> dict:
    """Return explicit sampling metadata for the manifest.

    The harness does not control server-side sampling for pi/little-coder
    providers, but null values make runs look accidentally incomplete. Use
    task/env overrides when available and otherwise record a deliberate
    "server-default" marker.
    """
    return {
        "temperature": task_data.get("temperature")
        or os.environ.get("CODING_EVAL_TEMPERATURE")
        or "server-default",
        "top_p": task_data.get("top_p")
        or os.environ.get("CODING_EVAL_TOP_P")
        or "server-default",
        "max_tokens": task_data.get("max_tokens")
        or os.environ.get("CODING_EVAL_MAX_TOKENS")
        or "server-default",
    }


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

    payload = json.dumps({
        "model": model_name,
        "messages": [{"role": "user", "content": "hi"}],
        "max_tokens": 1,
    }).encode()
    req = urllib.request.Request(
        f"{base_url.rstrip('/')}/chat/completions",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status == 200
    except urllib.error.HTTPError as e:
        return e.code == 200
    except Exception:
        return False


def run_trial(suite, adapter, model_id, task_id, trial_k, results_dir, vendor_dir):
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
    trial_dir.mkdir(parents=True, exist_ok=True)

    # Create workdir for this trial
    workdir = trial_dir / "workdir"
    workdir.mkdir(exist_ok=True)

    # Materialize the task into the workdir
    task_data = suite.materialize_task(task_id, workdir, vendor_dir)

    # Override model_id with the actual model from args
    task_data["model_id"] = model_id

    # Parse provider from model_id (e.g., "nvidia/nemotron-..." -> provider="nvidia")
    provider = model_id.split("/")[0] if "/" in model_id else "unknown"

    # Build manifest with all required fields
    manifest = {
        "model": {
            "id": model_id,
            "provider": provider,
            "served_model": (
                task_data.get("served_model")
                or os.environ.get("CODING_EVAL_SERVED_MODEL")
                or model_id
            ),
        },
        "adapter": {
            "id": adapter.__class__.__name__,
            "version": getattr(adapter, "version", "unknown"),
        },
        "suite": {
            "id": suite.__class__.__name__,
            "task_id": task_id,
        },
        "trial": trial_k,
        "sampling": _manifest_sampling(task_data),
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

    # Run the adapter
    out_dir = trial_dir / "out"
    out_dir.mkdir(exist_ok=True)

    log_file = out_dir / "session.log"
    stderr_file = out_dir / "stderr.log"

    # Terminal-Bench is Harbor-driven: the suite owns execution and scoring.
    # The generic adapter path does not apply (there is no in-workdir prompt
    # loop; Harbor runs the agent inside a container and scores via pytest).
    # Suites that expose `run_harbor_job` take over here.
    start_time = time.time()
    adapter_failed = False
    harbor_result = None
    if hasattr(suite, "run_harbor_job") and getattr(suite, "name", "") == "terminal_bench":
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
        except Exception as e:
            manifest["exit_code"] = -1
            manifest["timing"]["wall_clock_seconds"] = time.time() - start_time
            manifest["run_end_time"] = datetime.now(timezone.utc).isoformat()
            manifest["error"] = str(e)
            adapter_failed = True

            # Write error to log
            with open(log_file, "a") as f:
                f.write(f"\n[ERROR] {e}\n")

    # Run the suite's verifier only if the adapter succeeded. A suite may
    # explicitly opt into post-failure verification by setting
    # `verify_on_adapter_failure = True` (e.g. for suites whose verifier is
    # the source of truth, like a Harbor-scored Terminal-Bench trial).
    verify_on_failure = getattr(
        suite, "verify_on_adapter_failure", False
    )
    if not adapter_failed or verify_on_failure:
        verdict = suite.verify(task_data, workdir)
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


def main():
    args = parse_args()

    # Coerce CLI path args to Path (argparse returns strings for user input)
    args.results_dir = Path(args.results_dir)
    args.vendor_dir = Path(args.vendor_dir)
    args.config = Path(args.config)

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

    print(f"Running {len(task_ids)} tasks x {args.k} trials = {len(task_ids) * args.k} total trials")
    print(f"Suite: {args.suite}, Adapter: {args.adapter}, Model: {args.model}")
    print(f"Results dir: {args.results_dir}")
    print()

    # Run trials
    for task_id in task_ids:
        print(f"── Task: {task_id} ──")
        for k in range(1, args.k + 1):
            print(f"  Trial {k}/{args.k}...", end=" ", flush=True)
            try:
                manifest, verdict = run_trial(
                    suite, adapter, args.model, task_id, k,
                    args.results_dir, args.vendor_dir
                )
                status = "✓" if verdict.get("passed") else "✗"
                print(f"{status} ({manifest['timing'].get('wall_clock_seconds', 0):.1f}s)")
            except Exception as e:
                print(f"ERROR: {e}")
        print()

    print("Done.")


if __name__ == "__main__":
    main()
