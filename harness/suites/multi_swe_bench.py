"""Multi-SWE-bench Flash pilot through pinned images and Harbor.

The upstream images contain the repository, test commands, dependencies, and
also construction-time gold/test patches. Cospa derives a history-free baseline
that removes those hidden artifacts before the agent starts. The hidden test
patch and oracle patch enter only Harbor's verifier and solution phases.
"""

from __future__ import annotations

import functools
import hashlib
import importlib.util
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
HERMETIC25_PATH = (
    PROJECT_ROOT / "configs" / "multi_swe_bench_flash_hermetic25.json"
)
IMAGE_LOCK_PATH = PROJECT_ROOT / "configs" / "ornith_runtime_pilot_images_v1.json"
_DATASET_LOCK = threading.Lock()
_DATASET_CACHE: dict[tuple[str, str, tuple[str, ...]], dict[str, dict[str, Any]]] = {}
_REGISTER_RE = re.compile(
    r"@Instance\.register\([\"']([^\"']+)[\"']\s*,\s*[\"']([^\"']+)[\"']\)"
)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


@functools.lru_cache(maxsize=4)
def _parser_registry(repo_root: str) -> dict[tuple[str, str], str]:
    """Map upstream ``@Instance.register`` pairs to their pinned source file."""
    root = Path(repo_root)
    registry: dict[tuple[str, str], str] = {}
    for path in root.rglob("*.py"):
        source = path.read_text(errors="replace")
        for org, repo in _REGISTER_RE.findall(source):
            registry[(org, repo)] = str(path)
    return registry


def parse_multi_swe_test_output(
    row: dict[str, Any],
    output: str,
    vendor_dir: Path,
) -> dict[str, list[str]]:
    """Run the pinned repository parser without importing its Docker stack.

    The vendored harness eagerly imports thousands of repository modules plus
    optional Docker/serialization packages. An isolated subprocess loads only
    the exact registered parser source and supplies tiny compatibility stubs for
    decorators unused by parsing.
    """
    source_root = (
        Path(vendor_dir) / "multi-swe-bench" / "multi_swe_bench"
    ).resolve()
    repos_root = source_root / "harness" / "repos"
    parser_file = _parser_registry(str(repos_root)).get((row["org"], row["repo"]))
    if not parser_file:
        raise ValueError(
            f"No pinned Multi-SWE parser for {row['org']}/{row['repo']}"
        )

    parser_program = r'''
import dataclasses
import importlib
import importlib.util
import json
import sys
import types
from typing import get_args, get_origin

source_root, parser_file, org, repo, number, base_json = sys.argv[1:]

# Bypass the harness package's eager all-repository import.
root_package = types.ModuleType("multi_swe_bench")
root_package.__path__ = [source_root]
sys.modules[root_package.__name__] = root_package
harness_package = types.ModuleType("multi_swe_bench.harness")
harness_package.__path__ = [source_root + "/harness"]
sys.modules[harness_package.__name__] = harness_package

# Parsing uses plain dataclasses; serializer and diff helpers are optional.
# A few pinned parsers rely on dataclasses-json for recursive nested objects,
# so preserve that narrow from_dict behavior without importing its Docker-era
# dependency stack.
def _convert_dataclass_value(annotation, value):
    origin = get_origin(annotation)
    if origin is list:
        (item_type,) = get_args(annotation)
        return [_convert_dataclass_value(item_type, item) for item in value]
    if dataclasses.is_dataclass(annotation) and isinstance(value, dict):
        return annotation.from_dict(value)
    return value


def _dataclass_json(cls):
    @classmethod
    def from_dict(inner_cls, payload):
        values = {}
        for field in dataclasses.fields(inner_cls):
            if field.name in payload:
                values[field.name] = _convert_dataclass_value(
                    field.type, payload[field.name]
                )
        return inner_cls(**values)

    cls.from_dict = from_dict
    return cls


dataclasses_json = types.ModuleType("dataclasses_json")
dataclasses_json.dataclass_json = _dataclass_json
dataclasses_json.config = lambda **kwargs: {}
sys.modules["dataclasses_json"] = dataclasses_json
unidiff = types.ModuleType("unidiff")
unidiff.PatchSet = lambda _: []
sys.modules["unidiff"] = unidiff

for module_name in ("pull_request", "test_result", "image", "instance"):
    importlib.import_module("multi_swe_bench.harness." + module_name)

spec = importlib.util.spec_from_file_location("cospa_multi_swe_parser", parser_file)
module = importlib.util.module_from_spec(spec)
if spec.loader is None:
    raise RuntimeError("Pinned parser has no loader")
spec.loader.exec_module(module)

from multi_swe_bench.harness.instance import Instance

base = types.SimpleNamespace(**json.loads(base_json))
pr = types.SimpleNamespace(
    org=org,
    repo=repo,
    number=int(number),
    tag="",
    number_interval="",
    base=base,
    fix_patch="",
    test_patch="",
)
config = types.SimpleNamespace(need_clone=False, global_env=None, clear_env=False)
parsed = Instance.create(pr, config).parse_log(sys.stdin.read())
print(json.dumps({
    "passed_tests": sorted(parsed.passed_tests),
    "failed_tests": sorted(parsed.failed_tests),
    "skipped_tests": sorted(parsed.skipped_tests),
}))
'''
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            parser_program,
            str(source_root),
            parser_file,
            row["org"],
            row["repo"],
            str(row["number"]),
            json.dumps(row["base"]),
        ],
        input=output,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise ValueError(
            f"Pinned Multi-SWE parser failed for {row['instance_id']}: {detail}"
        )
    try:
        parsed = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Pinned Multi-SWE parser emitted invalid JSON for {row['instance_id']}"
        ) from exc
    if not isinstance(parsed, dict):
        raise ValueError(
            f"Pinned Multi-SWE parser returned non-object for {row['instance_id']}"
        )
    return {
        "passed_tests": list(parsed.get("passed_tests") or []),
        "failed_tests": list(parsed.get("failed_tests") or []),
        "skipped_tests": list(parsed.get("skipped_tests") or []),
    }


def score_multi_swe_result(
    parsed: dict[str, list[str]],
    row: dict[str, Any],
) -> dict[str, Any]:
    """Apply the upstream transition-category resolution contract."""
    passed_tests = list(parsed.get("passed_tests") or [])
    failed_tests = list(parsed.get("failed_tests") or [])
    skipped_tests = list(parsed.get("skipped_tests") or [])
    passed_set = set(passed_tests)
    failed_set = set(failed_tests)

    f2p = set(row.get("f2p_tests") or {})
    p2p = set(row.get("p2p_tests") or {})
    s2p = set(row.get("s2p_tests") or {})
    n2p = set(row.get("n2p_tests") or {})
    required_transitions = f2p | s2p | n2p
    all_f2p_passed = f2p.issubset(passed_set)
    all_transition_tests_passed = required_transitions.issubset(passed_set)
    all_p2p_passed = p2p.issubset(passed_set)
    no_p2p_failed = not p2p.intersection(failed_set)
    resolved = (
        bool(required_transitions)
        and all_transition_tests_passed
        and all_p2p_passed
        and no_p2p_failed
    )
    return {
        "passed": resolved,
        "test_count": len(passed_tests) + len(failed_tests) + len(skipped_tests),
        "tests_passed": len(passed_tests),
        "all_f2p_passed": all_f2p_passed,
        "all_transition_tests_passed": all_transition_tests_passed,
        "all_p2p_passed": all_p2p_passed,
        "no_p2p_failed": no_p2p_failed,
        "passed_tests": passed_tests,
        "failed_tests": failed_tests,
        "skipped_tests": skipped_tests,
        "failure_class": "resolved" if resolved else "incorrect",
        "exit_code": 0,
    }


class MultiSweBenchFlashSuite(TerminalBenchSuite):
    """Frozen 30-task Multi-SWE-bench Flash runtime/validity pilot."""

    name = "multi_swe_bench_flash"
    version = "0.1"
    task_count = 30
    source_suite_name = "multi_swe_bench_flash"
    verify_on_adapter_failure = True

    def __init__(self) -> None:
        pilot = json.loads(PILOT_PATH.read_text())
        self.pilot = pilot["suites"][self.source_suite_name]
        self.selected = {task["id"]: task for task in self.pilot["tasks"]}
        image_lock = json.loads(IMAGE_LOCK_PATH.read_text())["images"]
        self.images_by_task: dict[str, str] = {}
        for mutable_ref, image in image_lock.items():
            if self.source_suite_name not in image.get("suites", []):
                continue
            for task_id in image.get("task_ids", []):
                if task_id in self.selected:
                    self.images_by_task[task_id] = image["pinned_ref"]
        self._rows: dict[str, dict[str, Any]] | None = None

    def _dataset_path(self, vendor_dir: Path) -> Path:
        declared = Path(self.pilot["dataset"]["local_path"])
        return Path(vendor_dir).joinpath(*declared.parts[1:])

    def _load_rows(self, vendor_dir: Path) -> dict[str, dict[str, Any]]:
        dataset_path = self._dataset_path(vendor_dir)
        if not dataset_path.is_file():
            return {}
        expected = self.pilot["dataset"]["sha256"]
        cache_key = (
            str(dataset_path.resolve()),
            expected,
            tuple(sorted(self.selected)),
        )
        with _DATASET_LOCK:
            cached = _DATASET_CACHE.get(cache_key)
            if cached is None:
                actual = _sha256_file(dataset_path)
                if actual != expected:
                    raise ValueError(
                        f"Multi-SWE-bench Flash dataset checksum mismatch: {actual}"
                    )
                rows: dict[str, dict[str, Any]] = {}
                with dataset_path.open() as handle:
                    for line in handle:
                        row = json.loads(line)
                        task_id = row.get("instance_id")
                        if task_id in self.selected:
                            rows[task_id] = row
                _DATASET_CACHE[cache_key] = rows
                cached = rows
        self._rows = cached
        return cached

    def get_task_ids(self, vendor_dir: Path | None = None) -> list[str]:
        vendor_dir = Path(vendor_dir or PROJECT_ROOT / "vendor")
        rows = self._load_rows(vendor_dir)
        if not rows:
            return []
        missing_rows = set(self.selected).difference(rows)
        missing_images = set(self.selected).difference(self.images_by_task)
        if missing_rows:
            raise ValueError(f"Missing selected Multi-SWE tasks: {sorted(missing_rows)}")
        if missing_images:
            raise ValueError(
                f"Missing selected Multi-SWE image pins: {sorted(missing_images)}"
            )
        return list(self.selected)

    @staticmethod
    def _task_toml(task_id: str) -> str:
        return f'''schema_version = "1.1"

[task]
name = "cospa/{task_id}"
description = "Pinned Multi-SWE-bench Flash task"
authors = []
keywords = ["repository", "multi-swe-bench"]

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
    def _prompt(row: dict[str, Any]) -> str:
        sections = [
            "# Benchmark execution context",
            "",
            f"- Task ID: `{row['instance_id']}`",
            f"- Repository: `{row['org']}/{row['repo']}`",
            "- The base repository is at `/testbed`; make all solution changes there.",
            "- Hidden tests and the reference patch are unavailable during the agent phase.",
            "- Solve only from the issue text and visible repository.",
            "",
        ]
        issues = row.get("resolved_issues") or []
        if issues:
            for issue in issues:
                sections.extend(
                    [
                        f"## Issue #{issue['number']}: {issue['title']}",
                        "",
                        (issue.get("body") or "").strip(),
                        "",
                    ]
                )
        else:
            sections.extend(
                [
                    f"## {row.get('title') or 'Task'}",
                    "",
                    (row.get("body") or "").strip(),
                    "",
                ]
            )
        return "\n".join(sections).rstrip() + "\n"

    @staticmethod
    def _verifier_script() -> str:
        return '''#!/bin/bash
set -uo pipefail
mkdir -p /logs/verifier
cd /testbed || exit 0
git config --global --add safe.directory /testbed

# Capture all non-ignored model changes before hidden artifacts enter.
git add -N . >/dev/null 2>&1 || true
git diff --binary HEAD > /logs/verifier/model.patch
git reset --hard HEAD >/dev/null 2>&1
git clean -fd >/dev/null 2>&1

# Restore image-provided untracked build/test assets so agent-side tool runs
# cannot alter verifier behavior outside the captured source patch.
xargs -0r rm -rf < /opt/cospa/baseline-untracked.z
tar -xf /opt/cospa/baseline-untracked.tar -C /testbed

if git apply --whitespace=nowarn /tests/test.patch; then
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
  bash /home/run.sh > /logs/verifier/test_output.txt 2>&1
  test_exit_code=$?
  set -e
elif [[ "$test_patch_applied" != true ]]; then
  test_exit_code=-1
  echo "Hidden test patch failed to apply" > /logs/verifier/test_output.txt
else
  test_exit_code=-1
  echo "Model patch failed to apply" > /logs/verifier/test_output.txt
fi

printf '{"test_patch_applied":%s,"model_patch_applied":%s,"test_exit_code":%s}\n' \
  "$test_patch_applied" "$model_patch_applied" "$test_exit_code" \
  > /logs/verifier/status.json
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
            raise ValueError(f"Unknown selected Multi-SWE task: {task_id}")
        if task_id not in self.images_by_task:
            raise ValueError(f"Missing selected Multi-SWE image pin: {task_id}")
        row = rows[task_id]
        selected = self.selected[task_id]
        image_ref = self.images_by_task[task_id]
        repo_path = f"/home/{row['repo']}"
        base_commit = row["base"]["sha"]

        workdir = Path(workdir)
        for directory in ("environment", "tests", "solution"):
            (workdir / directory).mkdir(parents=True, exist_ok=True)

        prompt = self._prompt(row)
        (workdir / "instruction.md").write_text(prompt)
        (workdir / "task.toml").write_text(self._task_toml(task_id))
        (workdir / "environment/Dockerfile").write_text(
            f"FROM {image_ref}\n"
            "RUN set -eux; \\\n"
            "    rm -f /home/fix.patch /home/test.patch; \\\n"
            f"    cd {shlex.quote(repo_path)}; \\\n"
            "    git config --global --add safe.directory '*' ; \\\n"
            f"    git checkout --detach {shlex.quote(base_commit)}; \\\n"
            f"    git reset --hard {shlex.quote(base_commit)}; \\\n"
            "    mkdir -p /opt/cospa; \\\n"
            "    git ls-files --others --exclude-standard > /opt/cospa/baseline-untracked; \\\n"
            "    find . -path '*/.git' -prune -o -type d -empty -printf '%P/\\n' >> /opt/cospa/baseline-untracked; \\\n"
            "    git ls-files --others --exclude-standard -z > /opt/cospa/baseline-untracked.z; \\\n"
            "    find . -path '*/.git' -prune -o -type d -empty -printf '%P/\\0' >> /opt/cospa/baseline-untracked.z; \\\n"
            "    tar --null -T /opt/cospa/baseline-untracked.z -cf /opt/cospa/baseline-untracked.tar; \\\n"
            "    find . -mindepth 2 -name .git -print0 | xargs -0r rm -rf; \\\n"
            "    rm -rf .git; \\\n"
            "    git init; \\\n"
            "    cat /opt/cospa/baseline-untracked >> .git/info/exclude; \\\n"
            "    git config user.name cospa; \\\n"
            "    git config user.email cospa@localhost; \\\n"
            "    git add -A; \\\n"
            "    git commit -m 'Cospa agent baseline'; \\\n"
            "    rm -rf /testbed; \\\n"
            f"    ln -s {shlex.quote(repo_path)} /testbed\n"
        )
        (workdir / "tests/test.patch").write_text(row["test_patch"])
        verifier = workdir / "tests/test.sh"
        verifier.write_text(self._verifier_script())
        verifier.chmod(0o755)
        (workdir / "solution/gold.patch").write_text(row["fix_patch"])
        solution = workdir / "solution/solve.sh"
        solution.write_text(
            "#!/bin/bash\nset -euo pipefail\ncd /testbed\n"
            "git apply --whitespace=nowarn /solution/gold.patch\n"
        )
        solution.chmod(0o755)

        # Verification needs only parser identity and transition sets. Keep the
        # hidden patches out of task_data so no adapter can receive them through
        # a future runner path.
        verification_row = {
            key: row[key]
            for key in (
                "org",
                "repo",
                "number",
                "base",
                "instance_id",
                "f2p_tests",
                "p2p_tests",
                "s2p_tests",
                "n2p_tests",
            )
        }
        return {
            "task_id": task_id,
            "problem": task_id,
            "prompt": prompt,
            "repository": f"{row['org']}/{row['repo']}",
            "language": selected["language"],
            "difficulty": selected.get("difficulty"),
            "base_commit": base_commit,
            "image_ref": image_ref,
            "row": verification_row,
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
            "difficulty": task_data["difficulty"],
            "base_commit": task_data["base_commit"],
            "verifier": "multi_swe_bench_upstream_parser",
            "verifier_network": "no-network",
        }

    def parse_test_output(
        self,
        row: dict[str, Any],
        output: str,
        vendor_dir: Path,
    ) -> dict[str, list[str]]:
        return parse_multi_swe_test_output(row, output, vendor_dir)

    def score_result(
        self,
        parsed: dict[str, list[str]],
        row: dict[str, Any],
    ) -> dict[str, Any]:
        return score_multi_swe_result(parsed, row)

    def verify(self, task_data: dict[str, Any], workdir: Path) -> dict[str, Any]:
        jobs_dir = Path(workdir).parent / "jobs"
        status_files = sorted(
            jobs_dir.rglob("status.json"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        if not status_files:
            return self._verifier_failure("Missing Harbor verifier artifacts")

        artifact_dir = status_files[0].parent
        output_file = artifact_dir / "test_output.txt"
        patch_file = artifact_dir / "model.patch"
        if not output_file.is_file() or not patch_file.is_file():
            return self._verifier_failure("Missing Harbor verifier artifacts")
        try:
            status = json.loads(status_files[0].read_text())
        except (OSError, json.JSONDecodeError) as exc:
            return self._verifier_failure(f"Invalid Harbor verifier status: {exc}")
        if status.get("test_patch_applied") is not True:
            return self._verifier_failure(output_file.read_text(errors="replace"))
        if status.get("model_patch_applied") is not True:
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
            parsed = self.parse_test_output(
                task_data["row"],
                test_output,
                Path(task_data["vendor_dir"]),
            )
        except Exception as exc:
            return self._verifier_failure(
                f"Pinned parser failed: {exc}\n{test_output}"
            )
        verdict = self.score_result(parsed, task_data["row"])
        verdict["grader_output"] = test_output
        verdict["test_exit_code"] = status.get("test_exit_code")
        verdict["model_patch_bytes"] = len(patch_file.read_bytes())
        return verdict

    @staticmethod
    def _verifier_failure(detail: str) -> dict[str, Any]:
        return {
            "passed": False,
            "test_count": 0,
            "grader_output": detail,
            "exit_code": -1,
            "verifier_failed": True,
            "failure_class": "verifier_failed",
        }


class MultiSweBenchFlashHermeticSuite(MultiSweBenchFlashSuite):
    """Repeat-qualified no-network subset of the screened Flash pilot."""

    name = "multi_swe_bench_flash_hermetic25"
    version = "2026-08-15"
    task_count = 25
    panel_path = HERMETIC25_PATH

    def __init__(self) -> None:
        super().__init__()
        self.panel = json.loads(self.panel_path.read_text())
        task_ids = [task["task_id"] for task in self.panel["tasks"]]
        if len(task_ids) != self.task_count or len(set(task_ids)) != len(task_ids):
            raise ValueError("Invalid Multi-SWE-bench Flash hermetic25 manifest")
        missing = set(task_ids).difference(self.selected)
        if missing:
            raise ValueError(f"Missing Multi-SWE hermetic25 tasks: {sorted(missing)}")
        self.selected = {task_id: self.selected[task_id] for task_id in task_ids}

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
