"""
Terminal-Bench suite — Harbor-based evaluation.

This suite delegates to Harbor for task execution and verification.
It reads the Terminal-Bench registry to discover tasks, then launches
Harbor jobs with the appropriate agent and model.

Reference: vendor/terminal-bench/CLAUDE.md
"""

import json
import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List


@dataclass
class SuiteResult:
    name: str
    adapter: str
    model: str
    task_id: str
    trial: int
    passed: bool
    test_count: int = 0
    wall_clock_seconds: float = 0.0


def _parse_task_yaml(text: str) -> Dict[str, Any]:
    """Parse the subset of task.yaml we care about.

    PyYAML isn't a hard dependency of the harness, so we prefer it when
    available and fall back to a small hand-rolled parser for the
    `instruction:` block scalar. The instruction field is the only one we
    actually consume.
    """
    try:
        import yaml  # type: ignore
        data = yaml.safe_load(text) or {}
        return data if isinstance(data, dict) else {}
    except ImportError:
        pass

    # Hand-rolled fallback: handle `instruction: |-` and `instruction: |`
    # block scalars, plus simple `key: value` lines.
    result: Dict[str, Any] = {}
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.lstrip()
        if not stripped or stripped.startswith("#"):
            i += 1
            continue
        # Match `instruction: |-` or `instruction: |` or `instruction: >-`
        m_instr = re.match(r"^instruction\s*:\s*([|>][-+]?)\s*$", line)
        if m_instr:
            block_indent = len(line) - len(line.lstrip()) + 2  # child indent
            block_lines = []
            i += 1
            while i < len(lines):
                bl = lines[i]
                if bl.strip() == "":
                    block_lines.append("")
                    i += 1
                    continue
                cur_indent = len(bl) - len(bl.lstrip())
                if cur_indent < block_indent:
                    break
                block_lines.append(bl[block_indent:])
                i += 1
            result["instruction"] = "\n".join(block_lines).rstrip() + "\n"
            continue
        # Plain `key: value`
        m_kv = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*:\s*(.*)$", line)
        if m_kv and m_kv.group(2):
            result[m_kv.group(1)] = m_kv.group(2).strip().strip('"\'')
        i += 1
    return result


class TerminalBenchSuite:
    """Terminal-Bench suite using Harbor for execution."""

    name = "terminal_bench"
    version = "0.1"
    languages = ["python"]
    task_count = 0

    # Harbor is the source of truth for Terminal-Bench scoring, so we want
    # verify() to run even if the (no-op) adapter returned nonzero — the
    # adapter path is bypassed entirely for this suite, but this flag keeps
    # the semantics explicit.
    verify_on_adapter_failure = True

    # Map adapter name -> Harbor agent. pi* adapters run as the `pi` agent;
    # little_coder* run as `aider` (little-coder is a pi fork, but Harbor
    # exposes it through the aider adapter contract).
    AGENT_MAP = {
        "pi_vanilla": "pi",
        "pi_devstack": "pi",
        "pi_superpowers": "pi",
        "little_coder": "aider",
        "little_coder_superpowers": "aider",
    }

    def get_task_ids(self, vendor_dir: Path = None) -> List[str]:
        """Get all task IDs from Terminal-Bench registry or original-tasks directory."""
        if vendor_dir is None:
            vendor_dir = Path("vendor")
        vendor_dir = Path(vendor_dir)

        registry_file = vendor_dir / "terminal-bench" / "registry.json"
        if not registry_file.exists():
            return []

        with open(registry_file) as f:
            registry = json.load(f)

        # Registry is a list of dataset versions
        task_ids = []
        for entry in registry:
            # Use the head version if available, otherwise use the latest
            if entry.get("version") == "head" and entry.get("task_id_subset") is None:
                # Head version with no subset = all tasks
                # Discover tasks from the original-tasks directory
                tasks_dir = vendor_dir / "terminal-bench" / "original-tasks"
                if tasks_dir.exists():
                    for task_dir in tasks_dir.iterdir():
                        if task_dir.is_dir():
                            task_ids.append(task_dir.name)
                break
            elif entry.get("task_id_subset"):
                task_ids.extend(entry["task_id_subset"])

        return sorted(set(task_ids))  # Deduplicate

    def materialize_task(self, task_id: str, workdir: Path, vendor_dir: Path = None) -> Dict[str, Any]:
        """
        Materialize a Terminal-Bench task into the workdir.

        Real Terminal-Bench tasks are described by a `task.yaml` whose
        `instruction` field is the agent prompt. Older/legacy tasks used
        `instruction.md`; we support both. The verifier/scorer fields are
        optional (most tasks use Harbor's built-in pytest parser instead),
        so we initialize them to empty strings and never raise if they're
        absent.
        """
        if vendor_dir is None:
            vendor_dir = Path("vendor")
        vendor_dir = Path(vendor_dir)

        prompt = ""
        verifier = ""
        scorer = ""
        task_meta: Dict[str, Any] = {}

        original_task_dir = vendor_dir / "terminal-bench" / "original-tasks" / task_id
        if original_task_dir.exists():
            if workdir.exists():
                shutil.rmtree(workdir)
            workdir.mkdir(parents=True, exist_ok=True)
            shutil.copytree(original_task_dir, workdir, dirs_exist_ok=True)

            # Primary source: task.yaml `instruction` field
            task_yaml = workdir / "task.yaml"
            if task_yaml.exists():
                task_meta = _parse_task_yaml(task_yaml.read_text())
                prompt = task_meta.get("instruction", "")

            # Legacy fallback: instruction.md
            if not prompt:
                instruction_file = workdir / "instruction.md"
                if instruction_file.exists():
                    prompt = instruction_file.read_text()

            # Optional verifier.py / scorer.py (not present in most tasks)
            verifier_file = workdir / "verifier.py"
            if verifier_file.exists():
                verifier = verifier_file.read_text()
            scorer_file = workdir / "scorer.py"
            if scorer_file.exists():
                scorer = scorer_file.read_text()
        else:
            prompt = f"Terminal-Bench task: {task_id}"

        return {
            "task_id": task_id,
            "prompt": prompt,
            "verifier": verifier,
            "scorer": scorer,
            "task_meta": task_meta,
            "model_id": "nvidia/nemotron-3-ultra-550b-a55b",
        }

    def verify(self, task_data: Dict[str, Any], workdir: Path) -> Dict[str, Any]:
        """
        Verify the solution by checking Harbor output.

        For Terminal-Bench, verification is handled by Harbor's scoring.
        This method checks if Harbor has produced a score for the task.
        """
        # Check if there's a Harbor output directory for this task
        # Harbor stores results in jobs/<job_id>/trials/<trial_id>/
        harbor_jobs = workdir.parent / "jobs"
        if harbor_jobs.exists():
            # Look for recent job output
            for job_dir in sorted(harbor_jobs.iterdir(), reverse=True):
                if job_dir.is_dir():
                    trials_dir = job_dir / "trials"
                    if trials_dir.exists():
                        for trial_dir in trials_dir.iterdir():
                            if trial_dir.is_dir():
                                score_file = trial_dir / "score.json"
                                if score_file.exists():
                                    try:
                                        with open(score_file) as f:
                                            score_data = json.load(f)
                                        return {
                                            "passed": score_data.get("score", 0) > 0,
                                            "test_count": score_data.get("total_tests", 0),
                                            "grader_output": json.dumps(score_data, indent=2),
                                            "exit_code": 0,
                                        }
                                    except Exception:
                                        pass

        # If no Harbor output, return a pending status
        return {
            "passed": False,
            "test_count": 0,
            "grader_output": "No Harbor output found — run harbor run first",
            "exit_code": -1,
            "pending": True,
        }

    def run_harbor_job(
        self,
        task_id: str,
        model_id: str,
        adapter_name: str,
        workdir: Path,
        jobs_dir: Path,
        n_attempts: int = 1,
        vendor_dir: Path = None,
    ) -> Dict[str, Any]:
        """
        Run a Harbor job for a Terminal-Bench task.

        This is the primary execution path for Terminal-Bench tasks. It
        delegates to `harbor run` with the agent, model, and dataset
        resolved from the vendored registry.

        Per `harbor run --help`:
          -k, --n-attempts   attempts per trial   (NOT -n, which is concurrency)
          -a, --agent        agent to run
          -m, --model        model name for the agent
          -o, --jobs-dir     directory for job results
          --registry-path    path to a registry.json
          -t, --task         run a single task from the registry
        """
        agent = self.AGENT_MAP.get(adapter_name, "pi")

        # Resolve the registry so Harbor can pick up the task definition.
        # The head version's commit_hash/branch identify the dataset.
        registry_path = None
        task_ref = None
        if vendor_dir is not None:
            vendor_dir = Path(vendor_dir)
            reg = vendor_dir / "terminal-bench" / "registry.json"
            if reg.exists():
                registry_path = reg
                task_ref = f"terminal-bench-core/{task_id}"

        cmd = [
            "harbor", "run",
            "--agent", agent,
            "--model", model_id,
            "--n-attempts", str(n_attempts),
            "--jobs-dir", str(jobs_dir),
            "--yes",
        ]
        if registry_path is not None:
            cmd += ["--registry-path", str(registry_path), "--task", task_ref]
        else:
            # Fallback: point Harbor at the task directory directly.
            cmd += ["--path", str(workdir)]

        try:
            result = subprocess.run(
                cmd,
                cwd=str(workdir),
                capture_output=True,
                text=True,
                timeout=3600,
            )
            return {
                "returncode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
            }
        except subprocess.TimeoutExpired:
            return {"returncode": -1, "stdout": "", "stderr": "Harbor job timed out"}
        except FileNotFoundError as e:
            return {"returncode": -1, "stdout": "", "stderr": f"harbor not found: {e}"}
        except Exception as e:
            return {"returncode": -1, "stdout": "", "stderr": str(e)}
