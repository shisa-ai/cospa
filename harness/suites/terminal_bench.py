"""
Terminal-Bench suite — Harbor-based evaluation.

This suite delegates to Harbor for task execution and verification.
It reads the Terminal-Bench registry to discover tasks, then launches
Harbor jobs with the appropriate agent and model.

Reference: vendor/terminal-bench/CLAUDE.md
"""

import json
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List


PROJECT_ROOT = Path(__file__).resolve().parents[2]


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

    # Map each harness adapter to a distinct custom Harbor agent. Using
    # Harbor's built-in `pi`/`aider` agents would collapse multiple benchmark
    # arms into the same execution path and invalidate the scaffold comparison.
    AGENT_MAP = {
        "pi_vanilla": "harness.harbor_agents:PiVanillaHarborAgent",
        "pi_devstack": "harness.harbor_agents:PiDevstackHarborAgent",
        "pi_superpowers": "harness.harbor_agents:PiSuperpowersHarborAgent",
        "little_coder": "harness.harbor_agents:LittleCoderHarborAgent",
        "little_coder_superpowers": (
            "harness.harbor_agents:LittleCoderSuperpowersHarborAgent"
        ),
    }

    def _harbor_env(
        self,
        model_id: str | None = None,
        thinking: str | None = None,
    ) -> Dict[str, str]:
        """Return env vars for the Harbor subprocess.

        Custom Harbor agents live in this repository, while `harbor run`
        executes in Harbor's own Python environment. Prepending PROJECT_ROOT to
        PYTHONPATH lets Harbor import `harness.harbor_agents`.
        """
        env = os.environ.copy()
        existing = env.get("PYTHONPATH")
        parts = [str(PROJECT_ROOT)]
        if existing:
            parts.append(existing)
        env["PYTHONPATH"] = os.pathsep.join(parts)
        if thinking:
            env["CODING_EVAL_THINKING"] = str(thinking)
            env["CODING_EVAL_REASONING_EFFORT"] = str(thinking)

        if not model_id or "/" not in model_id:
            return env

        provider_name, provider_model = model_id.split("/", 1)
        models_json = Path.home() / ".pi" / "agent" / "models.json"
        providers = {}
        if models_json.exists():
            try:
                with open(models_json) as f:
                    data = json.load(f)
                providers = data.get("providers", data) if isinstance(data, dict) else {}
            except Exception:
                providers = {}

        provider_cfg = providers.get(provider_name, {}) if isinstance(providers, dict) else {}
        if not isinstance(provider_cfg, dict):
            provider_cfg = {}

        base_url = provider_cfg.get("baseUrl") or provider_cfg.get("base_url")
        api_key = provider_cfg.get("apiKey") or provider_cfg.get("api_key")
        api_key_env = (
            provider_cfg.get("apiKeyEnv")
            or provider_cfg.get("api_key_env")
            or provider_cfg.get("apiKeyEnvVar")
            or provider_cfg.get("api_key_env_var")
        )
        if api_key_env and os.environ.get(api_key_env):
            api_key = os.environ[api_key_env]
        if provider_name == "local":
            base_url = os.environ.get("CODING_EVAL_LOCAL_BASE_URL") or base_url
            api_key = os.environ.get("CODING_EVAL_LOCAL_API_KEY") or api_key
        if not base_url:
            return env

        model_entry = {}
        for item in provider_cfg.get("models", []):
            if isinstance(item, dict):
                candidate = item.get("id") or item.get("name")
            else:
                candidate = item
            if candidate in (provider_model, model_id):
                model_entry = item if isinstance(item, dict) else {"id": item}
                break

        resolved_model = model_entry.get("id") or provider_model
        env["CODING_EVAL_PI_PROVIDER_NAME"] = provider_name
        env["CODING_EVAL_PI_PROVIDER_BASE_URL"] = base_url
        env["CODING_EVAL_PI_PROVIDER_API"] = (
            provider_cfg.get("api")
            or provider_cfg.get("api_type")
            or "openai-completions"
        )
        env["CODING_EVAL_PI_PROVIDER_MODEL_ID"] = resolved_model
        env["CODING_EVAL_PI_PROVIDER_MODEL_NAME"] = (
            model_entry.get("name") or resolved_model
        )
        if api_key:
            env["CODING_EVAL_PI_PROVIDER_API_KEY"] = api_key
        if provider_name == "local":
            env["CODING_EVAL_LOCAL_BASE_URL"] = base_url
            if api_key:
                env["CODING_EVAL_LOCAL_API_KEY"] = api_key
        return env

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

    @staticmethod
    def _path_mtime(path: Path) -> float:
        try:
            return path.stat().st_mtime
        except OSError:
            return 0.0

    @staticmethod
    def _read_json(path: Path) -> Dict[str, Any] | None:
        try:
            with open(path) as f:
                data = json.load(f)
            return data if isinstance(data, dict) else None
        except Exception:
            return None

    @staticmethod
    def _numeric_harbor_rewards(verifier_result: Any) -> Dict[str, float]:
        if not isinstance(verifier_result, dict):
            return {}

        raw_rewards = verifier_result.get("rewards")
        if isinstance(raw_rewards, dict):
            return {
                str(key): float(value)
                for key, value in raw_rewards.items()
                if isinstance(value, (int, float))
            }

        for key in ("reward", "score"):
            value = verifier_result.get(key)
            if isinstance(value, (int, float)):
                return {key: float(value)}
        return {}

    def _verdict_from_harbor_trial_result(
        self,
        result_data: Dict[str, Any],
    ) -> Dict[str, Any] | None:
        exception_info = result_data.get("exception_info")
        if exception_info:
            return {
                "passed": False,
                "test_count": 0,
                "grader_output": json.dumps(result_data, indent=2),
                "exit_code": -1,
            }

        verifier_result = result_data.get("verifier_result")
        rewards = self._numeric_harbor_rewards(verifier_result)
        if rewards:
            return {
                "passed": any(value > 0 for value in rewards.values()),
                "test_count": len(rewards),
                "grader_output": json.dumps(result_data, indent=2),
                "exit_code": 0,
            }

        if verifier_result is not None:
            return {
                "passed": False,
                "test_count": 0,
                "grader_output": json.dumps(result_data, indent=2),
                "exit_code": 0,
            }
        return None

    def _verdict_from_harbor_job_result(
        self,
        result_data: Dict[str, Any],
    ) -> Dict[str, Any] | None:
        stats = result_data.get("stats")
        if not isinstance(stats, dict):
            return None
        if stats.get("n_pending_trials", 0) or not result_data.get("finished_at"):
            return None

        evals = stats.get("evals")
        means: list[float] = []
        trial_count = (
            stats.get("n_completed_trials")
            or result_data.get("n_total_trials")
            or 0
        )
        has_errors = stats.get("n_errored_trials", 0) > 0
        if isinstance(evals, dict):
            for eval_result in evals.values():
                if isinstance(eval_result, dict):
                    trial_count = max(trial_count, eval_result.get("n_trials") or 0)
                    metrics = eval_result.get("metrics")
                    if isinstance(metrics, list):
                        for metric in metrics:
                            if isinstance(metric, dict):
                                mean = metric.get("mean")
                                if isinstance(mean, (int, float)):
                                    means.append(float(mean))

        if means:
            return {
                "passed": any(mean > 0 for mean in means),
                "test_count": int(trial_count) if trial_count else len(means),
                "grader_output": json.dumps(result_data, indent=2),
                "exit_code": -1 if has_errors else 0,
            }

        if has_errors:
            return {
                "passed": False,
                "test_count": int(trial_count) if trial_count else 0,
                "grader_output": json.dumps(result_data, indent=2),
                "exit_code": -1,
            }
        return None

    def verify(self, task_data: Dict[str, Any], workdir: Path) -> Dict[str, Any]:
        """
        Verify the solution by checking Harbor output.

        For Terminal-Bench, verification is handled by Harbor's scoring.
        This method checks if Harbor has produced a score for the task.
        """
        # Check if there's a Harbor output directory for this task. Older
        # Terminal-Bench integrations wrote jobs/<job>/trials/<trial>/score.json;
        # Harbor 0.16 writes trial results to jobs/<job>/<trial>/result.json.
        harbor_jobs = workdir.parent / "jobs"
        if harbor_jobs.exists():
            job_dirs = sorted(
                (
                    path
                    for path in harbor_jobs.iterdir()
                    if path.is_dir() and not path.name.startswith("_local_tasks_")
                ),
                key=self._path_mtime,
                reverse=True,
            )
            for job_dir in job_dirs:
                result_files = sorted(
                    (
                        path
                        for path in job_dir.rglob("result.json")
                        if path != job_dir / "result.json"
                    ),
                    key=self._path_mtime,
                    reverse=True,
                )
                for result_file in result_files:
                    result_data = self._read_json(result_file)
                    if result_data is None:
                        continue
                    verdict = self._verdict_from_harbor_trial_result(result_data)
                    if verdict is not None:
                        return verdict

                for score_file in sorted(
                    job_dir.rglob("score.json"),
                    key=self._path_mtime,
                    reverse=True,
                ):
                    score_data = self._read_json(score_file)
                    if score_data is None:
                        continue
                    return {
                        "passed": score_data.get("score", 0) > 0,
                        "test_count": score_data.get("total_tests", 0),
                        "grader_output": json.dumps(score_data, indent=2),
                        "exit_code": 0,
                    }

                job_result = self._read_json(job_dir / "result.json")
                if job_result is not None:
                    verdict = self._verdict_from_harbor_job_result(job_result)
                    if verdict is not None:
                        return verdict

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
        thinking: str | None = None,
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
        workdir = Path(workdir).resolve()
        jobs_dir = Path(jobs_dir).resolve()
        jobs_dir.mkdir(parents=True, exist_ok=True)
        harbor_env = self._harbor_env(model_id, thinking=thinking)

        # Prefer the materialized local task when vendored data is present.
        # This keeps smoke/regression runs independent of Harbor's remote task
        # registry and exercises the exact dataset checked out under vendor/.
        registry_path = None
        task_ref = None
        local_task_path = None
        if vendor_dir is not None:
            vendor_dir = Path(vendor_dir).resolve()
            original_task = vendor_dir / "terminal-bench" / "original-tasks" / task_id
            if original_task.exists():
                local_task_path = jobs_dir / f"_local_tasks_{time.time_ns()}"
                migrate_cmd = [
                    "harbor",
                    "task",
                    "migrate",
                    "--input",
                    str(original_task.resolve()),
                    "--output",
                    str(local_task_path),
                ]
                migrate_result = subprocess.run(
                    migrate_cmd,
                    capture_output=True,
                    text=True,
                    timeout=300,
                    env=harbor_env,
                )
                if migrate_result.returncode != 0:
                    return {
                        "returncode": migrate_result.returncode,
                        "stdout": migrate_result.stdout,
                        "stderr": migrate_result.stderr,
                    }
            reg = vendor_dir / "terminal-bench" / "registry.json"
            if reg.exists() and local_task_path is None:
                registry_path = reg.resolve()
                task_ref = f"terminal-bench-core/{task_id}"

        cmd = [
            "harbor", "run",
            "--agent", agent,
            "--model", model_id,
            "--n-attempts", str(n_attempts),
            "--jobs-dir", str(jobs_dir),
            "--yes",
        ]
        if local_task_path is not None:
            cmd += ["--path", str(local_task_path)]
        elif registry_path is not None:
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
                env=harbor_env,
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
