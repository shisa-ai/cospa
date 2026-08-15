"""Fail-safe cleanup helpers for Harbor's per-trial Docker networks."""

from __future__ import annotations

import json
import re
import subprocess
from datetime import datetime, timezone
from typing import Any


_HARBOR_NETWORK_RE = re.compile(r"^workdir__[a-z0-9]+__env_default$")


def _parse_docker_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    normalized = value.replace("Z", "+00:00")
    normalized = re.sub(r"(\.\d{6})\d+(?=[+-])", r"\1", normalized)
    try:
        created = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    return created.astimezone(timezone.utc)


def reclaim_stale_harbor_networks(
    *,
    min_age_seconds: float = 300,
    now: datetime | None = None,
) -> list[str]:
    """Remove only old, unattached Harbor Compose networks.

    Active networks, recently created networks, unrelated Compose projects, and
    all non-Harbor Docker networks are preserved. Docker failures are best-effort
    here because the subsequent Harbor launch remains the fail-closed authority.
    """
    current_time = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    try:
        listed = subprocess.run(
            ["docker", "network", "ls", "--quiet"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if listed.returncode != 0:
            return []
        network_ids = [line for line in listed.stdout.splitlines() if line]
        if not network_ids:
            return []
        inspected = subprocess.run(
            ["docker", "network", "inspect", *network_ids],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if inspected.returncode != 0:
            return []
        networks = json.loads(inspected.stdout)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        return []

    stale: list[tuple[str, str]] = []
    for network in networks if isinstance(networks, list) else []:
        if not isinstance(network, dict):
            continue
        name = network.get("Name")
        network_id = network.get("Id")
        if (
            not isinstance(name, str)
            or not _HARBOR_NETWORK_RE.fullmatch(name)
            or not isinstance(network_id, str)
            or not network_id
            or bool(network.get("Containers"))
        ):
            continue
        created = _parse_docker_timestamp(network.get("Created"))
        if created is None:
            continue
        if (current_time - created).total_seconds() < min_age_seconds:
            continue
        stale.append((network_id, name))

    if not stale:
        return []
    try:
        removed = subprocess.run(
            ["docker", "network", "rm", *(network_id for network_id, _ in stale)],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if removed.returncode != 0:
        return []
    return [name for _, name in stale]
