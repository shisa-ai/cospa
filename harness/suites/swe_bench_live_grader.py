#!/usr/bin/env python3
"""Standalone hidden-test grader copied into SWE-bench-Live Harbor tasks."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
from pathlib import Path
from typing import Any


TESTS_DIR = Path(os.environ.get("COSPA_TESTS_DIR", "/tests"))
LOGS_DIR = Path(os.environ.get("COSPA_VERIFIER_LOGS_DIR", "/logs/verifier"))
TESTBED_DIR = Path(os.environ.get("COSPA_TESTBED_DIR", "/testbed"))


def _status_is(value: Any, expected: str) -> bool:
    return expected in str(value).strip().lower()


def score_statuses(
    statuses: dict[str, Any],
    *,
    fail_to_pass: list[str],
    pass_to_pass: list[str],
) -> dict[str, Any]:
    """Score strict F2P/P2P coverage, including missing expected tests.

    Upstream's evaluator rejects failing expected tests but can overlook absent
    pass-to-pass names. Cospa requires every declared expected test to be
    observed and passing so deleting or suppressing visible regression tests
    cannot improve a score.
    """

    def classify(expected_tests: list[str]) -> dict[str, list[str]]:
        passed = []
        failed = []
        missing = []
        for name in expected_tests:
            if name not in statuses:
                missing.append(name)
            elif _status_is(statuses[name], "pass"):
                passed.append(name)
            else:
                failed.append(name)
        return {"passed": passed, "failed": failed, "missing": missing}

    f2p = classify(fail_to_pass)
    p2p = classify(pass_to_pass)
    resolved = bool(fail_to_pass) and not any(
        (
            f2p["failed"],
            f2p["missing"],
            p2p["failed"],
            p2p["missing"],
        )
    )
    return {
        "resolved": resolved,
        "observed_test_count": len(statuses),
        "fail_to_pass": f2p,
        "pass_to_pass": p2p,
    }


def _find_repository(root: Path = TESTBED_DIR) -> Path:
    if (root / ".git").is_dir():
        return root
    candidates = sorted(
        git_dir.parent
        for git_dir in root.glob("*/*/.git")
        if git_dir.is_dir()
    )
    if not candidates:
        candidates = sorted(
            git_dir.parent for git_dir in root.glob("*/.git") if git_dir.is_dir()
        )
    if len(candidates) != 1:
        raise RuntimeError(
            f"Expected one git repository under {root}, found {len(candidates)}"
        )
    return candidates[0]


def _apply_hidden_test_patch(repository: Path) -> None:
    patch_path = TESTS_DIR / "test.patch"
    git_env = {
        **os.environ,
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_SYSTEM": "/dev/null",
    }
    result = subprocess.run(
        ["git", "apply", "--whitespace=nowarn", str(patch_path)],
        cwd=repository,
        env=git_env,
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "Could not apply hidden evaluator test patch: "
            + (result.stderr.strip() or result.stdout.strip())
        )


def _run_test_commands(repository: Path, task: dict) -> tuple[str, int]:
    rebuild = " ; ".join(str(command) for command in task.get("rebuild_cmds", []))
    tests = " ; ".join(str(command) for command in task.get("test_cmds", []))
    prints = " ; ".join(str(command) for command in task.get("print_cmds", []))
    log_path = LOGS_DIR / "post_patch_log.txt"

    lines = ["set +e", f"cd {shlex.quote(str(repository))}"]
    if rebuild.strip():
        lines.append(rebuild)
    if prints.strip():
        lines.extend(
            [
                tests,
                "test_status=$?",
                f"({prints}) > {shlex.quote(str(log_path))} 2>&1",
                "exit $test_status",
            ]
        )
    else:
        lines.extend(
            [
                f"({tests}) > {shlex.quote(str(log_path))} 2>&1",
                "exit $?",
            ]
        )
    result = subprocess.run(
        ["bash", "--noprofile", "--norc", "-c", "\n".join(lines)],
        cwd=repository,
        text=True,
    )
    if not log_path.exists():
        raise RuntimeError("Test commands did not produce a verifier log")
    return log_path.read_text(errors="replace"), result.returncode


def _parse_statuses(parser_source: str, log: str) -> dict[str, Any]:
    namespace: dict[str, Any] = {}
    exec(compile(parser_source, "<pinned-swe-bench-live-parser>", "exec"), namespace)
    parser = namespace.get("parser")
    if not callable(parser):
        raise RuntimeError("Pinned log parser does not define parser(log)")
    statuses = parser(log)
    if not isinstance(statuses, dict):
        raise RuntimeError("Pinned log parser did not return a dictionary")
    return {str(name): value for name, value in statuses.items()}


def _write_result(result: dict[str, Any]) -> None:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    (LOGS_DIR / "evaluation.json").write_text(json.dumps(result, indent=2) + "\n")
    reward = 1 if result.get("resolved") and not result.get("infrastructure_error") else 0
    (LOGS_DIR / "reward.txt").write_text(f"{reward}\n")


def main() -> int:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    try:
        task = json.loads((TESTS_DIR / "task.json").read_text())
        repository = _find_repository()
        _apply_hidden_test_patch(repository)
        log, test_exit_code = _run_test_commands(repository, task)
        statuses = _parse_statuses(str(task["log_parser"]), log)
        result = score_statuses(
            statuses,
            fail_to_pass=[str(name) for name in task["FAIL_TO_PASS"]],
            pass_to_pass=[str(name) for name in task["PASS_TO_PASS"]],
        )
        result.update(
            {
                "instance_id": task["instance_id"],
                "test_command_exit_code": test_exit_code,
                "infrastructure_error": None,
            }
        )
    except Exception as error:
        result = {
            "resolved": False,
            "instance_id": None,
            "observed_test_count": 0,
            "infrastructure_error": f"{type(error).__name__}: {error}",
        }
    _write_result(result)
    return 0 if result.get("resolved") else 1


if __name__ == "__main__":
    raise SystemExit(main())
