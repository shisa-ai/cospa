# coding-eval

Clean-room harness for evaluating small/local coding models across agent
harness variants on **Aider Polyglot** and **Terminal-Bench**. The harness
does not serve models; it consumes provider definitions from `~/.pi/agent/models.json`
and writes durable results under `results/`.

## What we're measuring

The single variable we want to isolate is **scaffold fit** — how well the
agent's context engineering (system prompt, tool descriptions, skill
selection, recovery behaviors) fits a small model's capabilities.

Harness variants, same agent loop, same model:

| Adapter | What it is |
|---|---|
| `pi_vanilla` | `pi --no-extensions` — 4 tools, ~1K-token prompt |
| `pi_devstack` | devstack pi profile (curated extensions + skills) |
| `little_coder` | little-coder launcher (pi + 20 ext + 30 skills) |
| `pi_superpowers` | `pi` plus the benchmark-safe Superpowers skill subset |
| `little_coder_superpowers` | `little-coder` plus the same benchmark-safe skills |

## Quick start

```bash
# 1. Verify environment
bash scripts/setup.sh

# 2. Check which models are alive (uses baseUrl/apiKey from ~/.pi/agent/models.json)
bash scripts/check-models.sh

# 3. Run a smoke test (5 problems, pi_vanilla, Aider Polyglot)
mamba run -n coding-eval python harness/runner.py \
  --suite aider_polyglot \
  --adapter pi_vanilla \
  --model local/ornith-1.0-35b \
  --problems 5 \
  --k 1

# 4. View results
mamba run -n coding-eval python view-scores/server.py
```

The viewer serves `http://localhost:8000` and reads the `results/` tree cold.
It also finds named smoke-run wrappers such as
`results/e2e-smoke-terminal-bench-20260704-1100/...`.

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

Terminal-Bench runs through Harbor and Docker. If your shell was opened before
you were added to the `docker` group, use `sg docker -c '<command>'` or open a
new login shell before running Harbor-backed smoke tests.

## Model Reachability

`scripts/check-models.sh` reads model IDs from `configs/models.yaml`, then
resolves provider `baseUrl`, `apiKey`, and provider-native model names from
`~/.pi/agent/models.json`. It sends a 1-token OpenAI-compatible
`/chat/completions` request with `Authorization: Bearer <apiKey>` when a key is
configured. API keys are never printed.

The runner performs the same authenticated reachability check by default before
starting a matrix cell. Use `--skip-reachability` only for an intentional
offline/smoke run where you accept that risk.

## Parallel Runs

`scripts/run-matrix.sh` runs matrix cells sequentially. You can still run
multiple eval processes at the same time by launching independent
`harness/runner.py` commands, as long as they do not write the same
`results/<model>/<adapter>/<suite>/<task>/trial-<k>/` directory.

The safest pattern is one wrapper results directory per concurrent process:

```bash
mamba run -n coding-eval python harness/runner.py \
  --suite aider_polyglot \
  --adapter pi_vanilla \
  --model local/ornith-1.0-35b \
  --problems 5 \
  --k 1 \
  --results-dir results/parallel/pi-vanilla &

mamba run -n coding-eval python harness/runner.py \
  --suite aider_polyglot \
  --adapter pi_devstack \
  --model local/ornith-1.0-35b \
  --problems 5 \
  --k 1 \
  --results-dir results/parallel/pi-devstack &

wait
```

The score viewer recursively discovers those wrapper directories. Avoid
running two processes against the same output directory and same matrix cell;
that will race on `trial-<k>` files. Terminal-Bench runs also share Docker and
model-serving capacity, so start with low concurrency and watch provider rate
limits.

## Reproducibility

Results are a pure directory tree — no database, re-scoreable without
re-running, partial runs compose by directory union. Every run records
model, adapter, sampling params, env hash, and timing in `manifest.json`.

## Benchmarks

- **Aider Polyglot** — 225 Exercism problems (C++, Go, Java, JS, Python, Rust). Cheap signal.
- **Terminal-Bench** — canonical agentic eval via Harbor. Wall-clock probe first.

## Current Verified State

- Python tests: `mamba run -n coding-eval python -m pytest -q` reports
  `88 passed`.
- Shell harness: `bash tests/scripts/run_all.sh` reports `22` assertions
  passed.
- Terminal-Bench Docker smoke: `local/ornith-1.0-35b` + `pi_vanilla` +
  `hello-world` completed through Harbor 0.16 with `verifier_result.rewards.reward: 1.0`.
- Smoke artifact:
  `results/e2e-smoke-terminal-bench-20260704-1100/local%2Fornith-1.0-35b/pi_vanilla/terminal_bench/hello-world/trial-1/`.
