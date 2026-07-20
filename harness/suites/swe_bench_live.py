"""Pinned SWE-bench-Live/MultiLang canary executed through Harbor."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tomllib
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import urlparse

from harness.subprocess_utils import run_command
from harness.suites.terminal_bench import PROJECT_ROOT, TerminalBenchSuite


class SweBenchLiveMultilangCanarySuite(TerminalBenchSuite):
    """A recent, balanced 24-task multilingual issue-resolution canary.

    The task image and existing repository tests are available to the agent.
    The resolving PR's test patch, parser, expected test identities, and gold
    solution remain in Harbor's tests/ and solution/ channels until their
    respective post-agent phases.
    """

    name = "swe_bench_live_multilang_canary24"
    version = "canary24-v1"
    languages = ["c", "cpp", "cs", "go", "java", "js", "rust", "ts"]
    task_count = 24
    manifest_path = (
        PROJECT_ROOT / "configs" / "swe_bench_live_multilang_canary24.json"
    )

    @staticmethod
    def _canonical_row_hash(row: dict) -> str:
        payload = json.dumps(
            row,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode()
        return hashlib.sha256(payload).hexdigest()

    def _task_index(self) -> Dict[str, Dict[str, Any]]:
        tasks = self._dataset_manifest().get("tasks")
        if not isinstance(tasks, list):
            return {}
        return {
            str(task["id"]): task
            for task in tasks
            if isinstance(task, dict) and task.get("id")
        }

    def _vendor_dataset_dir(self, vendor_dir: Path) -> Path:
        return Path(vendor_dir) / "swe-bench-live-multilang"

    def _load_rows(self, vendor_dir: Path) -> List[Dict[str, Any]]:
        manifest = self._dataset_manifest()
        expected_revision = str(manifest.get("dataset", {}).get("revision", ""))
        dataset_dir = self._vendor_dataset_dir(vendor_dir)
        revision_file = dataset_dir / "REVISION"
        rows_file = dataset_dir / "canary24.jsonl"
        try:
            if revision_file.read_text().strip() != expected_revision:
                return []
            rows = []
            for line in rows_file.read_text().splitlines():
                if line.strip():
                    row = json.loads(line)
                    if not isinstance(row, dict):
                        return []
                    rows.append(row)
        except (OSError, json.JSONDecodeError):
            return []

        tasks = manifest.get("tasks")
        if not isinstance(tasks, list) or len(tasks) != self.task_count:
            return []
        expected_ids = [str(task.get("id")) for task in tasks]
        if [str(row.get("instance_id")) for row in rows] != expected_ids:
            return []
        if len(set(expected_ids)) != self.task_count:
            return []

        for task, row in zip(tasks, rows, strict=True):
            if self._canonical_row_hash(row) != task.get("row_sha256"):
                return []
            expected_fields = {
                "repo": task.get("repository"),
                "base_commit": task.get("base_commit"),
                "created_at": task.get("created_at"),
                "docker_image": task.get("source_image"),
            }
            if any(row.get(key) != value for key, value in expected_fields.items()):
                return []
            required = (
                "problem_statement",
                "patch",
                "test_patch",
                "log_parser",
                "FAIL_TO_PASS",
                "PASS_TO_PASS",
                "rebuild_cmds",
                "test_cmds",
                "print_cmds",
            )
            if any(field not in row for field in required):
                return []
        return rows

    def get_task_ids(self, vendor_dir: Path = None) -> List[str]:
        vendor_dir = Path(vendor_dir) if vendor_dir is not None else Path("vendor")
        rows = self._load_rows(vendor_dir)
        if len(rows) != self.task_count:
            return []
        return [str(row["instance_id"]) for row in rows]

    def _row_index(self, vendor_dir: Path) -> Dict[str, Dict[str, Any]]:
        return {
            str(row["instance_id"]): row for row in self._load_rows(vendor_dir)
        }

    @staticmethod
    def _safe_task_name(task_id: str) -> str:
        value = re.sub(r"[^a-z0-9._-]+", "-", task_id.lower()).strip("-.")
        return value or "task"

    @staticmethod
    def _instruction(row: Dict[str, Any]) -> str:
        problem = str(row.get("problem_statement") or "").strip()
        return (
            "Work only in the repository under /testbed. Resolve the issue "
            "described below. You may inspect and run the repository's existing "
            "tests and add development tests. Do not use public network access. "
            "An independent evaluator test patch will be applied only after you "
            "finish.\n\n"
            "# Issue\n\n"
            f"{problem}\n"
        )

    def _task_toml(self, task: Dict[str, Any]) -> str:
        runtime = self._dataset_manifest().get("runtime", {})
        image = f"{task['source_image']}@{task['docker_digest']}"
        name = f"swe-bench-live/{self._safe_task_name(str(task['id']))}"
        return (
            'schema_version = "1.3"\n'
            "artifacts = []\n\n"
            "[task]\n"
            f"name = {json.dumps(name)}\n\n"
            "[metadata]\n"
            f"language = {json.dumps(str(task['language']))}\n"
            f"repository = {json.dumps(str(task['repository']))}\n"
            f"base_commit = {json.dumps(str(task['base_commit']))}\n\n"
            "[verifier]\n"
            f"timeout_sec = {float(runtime.get('verifier_timeout_sec', 9000))}\n"
            'network_mode = "no-network"\n'
            "collect = []\n\n"
            "[verifier.env]\n\n"
            "[agent]\n"
            f"timeout_sec = {float(runtime.get('agent_timeout_sec', 1200))}\n"
            'network_mode = "allowlist"\n'
            "allowed_hosts = []\n\n"
            "[environment]\n"
            f"docker_image = {json.dumps(image)}\n"
            'network_mode = "public"\n'
            'os = "linux"\n'
            'workdir = "/testbed"\n'
            f"build_timeout_sec = {float(runtime.get('build_timeout_sec', 1800))}\n"
            f"cpus = {int(runtime.get('cpus', 4))}\n"
            f"memory_mb = {int(runtime.get('memory_mb', 16384))}\n"
            f"storage_mb = {int(runtime.get('storage_mb', 51200))}\n"
            "mcp_servers = []\n\n"
            "[environment.env]\n\n"
            "[solution.env]\n"
        )

    @staticmethod
    def _solution_script() -> str:
        return """#!/usr/bin/env bash
set -euo pipefail
cd /testbed
if [[ ! -d .git ]]; then
  git_dir=$(find . -maxdepth 3 -mindepth 2 -type d -name .git -print -quit)
  [[ -n "$git_dir" ]]
  cd "${git_dir%/.git}"
fi
git apply --whitespace=nowarn /solution/gold.patch
"""

    @staticmethod
    def _test_script() -> str:
        return """#!/usr/bin/env bash
set -uo pipefail
python_bin=$(command -v python3 || command -v python || true)
if [[ -z "$python_bin" ]]; then
  mkdir -p /logs/verifier
  printf '%s\n' '0' > /logs/verifier/reward.txt
  printf '%s\n' '{"resolved": false, "infrastructure_error": "python missing in task image"}' > /logs/verifier/evaluation.json
  exit 1
fi
export PYTHONNOUSERSITE=1
export PYTHONPATH=
"$python_bin" -I /tests/grader.py
"""

    def materialize_task(
        self,
        task_id: str,
        workdir: Path,
        vendor_dir: Path = None,
    ) -> Dict[str, Any]:
        vendor_dir = Path(vendor_dir) if vendor_dir is not None else Path("vendor")
        workdir = Path(workdir)
        task = self._task_index().get(task_id)
        row = self._row_index(vendor_dir).get(task_id)
        if task is None:
            raise ValueError(f"Unknown SWE-bench-Live canary task: {task_id}")
        if row is None:
            raise FileNotFoundError(
                f"Missing or invalid pinned SWE-bench-Live row: {task_id}"
            )

        if workdir.exists():
            shutil.rmtree(workdir)
        (workdir / "tests").mkdir(parents=True)
        (workdir / "solution").mkdir()
        # Harbor requires environment/ to exist even when task.toml points at
        # a prebuilt docker_image and the directory is intentionally empty.
        (workdir / "environment").mkdir()
        prompt = self._instruction(row)
        (workdir / "instruction.md").write_text(prompt)
        (workdir / "task.toml").write_text(self._task_toml(task))

        hidden_task = {
            "instance_id": task_id,
            "rebuild_cmds": row["rebuild_cmds"],
            "test_cmds": row["test_cmds"],
            "print_cmds": row["print_cmds"],
            "log_parser": row["log_parser"],
            "FAIL_TO_PASS": row["FAIL_TO_PASS"],
            "PASS_TO_PASS": row["PASS_TO_PASS"],
        }
        (workdir / "tests" / "task.json").write_text(
            json.dumps(hidden_task, ensure_ascii=False, indent=2) + "\n"
        )
        (workdir / "tests" / "test.patch").write_text(str(row["test_patch"]))
        grader_source = Path(__file__).with_name("swe_bench_live_grader.py")
        shutil.copy2(grader_source, workdir / "tests" / "grader.py")
        test_script = workdir / "tests" / "test.sh"
        test_script.write_text(self._test_script())
        test_script.chmod(0o755)

        (workdir / "solution" / "gold.patch").write_text(str(row["patch"]))
        solution_script = workdir / "solution" / "solve.sh"
        solution_script.write_text(self._solution_script())
        solution_script.chmod(0o755)

        manifest = self._dataset_manifest()
        return {
            "task_id": task_id,
            "prompt": prompt,
            "language": task.get("language"),
            "patch_bucket": task.get("patch_bucket"),
            "repository": task.get("repository"),
            "base_commit": task.get("base_commit"),
            "created_at": task.get("created_at"),
            "source_image": task.get("source_image"),
            "docker_digest": task.get("docker_digest"),
            "image_compressed_bytes": task.get("image_compressed_bytes"),
            "dataset_row_sha256": task.get("row_sha256"),
            "dataset_revision": manifest.get("dataset", {}).get("revision"),
            "evaluator_commit": manifest.get("evaluator", {}).get("commit"),
            "verifier_policy": manifest.get("evaluator", {}).get("policy"),
            "model_id": "nvidia/nemotron-3-ultra-550b-a55b",
        }

    def manifest_metadata(self, task_data: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "dataset_revision": task_data.get("dataset_revision"),
            "dataset_row_sha256": task_data.get("dataset_row_sha256"),
            "evaluator_commit": task_data.get("evaluator_commit"),
            "verifier_policy": task_data.get("verifier_policy"),
            "language": task_data.get("language"),
            "patch_bucket": task_data.get("patch_bucket"),
            "repository": task_data.get("repository"),
            "base_commit": task_data.get("base_commit"),
            "created_at": task_data.get("created_at"),
            "source_image": task_data.get("source_image"),
            "docker_digest": task_data.get("docker_digest"),
            "image_compressed_bytes": task_data.get("image_compressed_bytes"),
        }

    def _harbor_env(
        self,
        model_id: str | None = None,
        thinking: str | None = None,
    ) -> Dict[str, str]:
        env = super()._harbor_env(model_id, thinking=thinking)
        # Hidden tests are uploaded after agent.run(). Remove model-created
        # watchers before that upload, while preserving normal container daemons.
        env["CODING_EVAL_CLEAN_AGENT_PROCESSES"] = "1"
        return env

    @staticmethod
    def _verifier_is_offline(task_root: Path) -> bool:
        try:
            data = tomllib.loads((Path(task_root) / "task.toml").read_text())
        except (OSError, tomllib.TOMLDecodeError):
            return False
        return data.get("verifier", {}).get("network_mode") == "no-network"

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
                "stderr": "Hermetic SWE-bench-Live execution requires a model base URL.",
            }
        model_host = urlparse(base_url).hostname
        if not model_host:
            return {"returncode": -1, "stdout": "", "stderr": "Invalid model base URL"}
        if model_host in {"127.0.0.1", "::1", "localhost"} or self._is_ip_literal(
            model_host
        ):
            return {
                "returncode": -1,
                "stdout": "",
                "stderr": (
                    "Hermetic SWE-bench-Live execution requires a dedicated "
                    "container-reachable model relay hostname, not loopback or an IP literal."
                ),
            }
        if not (workdir / "task.toml").is_file():
            return {
                "returncode": -1,
                "stdout": "",
                "stderr": f"Missing materialized SWE-bench-Live task.toml in {workdir}",
            }
        if self._main_service_has_explicit_networking(workdir):
            return {
                "returncode": -1,
                "stdout": "",
                "stderr": "Task-authored main networking bypasses Harbor egress controls.",
            }
        if not self._verifier_is_offline(workdir):
            return {
                "returncode": -1,
                "stdout": "",
                "stderr": "SWE-bench-Live verifier must use no-network policy.",
            }
        if self._set_agent_network_allowlist(workdir, model_host) == 0:
            return {
                "returncode": -1,
                "stdout": "",
                "stderr": "Could not apply SWE-bench-Live agent network policy.",
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
            "--allow-agent-host",
            model_host,
            "--path",
            str(workdir),
            "--verifier-include-logs",
            "**/*",
            "--yes",
        ]
        devstack_mounts = self._devstack_mounts(adapter_name)
        if devstack_mounts:
            cmd += ["--mounts", json.dumps(devstack_mounts)]
        try:
            result = run_command(
                cmd,
                cwd=str(workdir),
                capture_output=True,
                text=True,
                timeout=14400,
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
                "stderr": "SWE-bench-Live Harbor job timed out",
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
        verdict = super().verify(task_data, workdir)
        jobs_dir = Path(workdir).parent / "jobs"
        evaluations = (
            list(jobs_dir.rglob("evaluation.json")) if jobs_dir.exists() else []
        )
        if not evaluations:
            return verdict
        evaluation_path = max(evaluations, key=self._path_mtime)
        evaluation = self._read_json(evaluation_path)
        if evaluation is None:
            return verdict
        verdict["native_evaluation"] = evaluation
        infrastructure_error = evaluation.get("infrastructure_error")
        if infrastructure_error:
            verdict.update(
                {
                    "passed": False,
                    "exit_code": -1,
                    "verifier_failed": True,
                    "grader_output": json.dumps(evaluation, indent=2),
                }
            )
        else:
            verdict["passed"] = bool(evaluation.get("resolved"))
            verdict["test_count"] = int(evaluation.get("observed_test_count", 0))
            verdict["grader_output"] = json.dumps(evaluation, indent=2)
        return verdict
