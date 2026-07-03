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
    return parser.parse_args()


def get_env_hash():
    """Get a hash of the current environment for reproducibility."""
    try:
        result = subprocess.run(
            ["mamba", "run", "-n", "coding-eval", "python", "-c", "import sys; print(sys.executable)"],
            capture_output=True, text=True, timeout=10
        )
        return result.stdout.strip()
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

        # Look for the head version's pin
        for entry in registry:
            if entry.get("version") == "head":
                return entry.get("pin", "unknown")

        return "unknown"
    except Exception:
        return "unknown"


def run_trial(suite, adapter, model_id, task_id, trial_k, results_dir, vendor_dir):
    """Run a single trial of a single task."""
    from harness.path_utils import encode_model_path, encode_task_path

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
            "served_model": model_id,  # May differ from model_id if using rtk proxy
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

    start_time = time.time()
    adapter_failed = False
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

    # Run the suite's verifier only if adapter didn't fail
    # (unless suite explicitly wants to verify even on failure)
    if not adapter_failed:
        verdict = suite.verify(task_data, workdir)
    else:
        verdict = {
            "passed": False,
            "test_count": 0,
            "grader_output": f"Adapter failed with exit code {manifest.get('exit_code', -1)}",
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

    # Load suite and adapter
    suite = load_suite(args.suite)
    adapter = load_adapter(args.adapter)

    # Get task list from suite
    task_ids = suite.get_task_ids(vendor_dir=args.vendor_dir)

    # Filter by --problems if specified
    if args.problems:
        task_ids = task_ids[:args.problems]

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
