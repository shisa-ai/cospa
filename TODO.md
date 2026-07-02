## Models

Local
- Ornith

AIAnd
- Qwen

GLM
- GLM 5.2

Minimax
- Minimax 3
- Minimax 2.7

Nvidia
- Stepfun 3.7 Flash
- Nemotron 550B

## Procedure

**Restating concretely:** You're evaluating small local coding models (presumably served via your vLLM/SGLang/hipEngine stack) and want to compare two agent harnesses — Pi (Mario Zechner's minimal coding agent) and "Little Coder" — on agentic tool-calling/coding ability, using Terminal-Bench as the eval. You also want (a) a shorter, multi-language coding benchmark that isn't SWE-bench (which is Python-only and slow), and (b) a step-by-step setup for running both harnesses against the same models, including an ablation where you inject the Superpowers skills library into the harness to see if it moves the score. Let me verify current state of these tools first.Good news: this comparison is unusually clean, because little-coder doesn't fork pi — pi is a plain dependency, and everything little-coder-specific lives under `.pi/extensions/`, `skills/`, and `benchmarks/`. So "Pi vs little-coder" is literally a scaffold ablation on the same agent loop: pi is the minimal substrate with four built-in tools (read/write/edit/bash) and a ~1000-token system prompt, and little-coder is pi + 20 extensions + 30 skill markdown files + a Python benchmark harness. Same loop, same tools API, different context engineering — exactly the variable you want isolated for small-model testing.

**Benchmark choice.** For the short multi-language test: **Aider Polyglot** (225 Exercism problems across C++, Go, Java, JS, Python, Rust). It's the canonical answer to "SWE-bench but polyglot and fast," and little-coder already ships a runner for it — it's the benchmark behind the 45.56% vs 19.11% matched-model vanilla Aider baseline result on Qwen3.5-9B. For agentic/tool-calling, note there's a cheaper tier below TB 2.0: Terminal-Bench-Core v0.1.1 is a smaller subset — good for iteration before committing to full TB 2.0 runs (which at k=5 on a small local model will take a long while).

**Step-by-step:**

1. **Serve the model** on an OpenAI-compat endpoint (your vLLM/SGLang boxes). Both harnesses speak it: little-coder's llama-cpp-provider registers `llamacpp/*` and `ollama/*` as OpenAI-compat providers with `LLAMACPP_BASE_URL`/`OLLAMA_BASE_URL` env overrides — point `LLAMACPP_BASE_URL` at vLLM and use `--model llamacpp/<served-name>`. Pi supports 15+ providers including generic OpenAI-compat/Ollama the same way. Critical for the comparison: identical sampling params and tool-call parser config on the server side, since tool-call format mangling (vLLM's `--tool-call-parser` choice) will dominate differences otherwise.

2. **Install both.** Pi: `npm install -g --ignore-scripts @earendil-works/pi-coding-agent`. little-coder needs Node ≥ 22.19.0; clone, `npm install`, `npm link` (clone rather than npm package — the benchmarks harness is dev-only and not shipped with the npm package).

3. **Aider Polyglot first** (cheap signal): run from a clone with `python3 benchmarks/aider_polyglot.py` for the little-coder arm. For the vanilla-pi arm, easiest path is running the same script but launching pi with `--no-extensions` and none of the bundled set wired in — since little-coder's launcher is just pi + a curated extension list, the "vanilla" condition is pi with that list emptied.

4. **Terminal-Bench 2.0** via Harbor. Both have adapters. Pi: `uv tool install harbor`, then `harbor run -d terminal-bench@2.0 --agent-import-path pi_terminal_bench:PiAgent -m <model> -n 4` from badlogic/pi-terminal-bench. little-coder: `--agent-import-path benchmarks.harbor_adapter.little_coder_agent:LittleCoderAgent`. One landmine: there's a Harbor `upload_dir` bug where if the agent creates a `/tests` directory during the task, the verifier's files land at `/tests/tests/test.sh` — the patch must be applied before running evals. Use k=3–5 trials; little-coder's own leaderboard numbers had ±2–3 point error bars, so single runs won't separate the harnesses.

5. **Superpowers arm.** Pi is now an officially listed Superpowers harness (Claude Code, Antigravity, Codex, Cursor, Copilot CLI, Kimi Code, OpenCode, Pi), though pi support is framed as a minimal compatibility baseline since pi core lacks built-in subagents that some Superpowers behaviors assume. Options: official repo via `pi install https://github.com/obra/superpowers` plus @uadgj/pi-superpowers-support, which adds the TodoWrite/Task/Skill tools Superpowers expects, or the leaner adaptation `pi install git:github.com/coctostan/pi-superpowers`. For the little-coder arm, remember the launcher runs pi with `--no-extensions`, so globally pi-installed packages won't load — you add extensions by dropping a directory into `.pi/extensions/` or passing `-e /path/to/ext/index.ts`.

Two caveats on the Superpowers ablation. First, it's a workflow methodology tuned for frontier models — the mandatory skill-check protocol and brainstorming/clarifying-question flows can stall headless benchmark runs (no user to answer questions) and burn context on a 32K small model. You may want to strip the interactive skills and keep only systematic-debugging/verification-before-completion for the bench condition. Second, it partially duplicates what little-coder already does (its skill-inject extension does priority-based skill card selection — error recovery > recency > intent — within a token budget), so the interesting 2×2 is really: vanilla pi, pi+superpowers, little-coder, little-coder+superpowers-debugging-skills. My prediction, given the scaffold-fit thesis little-coder is built on: Superpowers helps vanilla pi a little on TB (recovery discipline) and hurts on Polyglot (token overhead per turn on a small context), while little-coder's targeted per-turn injection beats both — but that's exactly what's worth measuring.
