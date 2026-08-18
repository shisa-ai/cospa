"""Cost rollup from trial manifests (RUN-MANAGEMENT P5)."""

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from harness.cost_summary import (  # noqa: E402
    aggregate,
    iter_manifests,
    manifest_cost_usd,
    write_summary,
)


def _manifest(model_id, *, cost_record=None, usage=None, adapter="pi_vanilla",
              suite="aider_polyglot"):
    model = {"id": model_id}
    if cost_record is not None:
        model["cost"] = cost_record
    m = {
        "model": model,
        "model_id": model_id,
        "adapter": {"name": adapter},
        "suite": {"name": suite},
        "token_usage": usage or {},
    }
    if cost_record is not None and usage:
        from harness.cost import trial_cost
        computed = trial_cost(model, usage)
        if computed is not None:
            m["cost"] = computed
    return m


def _write_manifest(root: Path, *rel, manifest: dict):
    path = root.joinpath(*rel)
    path.mkdir(parents=True, exist_ok=True)
    (path / "manifest.json").write_text(json.dumps(manifest))
    return path / "manifest.json"


def _usage(prompt, completion, cached=0):
    return {
        "status": "observed",
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "cached_tokens": cached,
        "cache_creation_tokens": 0,
        "total_tokens": prompt + completion + cached,
    }


COST = {"input": 5.0, "output": 30.0, "cacheRead": 0.5, "cacheWrite": 0}


def test_manifest_cost_usd_prefers_runtime_record():
    m = _manifest("codex/gpt-5.5", cost_record=COST, usage=_usage(1000, 500, 200))
    assert m["cost"]["usd"] == 0.0201
    usd, source = manifest_cost_usd(m)
    assert usd == 0.0201 and source == "manifest"
    # Historical manifest without a runtime record is derived on the fly.
    m2 = _manifest("codex/gpt-5.5", usage=_usage(1000, 500, 200))
    m2["model"]["cost"] = COST  # cost config present, but no runtime record
    usd2, source2 = manifest_cost_usd(m2)
    assert usd2 == 0.0201 and source2 == "derived"
    # Unpriced trial (no cost table).
    m3 = _manifest("local/free-model", usage=_usage(10, 10))
    usd3, source3 = manifest_cost_usd(m3)
    assert usd3 == 0.0 and source3 is None


def test_aggregate_rolls_up_cells_models_suites(tmp_path):
    root = tmp_path / "run"
    _write_manifest(root, "model-a", "cell1", manifest=_manifest(
        "codex/gpt-5.5", cost_record=COST, usage=_usage(1000, 500, 200)))
    # Historical cell: cost config present, but no runtime cost record -> derived.
    hist = _manifest("codex/gpt-5.5", usage=_usage(1000, 500, 200))
    hist["model"]["cost"] = COST
    _write_manifest(root, "model-a", "cell2", manifest=hist)
    _write_manifest(root, "model-b", "cell3", manifest=_manifest(
        "zai/glm-5.2", usage=_usage(10, 10)))  # unpriced (no cost config)

    manifests = iter_manifests(root)
    summary = aggregate(manifests)

    assert summary["total_trials"] == 3
    assert summary["priced_trials"] == 2
    assert summary["unpriced_trials"] == 1
    assert summary["total_usd"] == 0.0402  # 2 x 0.0201

    assert summary["per_model"]["codex/gpt-5.5"]["usd"] == 0.0402
    assert summary["per_model"]["codex/gpt-5.5"]["trials"] == 2
    assert summary["per_model"]["zai/glm-5.2"]["trials"] == 1
    assert summary["per_suite"]["aider_polyglot"]["trials"] == 3
    cell_key = "codex/gpt-5.5|pi_vanilla|aider_polyglot"
    assert summary["per_cell"][cell_key]["priced_trials"] == 2


def test_write_summary_persists(tmp_path):
    root = tmp_path / "run"
    _write_manifest(root, "trial-1", manifest=_manifest(
        "codex/gpt-5.5", cost_record=COST, usage=_usage(1000, 500, 200)))
    summary = aggregate(iter_manifests(root))
    path = write_summary(root, summary)
    assert path.name == "cost-summary.json"
    data = json.loads(path.read_text())
    assert data["total_usd"] == 0.0201
    assert data["priced_trials"] == 1
