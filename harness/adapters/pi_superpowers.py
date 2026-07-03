"""
pi_superpowers adapter — pi + Superpowers skills (bench mode).

Strips interactive skill-check flows (no user present to answer clarifying
questions). Keeps only systematic-debugging + verification-before-completion
skills. This is the "Superpowers helps pi_vanilla on TB (recovery discipline)"
arm of the 2x2 ablation.

We use --no-skills to disable default discovery, then explicitly load ONLY
the bench-appropriate skills from a configured allowlist. We do NOT pass the
entire ~/.pi/agent/skills directory, because that brings in arbitrary
interactive user skills (review finding #8).
"""

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


# Bench-appropriate skills only. These are the Superpowers subset that helps
# with systematic debugging and verification discipline without requiring a
# human in the loop.
BENCH_SKILLS = [
    "systematic-debugging",
    "verification-before-completion",
]

# Known interactive skills that MUST be stripped under bench mode.
INTERACTIVE_SKILLS = {
    "check",
    "realitycheck",
    "shisa-kb",
    "rc-analyze",
    "rc-export",
    "rc-extract",
    "rc-search",
    "rc-stats",
    "rc-synthesize",
    "rc-validate",
}


@dataclass
class AdapterResult:
    returncode: int
    usage: Optional[object] = None
    error: Optional[str] = None


def _resolve_bench_skill_paths() -> list:
    """Return --skill paths for each bench skill that exists on disk.

    Prefer installed user skills under ~/.pi/agent/skills/<name>/, then fall
    back to the repo-local bench skill definitions. We never return the bare
    skills directory — only individual, allowlisted skill subdirs.
    """
    skills_roots = [
        Path.home() / ".pi" / "agent" / "skills",
        Path(__file__).resolve().parents[1] / "bench_skills",
    ]
    paths = []
    for name in BENCH_SKILLS:
        if name in INTERACTIVE_SKILLS:
            continue
        for skills_root in skills_roots:
            candidate = skills_root / name
            if candidate.is_dir():
                paths.append(str(candidate))
                break
    return paths


class PiSuperpowersAdapter:
    """Pi + Superpowers skills (bench mode, no interactive flows)."""

    name = "pi_superpowers"
    version = "superpowers-bench"

    def run(self, task_data: dict, workdir: Path, log_file: Path, stderr_file: Path) -> AdapterResult:
        """
        Run pi with the Superpowers bench subset in headless mode.

        Uses --no-skills to disable default discovery, then loads only the
        allowlisted bench skills (systematic-debugging,
        verification-before-completion). Interactive skills are stripped.
        """
        prompt = task_data.get("prompt", "")

        cmd = [
            "pi",
            "--print",
            "--no-extensions",
            "--no-skills",
            "--model", task_data.get("model_id", "nvidia/nemotron-3-ultra-550b-a55b"),
        ]

        # Load ONLY the bench-appropriate skills (never the whole user dir)
        for skill_path in _resolve_bench_skill_paths():
            cmd.extend(["--skill", skill_path])

        try:
            with open(log_file, "w") as log_f:
                with open(stderr_file, "w") as stderr_f:
                    result = subprocess.run(
                        cmd,
                        input=prompt,
                        cwd=str(workdir),
                        stdout=log_f,
                        stderr=stderr_f,
                        text=True,
                        timeout=task_data.get("timeout", 600),
                    )

            return AdapterResult(returncode=result.returncode)

        except subprocess.TimeoutExpired:
            return AdapterResult(returncode=-1)
        except Exception as e:
            return AdapterResult(returncode=-1, error=str(e))
