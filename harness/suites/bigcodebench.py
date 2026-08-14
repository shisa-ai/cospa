"""Pinned BigCodeBench-Hard Instruct pilot suite.

Public prompts are frozen in a committed spec. Hidden tests and canonical
solutions remain only in the pinned parquet and are mounted into the verifier
container after generation has finished.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SPEC_PATH = ROOT / "configs" / "bigcodebench_hard_instruct_pilot15.json"
IMAGE_LOCK_PATH = ROOT / "configs" / "ornith_runtime_pilot_images_v1.json"
IMAGE_TAG = "bigcodebench/bigcodebench-evaluate:latest"


def evaluation_counts(details: Any) -> dict[str, int]:
    """Return honest diagnostics for both upstream details schemas."""
    if isinstance(details, list):
        return {
            "test_count": len(details),
            "tests_passed": sum(value is True for value in details),
        }
    if isinstance(details, dict):
        # BigCodeBench 0.2.4 emits only failed test names and tracebacks, so
        # neither the total test count nor the passed count can be inferred.
        return {"test_count": 0, "failed_test_count": len(details)}
    return {"test_count": 0}


def groundtruth_pass_rate(output: str) -> float | None:
    """Extract the evaluator's reported ground-truth pass rate."""
    match = re.search(r"Groundtruth pass rate:\s*([0-9]+(?:\.[0-9]+)?)", output)
    return float(match.group(1)) if match else None


VERIFY_SCRIPT = r"""
import json
import os
import sys
import pyarrow.parquet as pq

rows = pq.read_table('/input/dataset.parquet').to_pylist()
dataset_path = '/tmp/bigcodebench-hard.jsonl'
with open(dataset_path, 'w') as output:
    for row in rows:
        output.write(json.dumps(row) + '\n')
os.environ['BIGCODEBENCH_OVERRIDE_PATH'] = dataset_path

from bigcodebench.sanitize import sanitize
from bigcodebench.evaluate import evaluate

with open('/work/raw-sample.jsonl') as source:
    sample = json.loads(source.readline())
solution = sanitize(sample['raw_solution'], sys.argv[1])
samples_path = '/work/sample-sanitized.jsonl'
with open(samples_path, 'w') as output:
    output.write(json.dumps({'task_id': sample['task_id'], 'solution': solution}) + '\n')

evaluate(
    split=sys.argv[3],
    subset=sys.argv[4],
    samples=samples_path,
    execution='local',
    selective_evaluate=sys.argv[2],
    pass_k=[1],
    save_pass_rate=False,
    calibrated=True,
    parallel=1,
)
""".strip()


class BigCodeBenchHardInstructSuite:
    """Fifteen-task, one-sample BigCodeBench-Hard Instruct runtime pilot."""

    name = "bigcodebench_hard_instruct"
    version = "0.1"

    def __init__(self) -> None:
        self.spec = json.loads(SPEC_PATH.read_text())
        self.protocol = self.spec["protocol"]
        self.tasks = {task["task_id"]: task for task in self.spec["tasks"]}
        lock = json.loads(IMAGE_LOCK_PATH.read_text())
        self.verifier_image = lock["images"][IMAGE_TAG]["pinned_ref"]

    def _dataset_path(self, vendor_dir: Path) -> Path:
        declared = Path(self.spec["source_dataset"]["local_path"])
        if declared.parts and declared.parts[0] == "vendor":
            return Path(vendor_dir).joinpath(*declared.parts[1:])
        return ROOT / declared

    def _validated_dataset_path(self, vendor_dir: Path) -> Path | None:
        dataset = self._dataset_path(Path(vendor_dir))
        if not dataset.is_file():
            return None
        observed = hashlib.sha256(dataset.read_bytes()).hexdigest()
        expected = self.spec["source_dataset"]["sha256"]
        if observed != expected:
            raise ValueError(
                f"BigCodeBench dataset checksum mismatch: {observed} != {expected}"
            )
        return dataset

    def get_task_ids(self, vendor_dir: Path | None = None) -> list[str]:
        vendor_dir = Path(vendor_dir or ROOT / "vendor")
        if self._validated_dataset_path(vendor_dir) is None:
            return []
        return list(self.tasks)

    def materialize_task(
        self,
        task_id: str,
        workdir: Path,
        vendor_dir: Path | None = None,
    ) -> dict[str, Any]:
        vendor_dir = Path(vendor_dir or ROOT / "vendor")
        dataset_path = self._validated_dataset_path(vendor_dir)
        if dataset_path is None:
            raise FileNotFoundError(self._dataset_path(vendor_dir))
        if task_id not in self.tasks:
            raise ValueError(f"Unknown BigCodeBench pilot task: {task_id}")

        public = self.tasks[task_id]
        prefix = self.protocol["instruction_prefix"]
        prompt = f"{prefix}\n{public['instruct_prompt'].strip()}"
        workdir = Path(workdir)
        workdir.mkdir(parents=True, exist_ok=True)
        (workdir / "prompt.txt").write_text(prompt + "\n")
        return {
            "task_id": task_id,
            "problem": task_id.replace("/", "_"),
            "prompt": prompt,
            "entry_point": public["entry_point"],
            "dataset_path": str(dataset_path),
            "required_adapter": "bigcodebench_openai",
            "tool_call_parser": "not_applicable_no_tools",
            "temperature": self.protocol["temperature"],
            "top_p": self.protocol["top_p"],
            "top_k": "not_sent",
            "max_tokens": self.protocol["max_completion_tokens"],
            "thinking_policy": "not_applicable",
            "sampling_source": "bigcodebench_hard_instruct_protocol",
            "sampling_rationale": (
                "Pinned upstream greedy single-sample Instruct protocol"
            ),
            "timeout": 600,
        }

    def manifest_metadata(self, task_data: dict[str, Any]) -> dict[str, Any]:
        source = self.spec["source_dataset"]
        return {
            "protocol": "bigcodebench_hard_instruct_single_generation",
            "source_revision": self.spec["source_harness"]["revision"],
            "dataset_revision": source["revision"],
            "dataset_sha256": source["sha256"],
            "verifier_image": self.verifier_image,
            "split": self.protocol["split"],
            "subset": self.protocol["subset"],
            "samples_per_task": self.protocol["samples_per_task"],
            "calibrated": self.protocol["calibrated"],
            "tools_enabled": False,
            "request_overrides": task_data.get("request_overrides", {}),
        }

    def _docker_prefix(self, task_data: dict[str, Any], workdir: Path) -> list[str]:
        dataset_path = Path(task_data["dataset_path"]).resolve()
        workdir = Path(workdir).resolve()
        return [
            "docker",
            "run",
            "--rm",
            "--network",
            "none",
            "--cpus",
            "2",
            "--memory",
            "8g",
            "--pids-limit",
            "512",
            "--security-opt",
            "no-new-privileges:true",
            "--user",
            f"{os.getuid()}:{os.getgid()}",
            "--env",
            "HOME=/tmp",
            "--volume",
            f"{dataset_path}:/input/dataset.parquet:ro",
            "--volume",
            f"{workdir}:/work",
        ]

    def verify(self, task_data: dict[str, Any], workdir: Path) -> dict[str, Any]:
        """Verify one completion and never retain the hidden dataset export."""
        workdir = Path(workdir)
        try:
            return self._verify(task_data, workdir)
        finally:
            (workdir / "dataset.jsonl").unlink(missing_ok=True)

    def _verify(self, task_data: dict[str, Any], workdir: Path) -> dict[str, Any]:
        raw_sample = workdir / "raw-sample.jsonl"
        if not raw_sample.is_file():
            return {
                "passed": False,
                "test_count": 0,
                "grader_output": "Missing raw-sample.jsonl",
                "exit_code": -1,
                "verifier_failed": True,
                "failure_class": "verifier_failed",
            }

        for generated_name in (
            "sample-sanitized.jsonl",
            "sample-sanitized_eval_results.json",
            "sample-sanitized_pass_at_k.json",
        ):
            (workdir / generated_name).unlink(missing_ok=True)

        command = self._docker_prefix(task_data, workdir) + [
            "--entrypoint",
            "python",
            self.verifier_image,
            "-c",
            VERIFY_SCRIPT,
            task_data["entry_point"],
            task_data["task_id"],
            self.protocol["split"],
            self.protocol["subset"],
        ]
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=900,
            )
        except Exception as exc:
            return {
                "passed": False,
                "test_count": 0,
                "grader_output": f"Verifier container raised: {exc}",
                "exit_code": -1,
                "verifier_failed": True,
                "failure_class": "verifier_failed",
            }
        outputs = [part for part in (result.stdout, result.stderr) if part]
        if result.returncode != 0:
            return {
                "passed": False,
                "test_count": 0,
                "grader_output": "\n".join(outputs),
                "exit_code": result.returncode,
                "verifier_failed": True,
                "failure_class": "verifier_failed",
            }

        results_path = workdir / "sample-sanitized_eval_results.json"
        try:
            results = json.loads(results_path.read_text())
            evaluations = results["eval"][task_data["task_id"]]
            if len(evaluations) != 1:
                raise ValueError(f"Expected one evaluation, found {len(evaluations)}")
            evaluation = evaluations[0]
            details = evaluation.get("details") or []
            passed = evaluation.get("status") == "pass"
        except Exception as exc:
            return {
                "passed": False,
                "test_count": 0,
                "grader_output": f"Invalid evaluator output: {exc}\n" + "\n".join(outputs),
                "exit_code": -1,
                "verifier_failed": True,
                "failure_class": "verifier_failed",
            }

        grader_output = "\n".join(outputs)
        gt_rate = groundtruth_pass_rate(grader_output)
        if gt_rate is None or gt_rate < 0.99:
            return {
                "passed": False,
                "test_count": 0,
                "grader_output": (
                    f"Ground-truth validity gate failed: {gt_rate}\n" + grader_output
                ),
                "exit_code": -1,
                "verifier_failed": True,
                "failure_class": "verifier_failed",
                "groundtruth_pass_rate": gt_rate,
            }

        return {
            "passed": passed,
            **evaluation_counts(details),
            "grader_output": grader_output,
            "exit_code": 0,
            "failure_class": "resolved" if passed else "incorrect",
            "upstream_status": evaluation.get("status"),
            "groundtruth_pass_rate": gt_rate,
            "details": details,
        }


AGENTIC_SOLUTION_FILE = "solution.py"
AGENTIC_STARTER_SOLUTION = (
    "# Implement the complete self-contained Python solution below.\n"
)


class BigCodeBenchHardAgenticSuite(BigCodeBenchHardInstructSuite):
    """BigCodeBench-Hard tasks adapted to Cospa's scaffold comparison."""

    name = "bigcodebench_hard_agentic"
    version = "0.1"

    def materialize_task(
        self,
        task_id: str,
        workdir: Path,
        vendor_dir: Path | None = None,
    ) -> dict[str, Any]:
        task_data = super().materialize_task(task_id, workdir, vendor_dir)
        public_prompt = self.tasks[task_id]["instruct_prompt"].strip()
        prompt = (
            "Work in the provided workspace and implement the complete "
            "self-contained Python solution in `solution.py`. Only the contents "
            "of `solution.py` will be submitted to the native evaluator; do not "
            "only describe the answer in chat. You may inspect and execute your "
            "own visible files, but hidden tests and reference solutions are "
            "unavailable.\n\nPublic task:\n"
            f"{public_prompt}"
        )
        workdir = Path(workdir)
        (workdir / "prompt.txt").write_text(prompt + "\n")
        (workdir / AGENTIC_SOLUTION_FILE).write_text(AGENTIC_STARTER_SOLUTION)

        task_data.update(
            {
                "prompt": prompt,
                "problem": task_id.replace("/", "_"),
                "solution_file": AGENTIC_SOLUTION_FILE,
                "timeout": 1800,
            }
        )
        for key in (
            "required_adapter",
            "tool_call_parser",
            "temperature",
            "top_p",
            "top_k",
            "max_tokens",
            "thinking_policy",
            "sampling_source",
            "sampling_rationale",
        ):
            task_data.pop(key, None)
        return task_data

    def manifest_metadata(self, task_data: dict[str, Any]) -> dict[str, Any]:
        metadata = super().manifest_metadata(task_data)
        metadata.update(
            {
                "protocol": "bigcodebench_hard_agentic_workspace",
                "tools_enabled": True,
                "solution_file": AGENTIC_SOLUTION_FILE,
                "scaffold_comparison": True,
                "request_overrides": {},
            }
        )
        return metadata

    def verify(self, task_data: dict[str, Any], workdir: Path) -> dict[str, Any]:
        workdir = Path(workdir)
        solution_path = workdir / task_data.get(
            "solution_file", AGENTIC_SOLUTION_FILE
        )
        try:
            solution = solution_path.read_text()
        except OSError as exc:
            return {
                "passed": False,
                "test_count": 0,
                "grader_output": f"Missing agentic solution file: {exc}",
                "exit_code": 1,
                "failure_class": "incorrect",
            }
        if not solution.strip() or solution.strip() == AGENTIC_STARTER_SOLUTION.strip():
            return {
                "passed": False,
                "test_count": 0,
                "grader_output": "Agent left the solution file unchanged",
                "exit_code": 1,
                "failure_class": "incorrect",
            }

        (workdir / "raw-sample.jsonl").write_text(
            json.dumps(
                {
                    "task_id": task_data["task_id"],
                    "raw_solution": solution,
                }
            )
            + "\n"
        )
        return super().verify(task_data, workdir)
