"""SWE-PolyBench Verified pilot through pinned images and Harbor.

The Harbor agent edits the base repository inside the selected immutable image.
Hidden tests and the gold patch are mounted only in Harbor's verifier/solution
phases. Cospa parses the upstream test log after Harbor completes.
"""

from __future__ import annotations

import ast
import csv
import hashlib
import json
import re
import shlex
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

from harness.suites.terminal_bench import PROJECT_ROOT, TerminalBenchSuite


PILOT_PATH = PROJECT_ROOT / "configs" / "ornith_runtime_pilot_v1.json"
IMAGE_LOCK_PATH = PROJECT_ROOT / "configs" / "ornith_runtime_pilot_images_v1.json"
BALANCED_CANDIDATE96_PATH = (
    PROJECT_ROOT / "configs" / "swe_polybench_balanced_candidate96_v1.json"
)
BALANCED_IMAGE_LOCK_PATH = (
    PROJECT_ROOT / "configs" / "swe_polybench_balanced_candidate96_images_v1.json"
)
BALANCED_JAVA_EXTENSION32_PATH = (
    PROJECT_ROOT / "configs" / "swe_polybench_balanced_java_extension32_v1.json"
)
BALANCED_JAVA_IMAGE_LOCK_PATH = (
    PROJECT_ROOT
    / "configs"
    / "swe_polybench_balanced_java_extension32_images_v1.json"
)
BALANCED_JAVA_STRATA_EXTENSION7_PATH = (
    PROJECT_ROOT
    / "configs"
    / "swe_polybench_balanced_java_strata_extension7_v1.json"
)
BALANCED_JAVA_STRATA_IMAGE_LOCK_PATH = (
    PROJECT_ROOT
    / "configs"
    / "swe_polybench_balanced_java_strata_extension7_images_v1.json"
)
BALANCED64_PATH = (
    PROJECT_ROOT / "configs" / "swe_polybench_verified_balanced64_v1.json"
)
BALANCED64_IMAGE_LOCK_PATH = (
    PROJECT_ROOT
    / "configs"
    / "swe_polybench_verified_balanced64_images_v1.json"
)
_CSV_FIELD_SIZE_LOCK = threading.Lock()
_SUBMODULE_STATE_PIPELINE = (
    "git submodule foreach --recursive --quiet "
    "'printf \"%s\\n\" \"$displaypath\"; git rev-parse HEAD; "
    "git ls-files -co --exclude-standard -z "
    "| LC_ALL=C sort -z | xargs -0r sha256sum'"
)


def parse_polybench_test_output(
    repo: str,
    output: str,
    vendor_dir: Path,
) -> dict[str, Any]:
    """Parse one test log with the pinned upstream repository parser.

    The upstream package ``__init__`` eagerly imports its Docker evaluator and
    large optional dependencies. Load only the pinned parser namespace in an
    isolated subprocess, which is also safe when trial verification is
    concurrent.
    """
    package_root = (
        Path(vendor_dir) / "swe-polybench" / "src" / "poly_bench_evaluation"
    ).resolve()
    if not package_root.is_dir():
        raise FileNotFoundError(package_root)

    parser_program = r'''
import importlib
import json
import sys
import types

package_root, repo = sys.argv[1:]
package = types.ModuleType("poly_bench_evaluation")
package.__package__ = "poly_bench_evaluation"
package.__path__ = [package_root]
sys.modules["poly_bench_evaluation"] = package
constants = importlib.import_module("poly_bench_evaluation.constants")
parsers = importlib.import_module("poly_bench_evaluation.parsers")
parser_name = constants.REPO_TO_PARSER_CLASS.get(repo)
if not parser_name or not hasattr(parsers, parser_name):
    raise ValueError(f"No pinned SWE-PolyBench parser for {repo}")
parsed = getattr(parsers, parser_name)(test_content=sys.stdin.read()).parse()
print(json.dumps(parsed))
'''
    # Upstream parsers receive DockerManager logs, which always add this
    # sentinel after command output. Harbor exposes raw verifier stdout, and
    # several JSON parsers otherwise truncate the final byte while searching
    # for that boundary. Recreate only the runner framing, not test content.
    parser_output = output
    if "Container exited with status code:" not in parser_output:
        parser_output = (
            parser_output.rstrip("\n")
            + "\nContainer exited with status code: unknown\n"
        )

    completed = subprocess.run(
        [sys.executable, "-c", parser_program, str(package_root), repo],
        input=parser_output,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise ValueError(f"Pinned SWE-PolyBench parser failed for {repo}: {detail}")
    try:
        parsed = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Pinned SWE-PolyBench parser emitted invalid JSON for {repo}"
        ) from exc
    if not isinstance(parsed, dict):
        raise ValueError(f"Pinned SWE-PolyBench parser returned non-object for {repo}")
    return parsed


def score_polybench_result(
    parsed: dict[str, Any],
    *,
    f2p: list[str],
    p2p: list[str],
) -> dict[str, Any]:
    """Apply upstream F2P/P2P resolved semantics to a parsed test log."""
    passed_tests = list(parsed.get("passed_tests") or [])
    failed_tests = list(parsed.get("failed_tests") or [])
    passed_set = set(passed_tests)
    failed_set = set(failed_tests)
    all_f2p_passed = set(f2p).issubset(passed_set)
    no_p2p_failed = not set(p2p).intersection(failed_set)
    resolved = all_f2p_passed and no_p2p_failed
    return {
        "passed": resolved,
        "test_count": len(passed_tests) + len(failed_tests),
        "tests_passed": len(passed_tests),
        "all_f2p_passed": all_f2p_passed,
        "no_p2p_failed": no_p2p_failed,
        "passed_tests": passed_tests,
        "failed_tests": failed_tests,
        "failure_class": "resolved" if resolved else "incorrect",
        "exit_code": 0,
    }


class SwePolyBenchVerifiedSuite(TerminalBenchSuite):
    """Repeat-qualified 28-task SWE-PolyBench Verified runtime pilot."""

    name = "swe_polybench_verified"
    version = "0.2"
    task_count = 28
    verify_on_adapter_failure = True

    def __init__(self) -> None:
        pilot = json.loads(PILOT_PATH.read_text())
        self.pilot = pilot["suites"][self.name]
        self.selected = {task["id"]: task for task in self.pilot["tasks"]}
        self.image_lock = json.loads(IMAGE_LOCK_PATH.read_text())["images"]
        self._rows: dict[str, dict[str, str]] | None = None

    def _dataset_path(self, vendor_dir: Path) -> Path:
        declared = Path(self.pilot["dataset"]["local_path"])
        return Path(vendor_dir).joinpath(*declared.parts[1:])

    def _load_rows(self, vendor_dir: Path) -> dict[str, dict[str, str]]:
        dataset_path = self._dataset_path(vendor_dir)
        if not dataset_path.is_file():
            return {}
        actual = hashlib.sha256(dataset_path.read_bytes()).hexdigest()
        expected = self.pilot["dataset"]["sha256"]
        if actual != expected:
            raise ValueError(f"SWE-PolyBench dataset checksum mismatch: {actual}")
        if self._rows is None:
            # csv.field_size_limit is process-global. Hold the lock through
            # parsing so concurrent verifier workers cannot restore the small
            # default while another reader is still consuming this 12 MB CSV.
            with _CSV_FIELD_SIZE_LOCK:
                previous_limit = csv.field_size_limit()
                try:
                    csv.field_size_limit(
                        max(previous_limit, dataset_path.stat().st_size)
                    )
                    with dataset_path.open(newline="") as handle:
                        self._rows = {
                            row["instance_id"]: row
                            for row in csv.DictReader(handle)
                        }
                finally:
                    csv.field_size_limit(previous_limit)
        return self._rows

    def get_task_ids(self, vendor_dir: Path | None = None) -> list[str]:
        vendor_dir = Path(vendor_dir or PROJECT_ROOT / "vendor")
        rows = self._load_rows(vendor_dir)
        if not rows:
            return []
        missing = set(self.selected).difference(rows)
        if missing:
            raise ValueError(f"Missing selected SWE-PolyBench tasks: {sorted(missing)}")
        return list(self.selected)

    @staticmethod
    def _task_toml(task_id: str) -> str:
        return f'''schema_version = "1.1"

[task]
name = "cospa/{task_id}"
description = "Pinned SWE-PolyBench Verified task"
authors = []
keywords = ["repository", "swe-polybench"]

[verifier]
timeout_sec = 1800.0
network_mode = "no-network"

[agent]
timeout_sec = 1800.0
network_mode = "no-network"

[environment]
build_timeout_sec = 900.0
cpus = 2
memory_mb = 8192
storage_mb = 20480
gpus = 0
network_mode = "public"
mcp_servers = []

[verifier.env]

[environment.env]

[solution.env]
'''

    @staticmethod
    def _hermetic_test_command(language: str, test_command: str) -> str:
        """Keep verifier execution offline when the pinned image has a cache.

        The upstream Java commands invoke Maven online even though the pinned
        images contain the required repository cache. Maven's offline switch
        prevents mutable plugin metadata from turning verification into a
        network-dependent operation.
        """
        # MUI images ship this test-log reporter as an untracked evaluator
        # helper. Preserve it outside the clean agent repository and keep the
        # digest-pinned implementation used by the upstream command.
        if "/testbed/custom-reporter.js" in test_command:
            test_command = (
                "export NODE_PATH=/testbed/node_modules${NODE_PATH:+:$NODE_PATH}; "
                + test_command.replace(
                    "/testbed/custom-reporter.js",
                    "/opt/cospa/custom-reporter.js",
                )
            )
        if language.lower() != "java":
            return test_command
        return re.sub(
            r"(?<!\S)mvn\s+(?!-o(?:\s|$))",
            "mvn -o ",
            test_command,
        )

    @staticmethod
    def _verifier_script(base_commit: str, test_command: str) -> str:
        quoted_test_command = shlex.quote(test_command)
        return f'''#!/bin/bash
set -uo pipefail
mkdir -p /logs/verifier
cd /testbed || exit 0
git config --global --add safe.directory /testbed

# Some upstream images intentionally carry a dirty submodule working tree.
# Hash that declared baseline and fail closed if the agent changed it: a root
# git diff cannot faithfully capture or replay nested-repository edits.
submodule_state_hash() {{
  {_SUBMODULE_STATE_PIPELINE} | sha256sum | awk '{{print $1}}'
}}
submodule_patch_capturable=true
if [[ ! -r /opt/cospa/submodules.sha256 ]] || \
   [[ "$(submodule_state_hash)" != "$(cat /opt/cospa/submodules.sha256)" ]]; then
  submodule_patch_capturable=false
fi

# Capture all replayable model changes before hidden artifacts enter the
# repository. Ignore the image's pre-existing dirty submodule baseline.
git add -N . >/dev/null 2>&1 || true
git diff --ignore-submodules=all --binary {shlex.quote(base_commit)} \
  > /logs/verifier/model.patch
git reset --hard {shlex.quote(base_commit)} >/dev/null 2>&1
git clean -fd >/dev/null 2>&1

if [[ "$submodule_patch_capturable" != true ]]; then
  test_patch_applied=false
elif git apply --whitespace=nowarn /tests/test.patch; then
  test_patch_applied=true
else
  test_patch_applied=false
fi

if [[ "$test_patch_applied" != true ]]; then
  model_patch_applied=false
elif [[ ! -s /logs/verifier/model.patch ]]; then
  model_patch_applied=true
elif git apply --whitespace=nowarn /logs/verifier/model.patch; then
  model_patch_applied=true
else
  model_patch_applied=false
fi

if [[ "$test_patch_applied" == true && "$model_patch_applied" == true ]]; then
  set +e
  bash -lc {quoted_test_command} > /logs/verifier/test_output.txt 2>&1
  test_exit_code=$?
  set -e
elif [[ "$submodule_patch_capturable" != true ]]; then
  test_exit_code=-1
  echo "Model changed an unsupported submodule" > /logs/verifier/test_output.txt
elif [[ "$test_patch_applied" != true ]]; then
  test_exit_code=-1
  echo "Hidden test patch failed to apply" > /logs/verifier/test_output.txt
else
  test_exit_code=-1
  echo "Model patch failed to apply" > /logs/verifier/test_output.txt
fi

printf '{{"submodule_patch_capturable":%s,"test_patch_applied":%s,"model_patch_applied":%s,"test_exit_code":%s}}\n' \
  "$submodule_patch_capturable" "$test_patch_applied" \
  "$model_patch_applied" "$test_exit_code" \
  > /logs/verifier/status.json
# Harbor requires a reward artifact. Cospa computes the authoritative score
# from the pinned upstream parser after the job finishes.
echo 0 > /logs/verifier/reward.txt
exit 0
'''

    def materialize_task(
        self,
        task_id: str,
        workdir: Path,
        vendor_dir: Path | None = None,
    ) -> dict[str, Any]:
        vendor_dir = Path(vendor_dir or PROJECT_ROOT / "vendor")
        rows = self._load_rows(vendor_dir)
        if task_id not in self.selected or task_id not in rows:
            raise ValueError(f"Unknown selected SWE-PolyBench task: {task_id}")
        row = rows[task_id]
        selected = self.selected[task_id]
        mutable_image = selected["image_ref"]
        image_ref = self.image_lock[mutable_image]["pinned_ref"]

        workdir = Path(workdir)
        for directory in ("environment", "tests", "solution"):
            (workdir / directory).mkdir(parents=True, exist_ok=True)

        prompt = (
            "# Benchmark execution context\n\n"
            f"- Task ID: `{task_id}`\n"
            f"- Repository: `{row['repo']}`\n"
            "- The base repository is at `/testbed`; make all solution changes "
            "there.\n"
            "- Hidden tests and the reference patch are unavailable during the "
            "agent phase.\n"
            "- Solve only from this issue and the visible repository.\n\n"
            + row["problem_statement"].strip()
            + "\n"
        )
        (workdir / "instruction.md").write_text(prompt)
        (workdir / "task.toml").write_text(self._task_toml(task_id))
        (workdir / "environment" / "Dockerfile").write_text(
            f"FROM {image_ref}\n"
            "RUN git config --global --add safe.directory /testbed \\\n"
            " && cd /testbed \\\n"
            " && mkdir -p /opt/cospa \\\n"
            " && if [ -f custom-reporter.js ]; then \\\n"
            "      cp /testbed/custom-reporter.js /opt/cospa/custom-reporter.js; \\\n"
            "    fi \\\n"
            f" && git reset --hard {shlex.quote(row['base_commit'])} \\\n"
            " && git clean -fd \\\n"
            f" && {_SUBMODULE_STATE_PIPELINE} \\\n"
            " | sha256sum | awk '{print $1}' \\\n"
            " > /opt/cospa/submodules.sha256\n"
        )
        (workdir / "tests" / "test.patch").write_text(row["test_patch"])
        test_script = workdir / "tests" / "test.sh"
        test_script.write_text(
            self._verifier_script(
                row["base_commit"],
                self._hermetic_test_command(row["language"], row["test_command"]),
            )
        )
        test_script.chmod(0o755)
        (workdir / "solution" / "gold.patch").write_text(row["patch"])
        solution_script = workdir / "solution" / "solve.sh"
        solution_script.write_text(
            "#!/bin/bash\nset -euo pipefail\ncd /testbed\n"
            "git apply --whitespace=nowarn /solution/gold.patch\n"
        )
        solution_script.chmod(0o755)

        return {
            "task_id": task_id,
            "problem": task_id,
            "prompt": prompt,
            "repository": row["repo"],
            "language": selected["language"],
            "task_type": selected["task_type"],
            "base_commit": row["base_commit"],
            "image_ref": image_ref,
            "f2p": ast.literal_eval(row["F2P"]),
            "p2p": ast.literal_eval(row["P2P"]),
            "vendor_dir": str(vendor_dir),
        }

    def manifest_metadata(self, task_data: dict[str, Any]) -> dict[str, Any]:
        return {
            "source_revision": self.pilot["source"]["revision"],
            "dataset_revision": self.pilot["dataset"]["revision"],
            "dataset_sha256": self.pilot["dataset"]["sha256"],
            "image_ref": task_data["image_ref"],
            "repository": task_data["repository"],
            "language": task_data["language"],
            "task_type": task_data["task_type"],
            "base_commit": task_data["base_commit"],
            "verifier": "swe_polybench_upstream_parser",
            "verifier_network": "no-network",
            "java_test_command_policy": "pinned_image_maven_cache_offline",
        }

    def verify(self, task_data: dict[str, Any], workdir: Path) -> dict[str, Any]:
        jobs_dir = Path(workdir).parent / "jobs"
        status_files = sorted(
            jobs_dir.rglob("status.json"), key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        if not status_files:
            return {
                "passed": False,
                "test_count": 0,
                "grader_output": "Missing Harbor verifier artifacts",
                "exit_code": -1,
                "verifier_failed": True,
                "failure_class": "verifier_failed",
            }

        artifact_dir = status_files[0].parent
        output_file = artifact_dir / "test_output.txt"
        patch_file = artifact_dir / "model.patch"
        if not output_file.is_file() or not patch_file.is_file():
            return {
                "passed": False,
                "test_count": 0,
                "grader_output": "Missing Harbor verifier artifacts",
                "exit_code": -1,
                "verifier_failed": True,
                "failure_class": "verifier_failed",
            }
        try:
            status = json.loads(status_files[0].read_text())
        except (OSError, json.JSONDecodeError) as exc:
            return {
                "passed": False,
                "test_count": 0,
                "grader_output": f"Invalid Harbor verifier status: {exc}",
                "exit_code": -1,
                "verifier_failed": True,
                "failure_class": "verifier_failed",
            }
        if status.get("test_patch_applied") is not True:
            return {
                "passed": False,
                "test_count": 0,
                "grader_output": output_file.read_text(errors="replace"),
                "exit_code": -1,
                "verifier_failed": True,
                "failure_class": "verifier_failed",
            }
        if status.get("model_patch_applied") is not True:
            # The hidden test patch applied cleanly, so the evaluator is sound.
            # A model patch that conflicts with those tests (commonly because
            # the agent edited visible tests) is a model outcome, not an
            # infrastructure failure eligible for a stochastic retry.
            return {
                "passed": False,
                "test_count": 0,
                "grader_output": output_file.read_text(errors="replace"),
                "exit_code": 1,
                "failure_class": "incorrect",
                "model_patch_bytes": len(patch_file.read_bytes()),
                "model_patch_applied": False,
            }

        test_output = output_file.read_text(errors="replace")
        try:
            parsed = parse_polybench_test_output(
                task_data["repository"],
                test_output,
                Path(task_data["vendor_dir"]),
            )
        except Exception as exc:
            return {
                "passed": False,
                "test_count": 0,
                "grader_output": f"Pinned parser failed: {exc}\n{test_output}",
                "exit_code": -1,
                "verifier_failed": True,
                "failure_class": "verifier_failed",
            }
        verdict = score_polybench_result(
            parsed,
            f2p=task_data["f2p"],
            p2p=task_data["p2p"],
        )
        verdict["grader_output"] = test_output
        verdict["test_exit_code"] = status.get("test_exit_code")
        verdict["model_patch_bytes"] = len(patch_file.read_bytes())
        return verdict


class SwePolyBenchBalancedCandidate96Suite(SwePolyBenchVerifiedSuite):
    """Outcome-blind 96-task screen used to qualify the balanced64 panel."""

    name = "swe_polybench_balanced_candidate96"
    version = "2026-08-15"
    task_count = 96
    panel_path = BALANCED_CANDIDATE96_PATH
    image_lock_path = BALANCED_IMAGE_LOCK_PATH

    def __init__(self) -> None:
        pilot = json.loads(PILOT_PATH.read_text())
        self.pilot = pilot["suites"]["swe_polybench_verified"]
        self.panel = json.loads(self.panel_path.read_text())
        self.selected = {
            task["task_id"]: {
                "id": task["task_id"],
                "image_ref": task["image_ref"],
                "language": task["language"],
                "task_type": task["task_type"],
            }
            for task in self.panel["tasks"]
        }
        if len(self.selected) != self.task_count:
            raise ValueError(f"Invalid {self.name} manifest")
        self.image_lock = json.loads(self.image_lock_path.read_text())["images"]
        missing_images = {
            task["image_ref"]
            for task in self.panel["tasks"]
            if task["image_ref"] not in self.image_lock
        }
        if missing_images:
            raise ValueError(
                f"Missing {self.name} image pins: {sorted(missing_images)}"
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


class SwePolyBenchBalancedJavaExtension32Suite(
    SwePolyBenchBalancedCandidate96Suite
):
    """Adaptive outcome-blind Java candidate extension for balanced64."""

    name = "swe_polybench_balanced_java_extension32"
    version = "2026-08-15"
    task_count = 32
    panel_path = BALANCED_JAVA_EXTENSION32_PATH
    image_lock_path = BALANCED_JAVA_IMAGE_LOCK_PATH


class SwePolyBenchBalancedJavaStrataExtension7Suite(
    SwePolyBenchBalancedCandidate96Suite
):
    """Outcome-blind final Java small/medium qualification candidates."""

    name = "swe_polybench_balanced_java_strata_extension7"
    version = "2026-08-15"
    task_count = 7
    panel_path = BALANCED_JAVA_STRATA_EXTENSION7_PATH
    image_lock_path = BALANCED_JAVA_STRATA_IMAGE_LOCK_PATH


class SwePolyBenchVerifiedBalanced64Suite(
    SwePolyBenchBalancedCandidate96Suite
):
    """Repeat-qualified, four-language SWE-PolyBench routine panel."""

    name = "swe_polybench_verified_balanced64"
    version = "2026-08-15"
    task_count = 64
    panel_path = BALANCED64_PATH
    image_lock_path = BALANCED64_IMAGE_LOCK_PATH
