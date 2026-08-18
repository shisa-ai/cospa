"""Per-run cost rollup from trial manifests (RUN-MANAGEMENT P5).

``scripts/summarize-costs.py`` scans a run directory for ``manifest.json``
files, prices each trial from ``models.yaml`` prices x pi usage (using the
runtime ``manifest.cost`` when present, or re-deriving it for historical
manifests), and writes a ``cost-summary.json`` rollup.

The pure functions here are unit-tested in ``tests/test_cost_summary.py``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from harness.cost import trial_cost


def iter_manifests(root: Path | str) -> list[tuple[Path, dict]]:
    """Yield (path, manifest) for every readable manifest under root."""
    root = Path(root)
    if not root.exists():
        return []
    manifests = []
    for path in sorted(root.rglob("manifest.json")):
        try:
            manifests.append((path, json.loads(path.read_text())))
        except (OSError, ValueError):
            continue
    return manifests


def manifest_cost_usd(manifest: dict) -> tuple[float, str | None]:
    """Return (usd, source) for a manifest's cost.

    ``source`` is ``"manifest"`` when a runtime cost record exists, ``"derived"``
    when priced from models.yaml x usage on the fly (historical backfill), or
    None when the trial is unpriced (no usage or no price table).
    """
    cost = manifest.get("cost")
    if isinstance(cost, dict) and isinstance(cost.get("usd"), (int, float)):
        return float(cost["usd"]), "manifest"
    computed = trial_cost(manifest.get("model"), manifest.get("token_usage"))
    if computed is not None:
        return float(computed["usd"]), "derived"
    return 0.0, None


def _bucket(manifest: dict) -> tuple[str, str, str]:
    model = (manifest.get("model") or {}).get("id") or manifest.get("model_id") or "unknown"
    adapter = (manifest.get("adapter") or {}).get("name") or "unknown"
    suite = (manifest.get("suite") or {}).get("name") or "unknown"
    return model, adapter, suite


def aggregate(manifests: list[tuple[Path, dict]]) -> dict[str, Any]:
    """Roll up per-cell, per-model, per-suite, and total cost."""
    cells: dict[str, dict] = {}
    models: dict[str, dict] = {}
    suites: dict[str, dict] = {}
    total_usd = 0.0
    priced = 0
    unpriced = 0

    for _, manifest in manifests:
        model, adapter, suite = _bucket(manifest)
        usd, source = manifest_cost_usd(manifest)
        if source:
            priced += 1
            total_usd += usd
        else:
            unpriced += 1

        key = f"{model}|{adapter}|{suite}"
        cells.setdefault(
            key,
            {
                "model": model,
                "adapter": adapter,
                "suite": suite,
                "usd": 0.0,
                "trials": 0,
                "priced_trials": 0,
            },
        )
        cells[key]["trials"] += 1
        models.setdefault(model, {"usd": 0.0, "trials": 0, "priced_trials": 0})
        models[model]["trials"] += 1
        suites.setdefault(suite, {"usd": 0.0, "trials": 0, "priced_trials": 0})
        suites[suite]["trials"] += 1
        if source:
            cells[key]["usd"] += usd
            cells[key]["priced_trials"] += 1
            models[model]["usd"] += usd
            models[model]["priced_trials"] += 1
            suites[suite]["usd"] += usd
            suites[suite]["priced_trials"] += 1

    return {
        "total_trials": len(manifests),
        "priced_trials": priced,
        "unpriced_trials": unpriced,
        "total_usd": round(total_usd, 6),
        "per_model": models,
        "per_suite": suites,
        "per_cell": cells,
    }


def write_summary(root: Path | str, summary: dict, *, name: str = "cost-summary.json") -> Path:
    """Write the cost summary under root; returns the written path."""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    path = root / name
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(summary, indent=2) + "\n")
    tmp.replace(path)
    return path
