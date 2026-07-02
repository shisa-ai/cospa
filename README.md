# coding-eval

Clean-room harness for evaluating small local coding models across agent
harness variants on **Aider Polyglot** and **Terminal-Bench**.

## What we're measuring

The single variable we want to isolate is **scaffold fit** — how well the
agent's context engineering (system prompt, tool descriptions, skill
selection, recovery behaviors) fits a small model's capabilities.

Three harnesses, same agent loop, same model:

| Adapter | What it is |
|---|---|
| `pi_vanilla` | `pi --no-extensions` — 4 tools, ~1K-token prompt |
| `pi_devstack` | devstack pi profile (curated extensions + skills) |
| `little_coder` | little-coder launcher (pi + 20 ext + 30 skills) |

## Quick start

```bash
# 1. Verify environment
bash scripts/setup.sh

# 2. Check which models are alive
bash scripts/check-models.sh

# 3. Run a smoke test (5 problems, pi_vanilla, Aider Polyglot)
mamba run -n coding-eval python harness/runner.py \
  --suite aider_polyglot \
  --adapter pi_vanilla \
  --model nvidia/nemotron-3-ultra-550b-a55b \
  --problems 5 \
  --k 1

# 4. View results
python view-scores/server.py
```

## Directory layout

```
harness/          # Core runner + adapter + suite implementations
  adapters/       # pi_vanilla, pi_devstack, little_coder
  suites/         # aider_polyglot, terminal_bench
  runner.py       # Single load-bearing component
configs/          # models.yaml, suite configs
scripts/          # setup.sh, check-models.sh
results/          # Generated per-run (gitignored)
view-scores/      # Score viewer (static HTML + server)
vendor/           # Vendored datasets (TB, Polyglot)
```

## Environments

All Python code runs inside the `coding-eval` mamba environment
(`python=3.12`). Use `mamba run -n coding-eval <cmd>` or
`conda activate coding-eval` before invoking any harness script.

## Reproducibility

Results are a pure directory tree — no database, re-scoreable without
re-running, partial runs compose by directory union. Every run records
model, adapter, sampling params, env hash, and timing in `manifest.json`.

## Benchmarks

- **Aider Polyglot** — 225 Exercism problems (C++, Go, Java, JS, Python, Rust). Cheap signal.
- **Terminal-Bench** — canonical agentic eval via Harbor. Wall-clock probe first.
