"""
Terminal-Bench suite — Harbor-based evaluation.

This suite delegates to Harbor for task execution and verification.
It reads cospa's immutable Terminal-Bench Core 0.1.1 manifest, then launches
Harbor jobs with the appropriate agent and model.

Reference: vendor/terminal-bench/CLAUDE.md
"""

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List

from harness.subprocess_utils import run_command
from harness.telemetry import load_model_metadata


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
            value = "\n".join(block_lines).rstrip("\n")
            if not m_instr.group(1).endswith("-"):
                value += "\n"
            result["instruction"] = value
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
    version = "0.1.1"
    languages = ["python"]
    task_count = 80
    manifest_path = PROJECT_ROOT / "configs" / "terminal_bench_core_0.1.1.json"

    # Harbor is the source of truth for Terminal-Bench scoring, so we want
    # verify() to run even if the (no-op) adapter returned nonzero — the
    # adapter path is bypassed entirely for this suite, but this flag keeps
    # the semantics explicit.
    verify_on_adapter_failure = True

    # Map each harness adapter to a distinct custom Harbor agent. Using
    # Harbor's built-in `pi`/`aider` agents would collapse multiple benchmark
    # arms into the same execution path and invalidate the scaffold comparison.
    DEVSTACK_ADAPTERS = frozenset({
        "pi_devstack",
        "pi_devstack_superpowers",
    })
    HEADLESS_DISABLED_PACKAGE_FRAGMENTS = (
        "npm:@the-forge-flow/camoufox-pi",
        "github.com/lhl/pi-zentui",
    )

    AGENT_MAP = {
        "pi_vanilla": "harness.harbor_agents:PiVanillaHarborAgent",
        "pi_devstack": "harness.harbor_agents:PiDevstackHarborAgent",
        "pi_devstack_superpowers": (
            "harness.harbor_agents:PiDevstackSuperpowersHarborAgent"
        ),
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

        harbor_base_url = os.environ.get("CODING_EVAL_HARBOR_MODEL_BASE_URL")
        base_url = (
            harbor_base_url
            or provider_cfg.get("baseUrl")
            or provider_cfg.get("base_url")
        )
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
            base_url = (
                harbor_base_url
                or os.environ.get("CODING_EVAL_LOCAL_BASE_URL")
                or base_url
            )
            api_key = os.environ.get("CODING_EVAL_LOCAL_API_KEY") or api_key
        if not base_url:
            return env

        model_entry = {}
        wanted_models = {
            re.sub(r"[^a-z0-9]", "", provider_model.lower()),
            re.sub(r"[^a-z0-9]", "", model_id.lower()),
        }
        for item in provider_cfg.get("models", []):
            if isinstance(item, dict):
                candidate = item.get("id") or item.get("name")
            else:
                candidate = item
            normalized = re.sub(r"[^a-z0-9]", "", str(candidate).lower())
            if normalized in wanted_models:
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
        model_metadata = load_model_metadata(model_id)
        sampling_params = model_metadata.get("sampling_params")
        if isinstance(sampling_params, dict) and sampling_params:
            env["CODING_EVAL_PI_SAMPLING_PARAMS"] = json.dumps(
                sampling_params, sort_keys=True
            )
        if model_metadata.get("context_window") is not None:
            env["CODING_EVAL_PI_CONTEXT_WINDOW"] = str(
                model_metadata["context_window"]
            )
        if model_metadata.get("max_tokens") is not None:
            env["CODING_EVAL_PI_MAX_TOKENS"] = str(
                model_metadata["max_tokens"]
            )
        thinking_level_map = model_entry.get("thinkingLevelMap")
        if isinstance(thinking_level_map, dict) and thinking_level_map:
            env["CODING_EVAL_PI_THINKING_LEVEL_MAP"] = json.dumps(
                thinking_level_map, sort_keys=True
            )
        compat = model_entry.get("compat")
        if isinstance(compat, dict) and compat:
            env["CODING_EVAL_PI_COMPAT"] = json.dumps(compat, sort_keys=True)
        if provider_name == "local":
            env["CODING_EVAL_LOCAL_BASE_URL"] = base_url
            if api_key:
                env["CODING_EVAL_LOCAL_API_KEY"] = api_key
        return env

    def _pi_runtime_mounts(self) -> list[dict[str, Any]]:
        """Mount the selected host pi/node runtime to avoid task network setup."""
        configured = os.environ.get("CODING_EVAL_PI_RUNTIME_DIR")
        if configured:
            runtime_dir = Path(configured).expanduser()
        else:
            pi_executable = shutil.which("pi")
            if not pi_executable:
                return []
            runtime_dir = Path(pi_executable).parent.parent
        runtime_dir = runtime_dir.resolve()
        if not (
            (runtime_dir / "bin" / "node").is_file()
            and (runtime_dir / "bin" / "pi").is_file()
        ):
            return []
        return [
            {
                "type": "bind",
                "source": str(runtime_dir),
                "target": "/opt/coding-eval-pi-runtime",
                "read_only": True,
            }
        ]

    def _compat_node_mounts(self) -> list[dict[str, Any]]:
        """Mount a glibc-2.17 Node build for legacy benchmark images."""
        configured = os.environ.get("CODING_EVAL_PI_COMPAT_NODE_DIR")
        compat_dir = (
            Path(configured).expanduser()
            if configured
            else Path.home() / ".cache" / "cospa-node-v22.14.0-glibc217"
        )
        compat_dir = compat_dir.resolve()
        if not (compat_dir / "bin" / "node").is_file():
            return []
        return [
            {
                "type": "bind",
                "source": str(compat_dir),
                "target": "/opt/coding-eval-node-compat",
                "read_only": True,
            }
        ]

    @classmethod
    def _sanitized_devstack_settings(cls, profile_dir: Path) -> Path:
        """Snapshot host settings with headless-unsafe resources disabled."""
        source_path = profile_dir / "settings.json"
        try:
            settings = json.loads(source_path.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"Invalid devstack settings: {source_path}") from exc
        if not isinstance(settings, dict):
            raise ValueError(f"Invalid devstack settings object: {source_path}")

        packages = settings.get("packages", [])
        if not isinstance(packages, list):
            raise ValueError(f"Invalid devstack packages list: {source_path}")
        sanitized_packages = []
        for entry in packages:
            package_source = (
                entry.get("source") if isinstance(entry, dict) else entry
            )
            if not isinstance(package_source, str) or not any(
                fragment in package_source
                for fragment in cls.HEADLESS_DISABLED_PACKAGE_FRAGMENTS
            ):
                sanitized_packages.append(entry)
                continue
            filtered = dict(entry) if isinstance(entry, dict) else {
                "source": package_source,
            }
            filtered.update({
                "extensions": [],
                "skills": [],
                "prompts": [],
                "themes": [],
            })
            sanitized_packages.append(filtered)
        settings["packages"] = sanitized_packages

        payload = json.dumps(settings, indent=2, sort_keys=True) + "\n"
        digest = hashlib.sha256(payload.encode()).hexdigest()[:16]
        snapshot_dir = profile_dir / ".cospa-devstack" / digest
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        snapshot_path = snapshot_dir / "settings.json"
        if not snapshot_path.is_file() or snapshot_path.read_text() != payload:
            with tempfile.NamedTemporaryFile(
                mode="w",
                dir=snapshot_dir,
                prefix=".settings.",
                delete=False,
            ) as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
                temporary_path = Path(handle.name)
            os.replace(temporary_path, snapshot_path)
        return snapshot_path

    def _devstack_mounts(
        self,
        adapter_name: str,
    ) -> list[dict[str, Any]]:
        """Return read-only mounts for the canonical devstack package profile.

        Harbor task containers start with an empty pi home. Merely omitting
        ``--no-extensions`` therefore makes ``pi_devstack`` behaviorally the
        same as vanilla. Mount the selected, sanitized package snapshot so the
        custom Harbor agent can recreate normal pi package discovery without
        exposing mutable host settings inside the benchmark container.
        """
        if adapter_name not in self.DEVSTACK_ADAPTERS:
            return []

        configured = os.environ.get("CODING_EVAL_DEVSTACK_PROFILE_DIR")
        profile_dir = (
            Path(configured).expanduser()
            if configured
            else Path.home() / ".pi" / "agent"
        ).resolve()
        required_sources = (
            profile_dir / "npm",
            profile_dir / "git",
            profile_dir / "settings.json",
        )
        missing = [
            str(source) for source in required_sources if not source.exists()
        ]
        if missing:
            raise FileNotFoundError(
                "Terminal-Bench devstack profile is incomplete; missing: "
                + ", ".join(missing)
            )
        settings_source = (
            profile_dir / "settings.json"
            if configured
            else self._sanitized_devstack_settings(profile_dir)
        )
        sources = (
            (profile_dir / "npm", "/opt/coding-eval-devstack/npm"),
            (profile_dir / "git", "/opt/coding-eval-devstack/git"),
            (settings_source, "/opt/coding-eval-devstack/settings.json"),
        )
        return [
            {
                "type": "bind",
                "source": str(source),
                "target": target,
                "read_only": True,
            }
            for source, target in sources
        ]

    def _dataset_manifest(self) -> Dict[str, Any]:
        """Load cospa's immutable Terminal-Bench Core dataset manifest."""
        try:
            with open(self.manifest_path) as f:
                manifest = json.load(f)
        except (OSError, json.JSONDecodeError):
            return {}
        return manifest if isinstance(manifest, dict) else {}

    def _task_source_dir(self, vendor_dir: Path) -> Path | None:
        manifest = self._dataset_manifest()
        dataset_path = manifest.get("dataset_path")
        if not isinstance(dataset_path, str) or not dataset_path:
            return None
        return Path(vendor_dir) / "terminal-bench" / dataset_path

    def _vendor_is_pinned(self, vendor_dir: Path) -> bool:
        """Reject a real git checkout that is not at the declared commit."""
        manifest = self._dataset_manifest()
        expected = manifest.get("commit_hash")
        repo = Path(vendor_dir) / "terminal-bench"
        if not expected or not (repo / ".git").exists():
            # Unit fixtures are not git repositories; task-shape checks below
            # still ensure the complete declared subset is present.
            return True
        try:
            result = subprocess.run(
                ["git", "-C", str(repo), "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                timeout=5,
            )
        except Exception:
            return False
        return result.returncode == 0 and result.stdout.strip() == expected

    def get_task_ids(self, vendor_dir: Path = None) -> List[str]:
        """Return the complete, immutable Terminal-Bench Core 0.1.1 subset."""
        if vendor_dir is None:
            vendor_dir = Path("vendor")
        vendor_dir = Path(vendor_dir)
        manifest = self._dataset_manifest()
        task_ids = manifest.get("task_ids")
        tasks_dir = self._task_source_dir(vendor_dir)
        if (
            not isinstance(task_ids, list)
            or not task_ids
            or tasks_dir is None
            or not self._vendor_is_pinned(vendor_dir)
        ):
            return []

        normalized = sorted({str(task_id) for task_id in task_ids})
        # Never silently run a partial/mismatched checkout under the 0.1.1
        # label. setup.sh checks out the matching commit, which contains all 80.
        if any(not (tasks_dir / task_id).is_dir() for task_id in normalized):
            return []
        return normalized

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

        tasks_dir = self._task_source_dir(vendor_dir)
        original_task_dir = tasks_dir / task_id if tasks_dir is not None else None
        if original_task_dir is not None and original_task_dir.exists():
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

    @staticmethod
    def _set_agent_network_allowlist(task_root: Path, model_host: str) -> int:
        """Restrict each migrated Harbor task's agent phase to the model host."""
        task_files = list(Path(task_root).rglob("task.toml"))
        for task_file in task_files:
            lines = task_file.read_text().splitlines()
            section_starts = []
            for index, line in enumerate(lines):
                match = re.fullmatch(r"\[([^]]+)]", line.strip())
                if match and (
                    match.group(1) == "agent"
                    or match.group(1).endswith(".agent")
                ):
                    section_starts.append(index)
            if not any(lines[index].strip() == "[agent]" for index in section_starts):
                if lines and lines[-1].strip():
                    lines.append("")
                lines.extend(["[agent]", 'network_mode = "allowlist"'])
                lines.append(f"allowed_hosts = {json.dumps([model_host])}")
                section_starts.append(len(lines) - 3)
            for section_start in reversed(section_starts):
                section_end = next(
                    (
                        i
                        for i in range(section_start + 1, len(lines))
                        if lines[i].lstrip().startswith("[")
                    ),
                    len(lines),
                )
                body = [
                    line
                    for line in lines[section_start + 1 : section_end]
                    if not re.match(
                        r"^\s*(network_mode|allowed_hosts)\s*=", line
                    )
                ]
                replacement = [
                    lines[section_start],
                    'network_mode = "allowlist"',
                    f"allowed_hosts = {json.dumps([model_host])}",
                    *body,
                ]
                lines[section_start:section_end] = replacement
            task_file.write_text("\n".join(lines) + "\n")
        return len(task_files)

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
        delegates to `harbor run` with the agent, model, and pinned local
        dataset task.

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

        base_url = harbor_env.get("CODING_EVAL_PI_PROVIDER_BASE_URL")
        if not base_url:
            return {
                "returncode": -1,
                "stdout": "",
                "stderr": (
                    "Hermetic Terminal-Bench execution requires a model base "
                    "URL. Configure the selected pi provider or set "
                    "CODING_EVAL_HARBOR_MODEL_BASE_URL to a container-reachable "
                    "endpoint."
                ),
            }

        from urllib.parse import urlparse

        model_host = urlparse(base_url).hostname
        if not model_host:
            return {
                "returncode": -1,
                "stdout": "",
                "stderr": f"Invalid Harbor model base URL: {base_url!r}",
            }
        if model_host in {"127.0.0.1", "::1", "localhost"}:
            return {
                "returncode": -1,
                "stdout": "",
                "stderr": (
                    "The Harbor agent cannot reach a host loopback model URL "
                    f"({base_url}). Set CODING_EVAL_HARBOR_MODEL_BASE_URL to "
                    "a container-reachable relay hostname or address."
                ),
            }

        # Materialize a local task before applying the solving-phase policy.
        # This keeps smoke/regression runs independent of Harbor's remote task
        # registry and exercises the exact dataset checked out under vendor/.
        local_task_path = None
        if vendor_dir is not None:
            vendor_dir = Path(vendor_dir).resolve()
            tasks_dir = self._task_source_dir(vendor_dir)
            original_task = tasks_dir / task_id if tasks_dir is not None else None
            if original_task is not None and original_task.exists():
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
                migrate_result = run_command(
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
        if local_task_path is None and list(workdir.rglob("task.toml")):
            local_task_path = workdir
        if local_task_path is None:
            return {
                "returncode": -1,
                "stdout": "",
                "stderr": (
                    "Hermetic Terminal-Bench execution requires a local "
                    "Harbor task containing task.toml; registry fallback is "
                    "disabled because it would bypass the agent network policy."
                ),
            }
        if self._set_agent_network_allowlist(local_task_path, model_host) == 0:
            return {
                "returncode": -1,
                "stdout": "",
                "stderr": (
                    "Hermetic Terminal-Bench execution could not find task.toml "
                    "after task migration."
                ),
            }

        cmd = [
            "harbor", "run",
            "--agent", agent,
            "--model", model_id,
            "--n-attempts", str(n_attempts),
            "--jobs-dir", str(jobs_dir),
            "--allow-agent-host", model_host,
            "--yes",
        ]
        mounts = (
            self._pi_runtime_mounts()
            + self._compat_node_mounts()
            + self._devstack_mounts(adapter_name)
        )
        if mounts:
            cmd += ["--mounts", json.dumps(mounts)]

        cmd += ["--path", str(local_task_path)]

        try:
            result = run_command(
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
