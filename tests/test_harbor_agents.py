from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent



def test_pi_model_arg_resolves_alias_through_env(tmp_path, monkeypatch):
    """When the provider env carries a resolved MODEL_ID, pi's --model arg
    uses provider/resolved-id so container-side matching cannot miss; raw
    ids pass through unchanged when env is absent or provider differs."""
    import ast
    import os

    # harbor_agents imports heavy optional deps; extract the pure helper.
    source = (PROJECT_ROOT / "harness" / "harbor_agents.py").read_text()
    tree = ast.parse(source)
    fn = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "_resolve_pi_model_arg"
    )
    namespace = {"os": os}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), "<helper>", "exec"), namespace)
    resolve = namespace["_resolve_pi_model_arg"]

    monkeypatch.setenv("CODING_EVAL_PI_PROVIDER_NAME", "local")
    monkeypatch.setenv("CODING_EVAL_PI_PROVIDER_MODEL_ID", "Qwen3.8-27B")
    assert resolve("local/qwen3.8-27b-fp8-block") == "local/Qwen3.8-27B"
    # different provider: untouched
    assert resolve("shisa/ornith-35b-fp8-block") == "shisa/ornith-35b-fp8-block"
    monkeypatch.delenv("CODING_EVAL_PI_PROVIDER_MODEL_ID")
    assert resolve("local/qwen3.8-27b-fp8-block") == "local/qwen3.8-27b-fp8-block"
