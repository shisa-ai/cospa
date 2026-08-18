

def test_wire_model_ref_resolves_aliases(tmp_path, monkeypatch):
    """--model references resolve through models.json aliases to the wire
    id; private sandbox configs then exact-match container/sandbox side."""
    import json
    import importlib.util
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    spec = importlib.util.spec_from_file_location(
        "subproc_wire_test", root / "harness" / "subprocess_utils.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    models = tmp_path / "models.json"
    models.write_text(json.dumps({
        "providers": {"local": {"baseUrl": "http://x/v1", "models": [
            {"id": "Qwen3.8-27B", "aliases": ["qwen3.8-27b-fp8-block"]},
        ]}}
    }))
    assert mod._wire_model_ref("local/qwen3.8-27b-fp8-block", models) == (
        "local/Qwen3.8-27B"
    )
    assert mod._wire_model_ref("local/qwen3.8-27b", models) == "local/Qwen3.8-27B"
    assert mod._wire_model_ref("local/unknown-x", models) == "local/unknown-x"
    assert mod._wire_model_ref(None, models) is None
