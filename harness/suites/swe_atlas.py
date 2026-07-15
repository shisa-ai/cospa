"""Pinned SWE Atlas Q&A + Test Writing pilot executed through Harbor."""

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List

from harness.subprocess_utils import run_command
from harness.suites.terminal_bench import PROJECT_ROOT, TerminalBenchSuite


class SweAtlasPilotSuite(TerminalBenchSuite):
    """The predeclared 12-task SWE Atlas cost and reliability pilot.

    SWE Atlas and Terminal-Bench both use Harbor tasks, custom cospa Harbor
    agents, and Harbor-native reward files. Reusing the mature Harbor result
    parser keeps those execution semantics identical while this class owns
    SWE Atlas discovery, materialization, judge configuration, and subchecks.
    """

    name = "swe_atlas_pilot12"
    version = "pilot12-v1"
    languages = ["go", "python", "c", "typescript"]
    task_count = 12
    manifest_path = PROJECT_ROOT / "configs" / "swe_atlas_pilot12.json"

    def _task_index(self) -> Dict[str, Dict[str, Any]]:
        tasks = self._dataset_manifest().get("tasks")
        if not isinstance(tasks, list):
            return {}
        return {
            str(task["id"]): task
            for task in tasks
            if isinstance(task, dict) and task.get("id")
        }

    def _vendor_is_pinned(self, vendor_dir: Path) -> bool:
        manifest = self._dataset_manifest()
        expected = manifest.get("upstream", {}).get("commit")
        repo = Path(vendor_dir) / "swe-atlas"
        if not expected or not (repo / ".git").exists():
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

    @staticmethod
    def _task_source_dir(vendor_dir: Path, task: Dict[str, Any]) -> Path:
        return (
            Path(vendor_dir)
            / "swe-atlas"
            / "data"
            / str(task["upstream_workflow"])
            / str(task["upstream_task_id"])
        )

    def get_task_ids(self, vendor_dir: Path = None) -> List[str]:
        """Return all 12 tasks only when the complete pinned pilot is present."""
        vendor_dir = Path(vendor_dir) if vendor_dir is not None else Path("vendor")
        tasks = self._task_index()
        if len(tasks) != self.task_count or not self._vendor_is_pinned(vendor_dir):
            return []
        task_ids = sorted(tasks)
        if any(
            not self._task_source_dir(vendor_dir, tasks[task_id]).is_dir()
            for task_id in task_ids
        ):
            return []
        return task_ids

    def materialize_task(
        self,
        task_id: str,
        workdir: Path,
        vendor_dir: Path = None,
    ) -> Dict[str, Any]:
        """Copy one upstream Harbor task without altering prompts or graders."""
        vendor_dir = Path(vendor_dir) if vendor_dir is not None else Path("vendor")
        workdir = Path(workdir)
        task = self._task_index().get(task_id)
        if task is None:
            raise ValueError(f"Unknown SWE Atlas pilot task: {task_id}")
        source = self._task_source_dir(vendor_dir, task)
        if not source.is_dir():
            raise FileNotFoundError(f"Missing SWE Atlas task directory: {source}")

        if workdir.exists():
            shutil.rmtree(workdir)
        shutil.copytree(source, workdir)
        instruction = workdir / "instruction.md"
        prompt = instruction.read_text() if instruction.exists() else ""
        manifest = self._dataset_manifest()
        upstream = manifest.get("upstream", {})
        judge = manifest.get("judge", {})
        return {
            "task_id": task_id,
            "prompt": prompt,
            "workflow": task.get("workflow"),
            "language": task.get("language"),
            "category": task.get("category"),
            "test_level": task.get("test_level"),
            "repository": task.get("repository"),
            "base_commit": task.get("base_commit"),
            "swe_atlas_pin": upstream.get("commit"),
            "judge_model": judge.get("model"),
            "model_id": "nvidia/nemotron-3-ultra-550b-a55b",
        }

    def manifest_metadata(self, task_data: Dict[str, Any]) -> Dict[str, Any]:
        """Return task strata and evaluator pins for durable run manifests."""
        return {
            "upstream_commit": task_data.get("swe_atlas_pin"),
            "judge_model": task_data.get("judge_model"),
            "workflow": task_data.get("workflow"),
            "language": task_data.get("language"),
            "category": task_data.get("category"),
            "test_level": task_data.get("test_level"),
            "repository": task_data.get("repository"),
            "base_commit": task_data.get("base_commit"),
        }

    def _harbor_env(
        self,
        model_id: str | None = None,
        thinking: str | None = None,
    ) -> Dict[str, str]:
        env = super()._harbor_env(model_id, thinking=thinking)
        manifest = self._dataset_manifest()
        judge = manifest.get("judge", {})
        key_env = judge.get("api_key_env") or "SWE_ATLAS_JUDGE_API_KEY"
        base_env = judge.get("base_url_env") or "SWE_ATLAS_JUDGE_BASE_URL"
        api_key = os.environ.get(str(key_env)) or os.environ.get("OPENAI_API_KEY")
        base_url = (
            os.environ.get(str(base_env))
            or os.environ.get("OPENAI_API_BASE")
            or os.environ.get("OPENAI_BASE_URL")
        )
        if api_key:
            env["OPENAI_API_KEY"] = api_key
        if base_url:
            env["OPENAI_API_BASE"] = base_url
        if judge.get("model"):
            env["EVAL_MODEL"] = str(judge["model"])
        return env

    @staticmethod
    def _judge_config_error(env: Dict[str, str]) -> str | None:
        missing = []
        if not env.get("OPENAI_API_KEY"):
            missing.append("SWE_ATLAS_JUDGE_API_KEY (or OPENAI_API_KEY)")
        if not env.get("OPENAI_API_BASE"):
            missing.append("SWE_ATLAS_JUDGE_BASE_URL (or OPENAI_API_BASE)")
        if missing:
            return "Missing SWE Atlas judge configuration: " + ", ".join(missing)
        return None

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
        """Run one already-Harbor-native SWE Atlas task from the pinned copy."""
        agent = self.AGENT_MAP.get(adapter_name, "pi")
        workdir = Path(workdir).resolve()
        jobs_dir = Path(jobs_dir).resolve()
        jobs_dir.mkdir(parents=True, exist_ok=True)
        harbor_env = self._harbor_env(model_id, thinking=thinking)
        config_error = self._judge_config_error(harbor_env)
        if config_error:
            return {"returncode": -1, "stdout": "", "stderr": config_error}
        if not (workdir / "task.toml").is_file():
            return {
                "returncode": -1,
                "stdout": "",
                "stderr": f"Missing materialized SWE Atlas task.toml in {workdir}",
            }

        cmd = [
            "harbor",
            "run",
            "--agent",
            agent,
            "--model",
            model_id,
            "--n-attempts",
            str(n_attempts),
            "--jobs-dir",
            str(jobs_dir),
            "--path",
            str(workdir),
            "--verifier-include-logs",
            "**/*",
            "--yes",
        ]
        try:
            result = run_command(
                cmd,
                cwd=str(workdir),
                capture_output=True,
                text=True,
                timeout=21600,
                env=harbor_env,
            )
            return {
                "returncode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
            }
        except subprocess.TimeoutExpired:
            return {
                "returncode": -1,
                "stdout": "",
                "stderr": "SWE Atlas Harbor job timed out",
            }
        except FileNotFoundError as error:
            return {
                "returncode": -1,
                "stdout": "",
                "stderr": f"harbor not found: {error}",
            }
        except Exception as error:
            return {"returncode": -1, "stdout": "", "stderr": str(error)}

    def verify(self, task_data: Dict[str, Any], workdir: Path) -> Dict[str, Any]:
        """Preserve Harbor's reward and expose benchmark-native subchecks."""
        verdict = super().verify(task_data, workdir)
        workflow = task_data.get("workflow")
        verdict["workflow"] = workflow

        jobs_dir = Path(workdir).parent / "jobs"
        candidates = (
            list(jobs_dir.rglob("evaluation_results.json"))
            if jobs_dir.exists()
            else []
        )
        if not candidates:
            return verdict
        evaluation_path = max(candidates, key=self._path_mtime)
        evaluation = self._read_json(evaluation_path)
        if evaluation is None:
            return verdict

        verdict["native_evaluation"] = evaluation
        if workflow == "test_writing":
            verdict["verifier_subchecks"] = {
                "overall": bool(evaluation.get("overall_pass")),
                "rubrics": bool(evaluation.get("rubrics_pass")),
                "manifest": bool(evaluation.get("manifest_pass")),
                "mutation": bool(evaluation.get("mutation_pass")),
            }
        elif workflow == "codebase_qa":
            verdict["verifier_subchecks"] = {
                "overall": bool(evaluation.get("pass")),
                "reward": bool(evaluation.get("reward")),
                "rubrics_scored": evaluation.get("num_scored"),
                "rubrics_passed": evaluation.get("num_passed"),
                "aggregate_score": evaluation.get("agg_score"),
            }
        return verdict
