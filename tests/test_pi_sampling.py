

def test_find_pi_model_matches_aliases(tmp_path, monkeypatch):
    """models.json entries can carry aliases; a cospa id matching an alias
    resolves to the entry's id (the wire name)."""
    import json
    from harness.adapters.sampling import _find_pi_model
    models_json = tmp_path / "models.json"
    models_json.write_text(json.dumps({
        "providers": {
            "local": {
                "baseUrl": "http://x/v1",
                "models": [
                    {"id": "Qwen3.8-27B", "aliases": ["qwen3.8-27b-fp8-block"]},
                ],
            }
        }
    }))
    hit = _find_pi_model("local/qwen3.8-27b-fp8-block", models_json)
    assert hit is not None and hit["id"] == "Qwen3.8-27B"
    assert _find_pi_model("local/qwen3.8-27b", models_json)["id"] == "Qwen3.8-27B"
    assert _find_pi_model("local/unknown-model", models_json) is None
