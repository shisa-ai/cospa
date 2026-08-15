"""Pinned FeatureBench Lite pilot through Harbor.

FeatureBench images contain an original repository under ``/root/my_repo``.
Cospa constructs the benchmark's masked agent workspace at image-build time,
keeps FAIL_TO_PASS tests and reference patches in Harbor's hidden phases, and
runs the pinned upstream pytest parser after verification.
"""

from __future__ import annotations

import hashlib
import json
import re
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any

from harness.suites.terminal_bench import PROJECT_ROOT, TerminalBenchSuite


PILOT_PATH = PROJECT_ROOT / "configs" / "ornith_runtime_pilot_v1.json"
IMAGE_LOCK_PATH = PROJECT_ROOT / "configs" / "ornith_runtime_pilot_images_v1.json"
LITE30_PATH = PROJECT_ROOT / "configs" / "featurebench_lite30_v1.json"
LITE30_IMAGE_LOCK_PATH = (
    PROJECT_ROOT / "configs" / "featurebench_lite30_images_v1.json"
)
PARETO12_PATH = PROJECT_ROOT / "configs" / "featurebench_lite_pareto12_v1.json"
PARETO12_IMAGE_LOCK_PATH = (
    PROJECT_ROOT / "configs" / "featurebench_lite_pareto12_images_v1.json"
)


_DATASET_READER = r'''
import json
import sys

import pandas as pd

featurebench_root, dataset_path, selected_json = sys.argv[1:]
sys.path.insert(0, featurebench_root)
from featurebench.harness.utils import preprocess_hf_patch

selected = set(json.loads(selected_json))
frame = pd.read_parquet(dataset_path)
rows = []
for raw in frame.to_dict(orient="records"):
    if raw["instance_id"] not in selected:
        continue
    row = {}
    for key, value in raw.items():
        if hasattr(value, "tolist"):
            value = value.tolist()
        row[key] = value
    row["FAIL_TO_PASS"] = list(row.get("FAIL_TO_PASS") or [])
    row["PASS_TO_PASS"] = list(row.get("PASS_TO_PASS") or [])
    row["repo_settings"] = json.loads(row.get("repo_settings") or "{}")
    row["level"] = int(row["instance_id"].rsplit(".lv", 1)[1])
    row["gold_patch"] = preprocess_hf_patch(
        row.get("patch") or "", row["FAIL_TO_PASS"]
    )
    rows.append(row)
print(json.dumps(rows))
'''.strip()


_PARSER_PROGRAM = r'''
import json
import sys

featurebench_root, repo = sys.argv[1:]
sys.path.insert(0, featurebench_root)
from featurebench.harness.test_parsers import MAP_REPO_TO_PARSER, parse_log_pytest

parser = MAP_REPO_TO_PARSER.get(repo, parse_log_pytest)
print(json.dumps(parser(sys.stdin.read())))
'''.strip()


def parse_featurebench_test_output(
    repo: str,
    output: str,
    vendor_dir: Path,
) -> dict[str, str]:
    """Parse pytest output with the pinned FeatureBench parser registry."""
    source_root = (Path(vendor_dir) / "featurebench").resolve()
    if not source_root.is_dir():
        raise FileNotFoundError(source_root)
    completed = subprocess.run(
        [sys.executable, "-c", _PARSER_PROGRAM, str(source_root), repo],
        input=output,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise ValueError(f"Pinned FeatureBench parser failed for {repo}: {detail}")
    try:
        parsed = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Pinned FeatureBench parser emitted invalid JSON for {repo}"
        ) from exc
    if not isinstance(parsed, dict):
        raise ValueError(f"Pinned FeatureBench parser returned non-object for {repo}")
    return {str(key): str(value) for key, value in parsed.items()}


def score_featurebench_result(
    *,
    f2p_status_maps: list[dict[str, str]],
    p2p_status_maps: list[dict[str, str]],
    f2p_exit_codes: list[int],
    p2p_exit_codes: list[int],
) -> dict[str, Any]:
    """Apply upstream binary resolution and F2P partial-score semantics."""

    def counts(status_maps: list[dict[str, str]]) -> tuple[int, int, int]:
        passed = 0
        failed = 0
        skipped = 0
        for status_map in status_maps:
            for status in status_map.values():
                if status in {"PASSED", "XFAIL"}:
                    passed += 1
                elif status in {"FAILED", "ERROR"}:
                    failed += 1
                else:
                    skipped += 1
        return passed, failed, skipped

    f2p_passed, f2p_failed, f2p_skipped = counts(f2p_status_maps)
    p2p_passed, p2p_failed, p2p_skipped = counts(p2p_status_maps)
    f2p_total = f2p_passed + f2p_failed
    resolved = (
        bool(f2p_exit_codes)
        and all(code == 0 for code in f2p_exit_codes)
        and all(code == 0 for code in p2p_exit_codes)
    )
    return {
        "passed": resolved,
        "test_count": f2p_total + p2p_passed + p2p_failed,
        "tests_passed": f2p_passed + p2p_passed,
        "f2p_test_count": f2p_total,
        "f2p_tests_passed": f2p_passed,
        "f2p_tests_failed": f2p_failed,
        "f2p_tests_skipped": f2p_skipped,
        "f2p_pass_rate": round(f2p_passed / f2p_total, 4) if f2p_total else 0.0,
        "p2p_test_count": p2p_passed + p2p_failed,
        "p2p_tests_passed": p2p_passed,
        "p2p_tests_failed": p2p_failed,
        "p2p_tests_skipped": p2p_skipped,
        "f2p_exit_codes": f2p_exit_codes,
        "p2p_exit_codes": p2p_exit_codes,
        "failure_class": "resolved" if resolved else "incorrect",
        "exit_code": 0,
    }


class FeatureBenchLitePilotSuite(TerminalBenchSuite):
    """Six-task, repository-distinct FeatureBench Lite runtime pilot."""

    name = "featurebench_lite_pilot6"
    version = "2026-08-15"
    task_count = 6
    verify_on_adapter_failure = True
    harbor_timeout_seconds = 14400

    def __init__(self) -> None:
        manifest = json.loads(PILOT_PATH.read_text())
        self.pilot = manifest["suites"]["featurebench_lite"]
        self.selected = {task["id"]: task for task in self.pilot["tasks"]}
        image_lock = json.loads(IMAGE_LOCK_PATH.read_text())
        self.image_lock = image_lock["images"]
        self._rows: dict[str, dict[str, Any]] | None = None

    def _dataset_path(self, vendor_dir: Path) -> Path:
        declared = Path(self.pilot["dataset"]["local_path"])
        if declared.parts and declared.parts[0] == "vendor":
            return Path(vendor_dir).joinpath(*declared.parts[1:])
        return PROJECT_ROOT / declared

    def _validated_dataset_path(self, vendor_dir: Path) -> Path | None:
        dataset_path = self._dataset_path(vendor_dir)
        if not dataset_path.is_file():
            return None
        observed = hashlib.sha256(dataset_path.read_bytes()).hexdigest()
        expected = self.pilot["dataset"]["sha256"]
        if observed != expected:
            raise ValueError(
                f"FeatureBench dataset checksum mismatch: {observed} != {expected}"
            )
        return dataset_path

    @staticmethod
    def _reader_python(vendor_dir: Path) -> Path:
        python = Path(vendor_dir) / "featurebench" / ".venv" / "bin" / "python"
        if not python.is_file():
            raise FileNotFoundError(
                "FeatureBench's pinned parquet reader is unavailable; run "
                "`uv sync --project vendor/featurebench`"
            )
        return python

    def _load_rows(self, vendor_dir: Path) -> dict[str, dict[str, Any]]:
        vendor_dir = Path(vendor_dir)
        dataset_path = self._validated_dataset_path(vendor_dir)
        if dataset_path is None:
            return {}
        if self._rows is None:
            completed = subprocess.run(
                [
                    str(self._reader_python(vendor_dir)),
                    "-c",
                    _DATASET_READER,
                    str((vendor_dir / "featurebench").resolve()),
                    str(dataset_path.resolve()),
                    json.dumps(list(self.selected)),
                ],
                capture_output=True,
                text=True,
                timeout=120,
            )
            if completed.returncode != 0:
                detail = completed.stderr.strip() or completed.stdout.strip()
                raise ValueError(f"Pinned FeatureBench dataset reader failed: {detail}")
            try:
                loaded = json.loads(completed.stdout)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    "Pinned FeatureBench dataset reader emitted invalid JSON"
                ) from exc
            self._rows = {row["instance_id"]: row for row in loaded}
        return self._rows

    def get_task_ids(self, vendor_dir: Path | None = None) -> list[str]:
        vendor_dir = Path(vendor_dir or PROJECT_ROOT / "vendor")
        rows = self._load_rows(vendor_dir)
        if not rows:
            return []
        missing = set(self.selected).difference(rows)
        if missing:
            raise ValueError(f"Missing selected FeatureBench tasks: {sorted(missing)}")
        return list(self.selected)

    @staticmethod
    def _runtime_config(row: dict[str, Any]) -> dict[str, Any]:
        settings = row.get("repo_settings") or {}
        run_args = (settings.get("docker_specs") or {}).get("run_args") or {}
        visible = run_args.get(
            "cuda_visible_num", run_args.get("cuda_visible_devices")
        )
        need_gpu = bool(visible)
        number_once = run_args.get("number_once", 1)
        if not isinstance(number_once, int) or number_once < 1:
            number_once = 1
        return {
            "need_gpu": need_gpu,
            "gpus": number_once if need_gpu else 0,
            "shm_size": run_args.get("shm_size"),
        }

    @staticmethod
    def _test_command(row: dict[str, Any]) -> str:
        settings = row.get("repo_settings") or {}
        command = settings.get("test_cmd") or (
            "pytest -rA -p no:cacheprovider --color=no"
        )
        if row.get("repo") == "pydantic/pydantic":
            command = "pytest -rA -v --color=no"
        timeout_one = settings.get("timeout_one")
        if isinstance(timeout_one, (int, float)) and timeout_one > 0:
            command = f"{command} --timeout={int(timeout_one)}"
        if settings.get("use_uv") and not command.lstrip().startswith("uv run"):
            command = f"uv run {command}"
        return command

    @staticmethod
    def _harbor_task_name(task_id: str) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", task_id.lower()).strip("-")
        digest = hashlib.sha256(task_id.encode()).hexdigest()[:10]
        return f"cospa/{slug[:80]}-{digest}"

    @classmethod
    def _task_toml(cls, task_id: str) -> str:
        return f'''schema_version = "1.1"

[task]
name = "{cls._harbor_task_name(task_id)}"
description = "Pinned FeatureBench Lite task"
authors = []
keywords = ["repository", "featurebench", "python"]

[verifier]
timeout_sec = 7800.0
network_mode = "no-network"

[agent]
timeout_sec = 3600.0
network_mode = "no-network"

[environment]
build_timeout_sec = 1800.0
cpus = 4
memory_mb = 32768
storage_mb = 51200
gpus = 0
network_mode = "public"
mcp_servers = []

[verifier.env]

[environment.env]

[solution.env]
'''

    @staticmethod
    def _baseline_script(row: dict[str, Any]) -> str:
        level = int(row["level"])
        lines = [
            "#!/usr/bin/env bash",
            "set -euo pipefail",
            "find /testbed -mindepth 1 -maxdepth 1 -exec rm -rf -- {} +",
        ]
        if level == 1:
            lines.extend(
                [
                    "cp -a /root/my_repo/. /testbed/",
                    "cd /testbed",
                    "git apply --whitespace=fix /opt/cospa/mask.patch",
                ]
            )
            for path in row["FAIL_TO_PASS"]:
                relative = str(path).removeprefix("/testbed/").lstrip("/")
                lines.append(f"rm -rf -- {shlex.quote(relative)}")
        else:
            lines.extend(
                [
                    "cd /testbed",
                    "printf '%s\\n' 'put all codes in this folder' > README.md",
                ]
            )
        lines.extend(
            [
                "find /testbed -type d \\( -name __pycache__ -o -name .pytest_cache "
                "-o -name .mypy_cache -o -name .ruff_cache -o -name .hypothesis \\) "
                "-prune -exec rm -rf -- {} +",
                "find /testbed -type f \\( -name '*.py[co]' -o -name '.coverage*' \\) -delete",
                "rm -rf .git",
                "git init -q",
                "git config user.email fb@bench.com",
                "git config user.name FeatureBench",
                "git add -A",
                "git commit -qm 'FeatureBench masked baseline' --allow-empty",
                "git config --global --add safe.directory /testbed",
                # The source image retains the unmasked repository here for
                # upstream evaluation setup. It is a reference artifact and
                # must not survive into the model-visible agent phase.
                "rm -rf -- /root/my_repo",
                "rm -f -- /opt/cospa/mask.patch /opt/cospa/baseline.sh",
            ]
        )
        return "\n".join(lines) + "\n"

    @classmethod
    def _verifier_script(cls, row: dict[str, Any]) -> str:
        level = int(row["level"])
        f2p_paths = [
            str(path).removeprefix("/testbed/").lstrip("/")
            for path in row["FAIL_TO_PASS"]
        ]
        p2p_paths = [
            str(path).removeprefix("/testbed/").lstrip("/")
            for path in row["PASS_TO_PASS"]
        ]
        command = cls._test_command(row)
        timeout_run = (row.get("repo_settings") or {}).get("timeout_run", 1800)
        try:
            timeout_run = max(1, int(timeout_run))
        except (TypeError, ValueError):
            timeout_run = 1800

        lines = [
            "#!/usr/bin/env bash",
            "set -uo pipefail",
            "mkdir -p /logs/verifier",
            "cd /testbed || exit 0",
            "git config --global --add safe.directory /testbed",
            "git add -N . >/dev/null 2>&1 || true",
            "git diff --binary HEAD > /logs/verifier/model.patch",
            "model_patch_applied=false",
            "test_patch_applied=false",
            "install_success=true",
            "setup_ready=false",
        ]
        if level == 1:
            lines.extend(
                [
                    "git reset --hard HEAD >/dev/null 2>&1",
                    "git clean -fd >/dev/null 2>&1",
                    "if [[ ! -s /logs/verifier/model.patch ]] || "
                    "git apply --whitespace=fix /logs/verifier/model.patch; then",
                    "  model_patch_applied=true",
                    "fi",
                ]
            )
            for path in f2p_paths:
                lines.append(f"rm -rf -- {shlex.quote(path)}")
            lines.extend(
                [
                    "if git apply --reverse --whitespace=fix /tests/test.patch; then",
                    "  test_patch_applied=true",
                    "fi",
                    "if [[ \"$model_patch_applied\" == true && "
                    "\"$test_patch_applied\" == true ]]; then",
                    "  setup_ready=true",
                    "fi",
                ]
            )
        else:
            lines.extend(
                [
                    "set +e",
                    "timeout -k 10 600s bash -lc "
                    + shlex.quote(
                        "source /opt/miniconda3/etc/profile.d/conda.sh && "
                        "conda activate testbed && cd /testbed && "
                        "pip install --no-deps ."
                    )
                    + " > /logs/verifier/install_output.txt 2>&1",
                    "install_exit_code=$?",
                    "set -e",
                    "if [[ $install_exit_code -eq 0 ]]; then install_success=true; "
                    "else install_success=false; fi",
                    "find /testbed -mindepth 1 -maxdepth 1 -exec rm -rf -- {} +",
                    "original_root=$(mktemp -d)",
                    "tar -xzf /tests/original-repo.tar.gz -C \"$original_root\"",
                    "cp -a \"$original_root/my_repo/.\" /testbed/",
                    "rm -rf -- \"$original_root\"",
                    "cd /testbed",
                    "if git apply --whitespace=fix /tests/test.patch; then",
                    "  test_patch_applied=true",
                    "fi",
                    "model_patch_applied=true",
                    "if [[ \"$install_success\" == true && "
                    "\"$test_patch_applied\" == true ]]; then",
                    "  setup_ready=true",
                    "fi",
                ]
            )

        f2p_vars = []
        p2p_vars = []
        shell_prefix = (
            "source /opt/miniconda3/etc/profile.d/conda.sh && "
            "conda activate testbed && cd /testbed && "
        )
        for kind, paths, variables in (
            ("f2p", f2p_paths, f2p_vars),
            ("p2p", p2p_paths if level == 1 else [], p2p_vars),
        ):
            for index, path in enumerate(paths):
                variable = f"{kind}_exit_{index}"
                variables.append(variable)
                test_command = f"{shell_prefix}{command} {shlex.quote('/testbed/' + path)}"
                lines.extend(
                    [
                        f"{variable}=-1",
                        "if [[ \"$setup_ready\" == true ]]; then",
                        "  set +e",
                        f"  timeout -k 10 {timeout_run}s bash -lc "
                        f"{shlex.quote(test_command)} "
                        f"> /logs/verifier/{kind}_{index}.txt 2>&1",
                        f"  {variable}=$?",
                        "  set -e",
                        "fi",
                    ]
                )

        f2p_json = ",".join(f'${{{name}}}' for name in f2p_vars)
        p2p_json = ",".join(f'${{{name}}}' for name in p2p_vars)
        lines.extend(
            [
                "printf '{\"level\":%s,\"model_patch_applied\":%s,"
                "\"test_patch_applied\":%s,\"install_success\":%s,"
                "\"f2p_exit_codes\":[%s],\"p2p_exit_codes\":[%s]}\\n' "
                f"{level} \"$model_patch_applied\" \"$test_patch_applied\" "
                f"\"$install_success\" \"{f2p_json}\" \"{p2p_json}\" "
                "> /logs/verifier/status.json",
                "echo 0 > /logs/verifier/reward.txt",
                "exit 0",
            ]
        )
        return "\n".join(lines) + "\n"

    @staticmethod
    def _write_hidden_original_archive(image_ref: str, destination: Path) -> None:
        """Export Level 2's original repo into Harbor's hidden test phase."""
        destination = Path(destination)
        try:
            with destination.open("wb") as output:
                completed = subprocess.run(
                    [
                        "docker",
                        "run",
                        "--rm",
                        "--network",
                        "none",
                        "--entrypoint",
                        "tar",
                        image_ref,
                        "-C",
                        "/root",
                        "-czf",
                        "-",
                        "my_repo",
                    ],
                    stdout=output,
                    stderr=subprocess.PIPE,
                    timeout=1800,
                )
        except Exception:
            destination.unlink(missing_ok=True)
            raise
        if completed.returncode != 0 or not destination.is_file() or not destination.stat().st_size:
            destination.unlink(missing_ok=True)
            detail = completed.stderr.decode(errors="replace").strip()
            raise ValueError(
                f"Could not export hidden FeatureBench Level 2 repository: {detail}"
            )

    def materialize_task(
        self,
        task_id: str,
        workdir: Path,
        vendor_dir: Path | None = None,
    ) -> dict[str, Any]:
        vendor_dir = Path(vendor_dir or PROJECT_ROOT / "vendor")
        rows = self._load_rows(vendor_dir)
        if task_id not in self.selected or task_id not in rows:
            raise ValueError(f"Unknown selected FeatureBench task: {task_id}")
        row = rows[task_id]
        selected = self.selected[task_id]
        mutable_image = selected["image_ref"]
        image_ref = self.image_lock[mutable_image]["pinned_ref"]
        if row["image_name"] != mutable_image:
            raise ValueError(f"FeatureBench image mismatch for {task_id}")

        workdir = Path(workdir)
        for directory in ("environment", "tests", "solution"):
            (workdir / directory).mkdir(parents=True, exist_ok=True)

        level_context = (
            "The masked repository is at `/testbed`; make all solution changes "
            "there."
            if row["level"] == 1
            else "A blank implementation workspace is at `/testbed`; create the "
            "requested package there."
        )
        prompt = (
            "# Benchmark execution context\n\n"
            f"- Task ID: `{task_id}`\n"
            f"- Repository: `{row['repo']}`\n"
            f"- {level_context}\n"
            "- Hidden tests and reference artifacts are unavailable during the "
            "agent phase.\n"
            "- Solve only from this specification and the visible workspace.\n\n"
            + str(row["problem_statement"]).strip()
            + "\n"
        )
        (workdir / "instruction.md").write_text(prompt)
        runtime = self._runtime_config(row)
        # Harbor 0.16's local Docker environment rejects task-level GPU
        # allocation even when the NVIDIA container runtime works. Keep the
        # scheduler-visible request at zero and use a task-authored Compose
        # override for passthrough on rows whose pinned upstream settings need
        # CUDA. Mechanical qualification records this compatibility policy.
        (workdir / "task.toml").write_text(self._task_toml(task_id))
        environment = workdir / "environment"
        if runtime["need_gpu"]:
            (environment / "docker-compose.yaml").write_text(
                "services:\n"
                "  main:\n"
                "    gpus: all\n"
            )
        (environment / "mask.patch").write_text(row.get("patch") or "")
        baseline_script = environment / "baseline.sh"
        baseline_script.write_text(self._baseline_script(row))
        baseline_script.chmod(0o755)
        (environment / "Dockerfile").write_text(
            f"FROM {image_ref}\n"
            "USER root\n"
            "COPY mask.patch /opt/cospa/mask.patch\n"
            "COPY baseline.sh /opt/cospa/baseline.sh\n"
            "RUN bash /opt/cospa/baseline.sh\n"
            "WORKDIR /testbed\n"
        )
        (workdir / "tests" / "test.patch").write_text(row["test_patch"])
        if row["level"] == 2:
            self._write_hidden_original_archive(
                image_ref,
                workdir / "tests" / "original-repo.tar.gz",
            )
        test_script = workdir / "tests" / "test.sh"
        test_script.write_text(self._verifier_script(row))
        test_script.chmod(0o755)
        (workdir / "solution" / "gold.patch").write_text(row["gold_patch"])
        solution_script = workdir / "solution" / "solve.sh"
        if row["level"] == 1 and row["gold_patch"].strip():
            solution_script.write_text(
                "#!/usr/bin/env bash\nset -euo pipefail\ncd /testbed\n"
                "git apply --whitespace=fix /solution/gold.patch\n"
            )
        else:
            solution_script.write_text(
                "#!/usr/bin/env bash\n"
                "echo 'FeatureBench Level 2 has no released gold patch' >&2\n"
                "exit 2\n"
            )
        solution_script.chmod(0o755)

        return {
            "task_id": task_id,
            "harbor_task_name": self._harbor_task_name(task_id),
            "problem": task_id,
            "prompt": prompt,
            "problem_statement": row["problem_statement"],
            "repository": row["repo"],
            "level": row["level"],
            "base_commit": row["base_commit"],
            "image_ref": image_ref,
            "fail_to_pass": row["FAIL_TO_PASS"][0],
            "fail_to_pass_paths": row["FAIL_TO_PASS"],
            "pass_to_pass_paths": row["PASS_TO_PASS"],
            "runtime": runtime,
            "vendor_dir": str(vendor_dir),
        }

    def manifest_metadata(self, task_data: dict[str, Any]) -> dict[str, Any]:
        return {
            "protocol": "featurebench_hidden_tests_harbor",
            "source_revision": self.pilot["source"]["revision"],
            "dataset_revision": self.pilot["dataset"]["revision"],
            "dataset_sha256": self.pilot["dataset"]["sha256"],
            "image_ref": task_data["image_ref"],
            "repository": task_data["repository"],
            "language": "python",
            "level": task_data["level"],
            "base_commit": task_data["base_commit"],
            "verifier": "featurebench_pinned_upstream_parser",
            "verifier_network": "no-network",
            "f2p_partial_diagnostic": "task_f2p_pass_rate",
            "gpu_requirement": task_data["runtime"],
            "gpu_passthrough": (
                "task_compose_all"
                if task_data["runtime"]["need_gpu"]
                else "not_required"
            ),
        }

    @staticmethod
    def _verifier_failure(message: str) -> dict[str, Any]:
        return {
            "passed": False,
            "test_count": 0,
            "grader_output": message,
            "exit_code": -1,
            "verifier_failed": True,
            "failure_class": "verifier_failed",
        }

    def verify(self, task_data: dict[str, Any], workdir: Path) -> dict[str, Any]:
        jobs_dir = Path(workdir).parent / "jobs"
        status_files = sorted(
            jobs_dir.rglob("status.json"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        if not status_files:
            return self._verifier_failure("Missing Harbor verifier status")
        artifact_dir = status_files[0].parent
        patch_file = artifact_dir / "model.patch"
        if not patch_file.is_file():
            return self._verifier_failure("Missing Harbor model patch artifact")
        try:
            status = json.loads(status_files[0].read_text())
        except (OSError, json.JSONDecodeError) as exc:
            return self._verifier_failure(f"Invalid Harbor verifier status: {exc}")
        if status.get("test_patch_applied") is not True:
            return self._verifier_failure("Hidden FeatureBench test patch failed")
        if status.get("model_patch_applied") is not True:
            return {
                "passed": False,
                "test_count": 0,
                "grader_output": "Model patch failed to replay",
                "exit_code": 1,
                "failure_class": "incorrect",
                "model_patch_applied": False,
                "model_patch_bytes": len(patch_file.read_bytes()),
            }
        if int(task_data["level"]) == 2 and status.get("install_success") is not True:
            return {
                "passed": False,
                "test_count": 0,
                "grader_output": "FeatureBench Level 2 package installation failed",
                "exit_code": 1,
                "failure_class": "incorrect",
                "model_patch_bytes": len(patch_file.read_bytes()),
            }

        f2p_exit_codes = list(status.get("f2p_exit_codes") or [])
        p2p_exit_codes = list(status.get("p2p_exit_codes") or [])
        if len(f2p_exit_codes) != len(task_data["fail_to_pass_paths"]):
            return self._verifier_failure("Incomplete FeatureBench F2P artifacts")
        if len(p2p_exit_codes) != len(task_data["pass_to_pass_paths"]):
            return self._verifier_failure("Incomplete FeatureBench P2P artifacts")

        try:
            f2p_outputs = [
                (artifact_dir / f"f2p_{index}.txt").read_text(errors="replace")
                for index in range(len(f2p_exit_codes))
            ]
            p2p_outputs = [
                (artifact_dir / f"p2p_{index}.txt").read_text(errors="replace")
                for index in range(len(p2p_exit_codes))
            ]
            f2p_maps = [
                parse_featurebench_test_output(
                    task_data["repository"], output, Path(task_data["vendor_dir"])
                )
                for output in f2p_outputs
            ]
            p2p_maps = [
                parse_featurebench_test_output(
                    task_data["repository"], output, Path(task_data["vendor_dir"])
                )
                for output in p2p_outputs
            ]
        except Exception as exc:
            return self._verifier_failure(f"Pinned FeatureBench parser failed: {exc}")

        verdict = score_featurebench_result(
            f2p_status_maps=f2p_maps,
            p2p_status_maps=p2p_maps,
            f2p_exit_codes=[int(code) for code in f2p_exit_codes],
            p2p_exit_codes=[int(code) for code in p2p_exit_codes],
        )
        verdict["grader_output"] = "\n\n".join(f2p_outputs + p2p_outputs)
        verdict["model_patch_bytes"] = len(patch_file.read_bytes())
        verdict["model_patch_applied"] = True
        verdict["test_patch_applied"] = True
        return verdict


class FeatureBenchLiteCandidateSuite(FeatureBenchLitePilotSuite):
    """Official outcome-blind Lite30 rows for mechanical qualification."""

    name = "featurebench_lite30_candidate"
    task_count = 30
    panel_path = LITE30_PATH
    image_lock_path = LITE30_IMAGE_LOCK_PATH

    def __init__(self) -> None:
        self.panel = json.loads(self.panel_path.read_text())
        self.pilot = self.panel
        self.selected = {
            task["task_id"]: {
                "id": task["task_id"],
                "image_ref": task["image_ref"],
                "repository": task["repository"],
                "level": task["level"],
            }
            for task in self.panel["tasks"]
        }
        image_lock = json.loads(self.image_lock_path.read_text())
        self.image_lock = image_lock["images"]
        missing_images = {
            task["image_ref"]
            for task in self.panel["tasks"]
            if task["image_ref"] not in self.image_lock
        }
        if missing_images:
            raise ValueError(
                f"Missing FeatureBench Lite30 image pins: {sorted(missing_images)}"
            )
        self._rows = None

    def manifest_metadata(self, task_data: dict[str, Any]) -> dict[str, Any]:
        metadata = super().manifest_metadata(task_data)
        metadata.update(
            {
                "panel": self.panel["name"],
                "panel_version": self.panel["version"],
                "panel_size": self.task_count,
                "panel_selection": self.panel["selection"],
                "panel_qualification": self.panel["qualification"],
            }
        )
        return metadata


class FeatureBenchLitePareto12Suite(FeatureBenchLiteCandidateSuite):
    """Repeat-qualified, repository-diverse FeatureBench Lite panel."""

    name = "featurebench_lite_pareto12"
    version = "2026-08-15"
    task_count = 12
    panel_path = PARETO12_PATH
    image_lock_path = PARETO12_IMAGE_LOCK_PATH
