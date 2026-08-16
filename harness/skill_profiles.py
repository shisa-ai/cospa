"""Pinned, reproducible capability profiles shared by benchmark adapters."""

from __future__ import annotations

import hashlib
import json
import shlex
from copy import deepcopy
from pathlib import Path
from typing import Any


BENCH_SKILLS_ROOT = Path(__file__).with_name("bench_skills")
SUPERPOWERS_PROFILE_PATH = BENCH_SKILLS_ROOT / "PROFILE.json"
CONTAINER_BENCH_SKILLS_ROOT = Path("/installed-agent/bench-skills")


def _safe_profile_path(root: Path, relative: str) -> Path:
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"unsafe Superpowers profile path: {relative}")
    resolved_root = root.resolve()
    resolved = (root / path).resolve()
    if resolved != resolved_root and resolved_root not in resolved.parents:
        raise ValueError(f"Superpowers profile path escapes root: {relative}")
    return resolved


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_superpowers_profile() -> dict[str, Any]:
    """Load and validate the immutable repo-local Superpowers treatment.

    Every selected file is checksum-verified before an adapter starts. This
    prevents a mutable user skill installation or partial checkout from silently
    changing a benchmark arm while retaining the same adapter label.
    """
    try:
        profile = json.loads(SUPERPOWERS_PROFILE_PATH.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid Superpowers profile: {error}") from error

    if profile.get("id") != "superpowers-bench-v1":
        raise ValueError("unexpected Superpowers capability profile id")
    source = profile.get("source")
    skills = profile.get("skills")
    files = profile.get("files")
    if not isinstance(source, dict) or not isinstance(skills, list) or not isinstance(files, dict):
        raise ValueError("Superpowers profile is missing source, skills, or files")
    if not skills or len(skills) != len(set(skills)):
        raise ValueError("Superpowers profile skills must be non-empty and unique")

    files_by_skill: dict[str, list[dict[str, str]]] = {str(name): [] for name in skills}
    for relative, expected in sorted(files.items()):
        if not isinstance(relative, str) or not isinstance(expected, str):
            raise ValueError("Superpowers profile file entries must be string pairs")
        path = _safe_profile_path(BENCH_SKILLS_ROOT, relative)
        if not path.is_file():
            raise ValueError(f"Superpowers profile file is missing: {relative}")
        observed = _sha256(path)
        if observed != expected:
            raise ValueError(
                f"Superpowers profile checksum mismatch for {relative}: "
                f"{observed} != {expected}"
            )
        skill_name = Path(relative).parts[0]
        if skill_name not in files_by_skill:
            raise ValueError(f"file belongs to undeclared Superpowers skill: {relative}")
        files_by_skill[skill_name].append(
            {
                "path": str(Path(relative).relative_to(skill_name)),
                "sha256": observed,
            }
        )

    manifest_skills = []
    for name in skills:
        skill_files = files_by_skill[str(name)]
        if not any(item["path"] == "SKILL.md" for item in skill_files):
            raise ValueError(f"Superpowers skill has no SKILL.md: {name}")
        digest = hashlib.sha256()
        for item in skill_files:
            digest.update(item["path"].encode())
            digest.update(b"\0")
            digest.update(bytes.fromhex(item["sha256"]))
            digest.update(b"\0")
        manifest_skills.append(
            {
                "name": str(name),
                "sha256": digest.hexdigest(),
                "files": skill_files,
            }
        )

    return {
        "id": profile["id"],
        "source": deepcopy(source),
        "skills": manifest_skills,
    }


def superpowers_skill_paths() -> list[str]:
    """Return only checksum-validated repo-local skill directories."""
    profile = load_superpowers_profile()
    return [str(BENCH_SKILLS_ROOT / skill["name"]) for skill in profile["skills"]]


def superpowers_container_skill_paths() -> tuple[str, ...]:
    """Return the matching paths used inside Harbor task containers."""
    profile = load_superpowers_profile()
    return tuple(
        str(CONTAINER_BENCH_SKILLS_ROOT / skill["name"])
        for skill in profile["skills"]
    )


def superpowers_install_command(
    destination: Path | str = CONTAINER_BENCH_SKILLS_ROOT,
) -> str:
    """Render a shell command that materializes the exact pinned skill files.

    Harbor setup cannot assume the Cospa checkout exists in a task container,
    so the reviewed text files are embedded as quoted heredocs. Per-file hashes
    are checked on the host before rendering and again in the container after
    materialization.
    """
    profile = load_superpowers_profile()
    destination = Path(destination)
    destination_q = shlex.quote(str(destination))
    lines = [
        "set -euo pipefail",
        f"destination={destination_q}",
        'rm -rf -- "$destination"',
        'mkdir -p -- "$destination"',
    ]

    for skill in profile["skills"]:
        name = skill["name"]
        for item in skill["files"]:
            source = BENCH_SKILLS_ROOT / name / item["path"]
            relative = Path(name) / item["path"]
            target = destination / relative
            target_q = shlex.quote(str(target))
            parent_q = shlex.quote(str(target.parent))
            text = source.read_text()
            if not text.endswith("\n"):
                raise ValueError(f"Superpowers text file lacks trailing newline: {relative}")
            delimiter = f"__COSPA_SUPERPOWERS_{item['sha256'].upper()}__"
            if delimiter in text:
                raise ValueError(f"heredoc delimiter collision in {relative}")
            lines.extend(
                [
                    f"mkdir -p -- {parent_q}",
                    f"cat >{target_q} <<'{delimiter}'",
                    text[:-1],
                    delimiter,
                    f"printf '%s  %s\\n' {shlex.quote(item['sha256'])} {target_q} | sha256sum -c -",
                ]
            )
            if source.stat().st_mode & 0o111:
                lines.append(f"chmod 0755 -- {target_q}")

    return "\n".join(lines) + "\n"
