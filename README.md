# cospa

*The cost-performance benchmark for coding agents.*

**Cospa** takes its name from the Japanese **コスパ** (*cospa*) — the
common clipping of **コストパフォーマンス** ("cost performance"), a word
used everywhere in Japanese product reviews, electronics shopping, and
everyday decision-making to mean *value for money*: how much capability
or quality you get per unit of cost. It is exactly the framing this
project brings to coding-agent evaluation. Most leaderboards rank models
by raw pass rate and treat cost as a footnote, if they report it at all.
Cospa treats the two axes as equally first-class — **raw capability
measured alongside what you pay for it** — so a result is only "good"
when the capability-per-dollar is good.

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
./run \
  --suite aider_polyglot \
  --adapters pi_vanilla \
  --models local/ornith-1.0-35b \
  --problems 5 \
  --k 1

# 4. View scores in the terminal
./view

# Optional browser UI
./view serve
```

`./view` prints a colored terminal table with `Score`, `Passed/Total`,
total cost, cost per completed task, and passed tasks per dollar.
`./view serve` starts the browser viewer at `http://localhost:8000`. Both read
the `results/` tree cold and find named smoke-run wrappers such as
`results/e2e-smoke-terminal-bench-20260704-1100/...`.

By default, CLI runs write to an isolated run wrapper:

```text
results/runs/<encoded-model>-<run-id>/<encoded-model>/<adapter>/<suite>/<task>/trial-<k>/
```

This makes repeated or concurrent invocations independent unless you
intentionally provide a shared `--results-dir`.

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

## Running Hugging Face Models

The harness does not load Hugging Face checkpoints directly. Run the checkpoint
behind an OpenAI-compatible `/v1` endpoint, then register that endpoint as a pi
provider. For example, a local vLLM-style server might look like this:

```bash
python -m vllm.entrypoints.openai.api_server \
  --model Qwen/Qwen2.5-Coder-7B-Instruct \
  --served-model-name Qwen/Qwen2.5-Coder-7B-Instruct \
  --host 0.0.0.0 \
  --port 8000
```

Add a provider to `~/.pi/agent/models.json`:

```json
{
  "providers": {
    "hf": {
      "baseUrl": "http://127.0.0.1:8000/v1",
      "apiKey": "EMPTY",
      "models": [
        { "id": "Qwen/Qwen2.5-Coder-7B-Instruct" }
      ]
    }
  }
}
```

For Aider Polyglot, `http://127.0.0.1:8000/v1` is fine. For
Terminal-Bench, the agent runs inside Docker, so use an address reachable from
the task container instead. On Linux Docker that is usually the bridge gateway,
for example `http://172.17.0.1:8000/v1`; on Docker Desktop,
`http://host.docker.internal:8000/v1` is usually the right value. Keep the
server bound to `0.0.0.0` when using those addresses.

Then add the model to `configs/models.yaml` with the provider prefix:

```yaml
models:
  - id: hf/Qwen/Qwen2.5-Coder-7B-Instruct
```

Entries may also include benchmark accounting metadata such as
`context_window`, `max_tokens`, `reasoning`, and per-million-token `cost`.
That repo metadata is used in manifests and usage backfill when the local pi
provider config is missing pricing or carries a development stub.

Verify and run:

```bash
bash scripts/check-models.sh

mamba run -n coding-eval python harness/runner.py \
  --suite aider_polyglot \
  --adapter pi_vanilla \
  --model hf/Qwen/Qwen2.5-Coder-7B-Instruct \
  --problems 5 \
  --k 1
```

The same model id can be used with `--suite terminal_bench`; the Harbor custom
agent copies the selected provider config into the task container before it
runs. The provider `baseUrl` still has to be reachable from inside Docker.

Use the same pattern for SGLang, llama.cpp, Ollama, or any other HF-serving
stack as long as it exposes OpenAI-compatible chat completions.

## Runner Output

Interactive `harness/runner.py` runs print a lightweight elapsed-time heartbeat
while each trial is executing. Non-interactive runs, background jobs, and log
files stay clean; detailed adapter output is still written under each trial's
`out/` directory.

## Viewing Scores

Use the root viewer first:

```bash
./view                    # colored terminal score/cost table
./view -v                 # add status, timing, token counts, and $/M pricing
./view --show-ci          # add Wilson 95% CI when you need uncertainty bounds
./view --no-cache         # force a cold scan for debugging
./view json --pretty      # machine-readable rows
./view serve              # browser UI at http://localhost:8000
```

The default score is task-level pass@k majority. For tiny smoke runs, confidence
intervals are deliberately not shown in the primary terminal/browser table
because `1/1` and `5/5` runs produce wide bounds that obscure the useful
operator signal.

The terminal/API score view keeps a local cache at `.cache/view-scores.json`.
The cache key includes the visible result set, each trial manifest/verdict
mtime and size, and filter options, so completed trials and new run output
invalidate automatically.

## Parallel Runs

`scripts/run-matrix.sh` runs matrix cells sequentially and passes one run id to
all cells in that matrix invocation. Individual `harness/runner.py` CLI
invocations are also parallel-safe by default because each one gets a unique
model-prefixed run wrapper under `results/runs/`.

You can provide a stable `--run-id` when you want a readable wrapper name:

```bash
mamba run -n coding-eval python harness/runner.py \
  --suite aider_polyglot \
  --adapter pi_vanilla \
  --model local/ornith-1.0-35b \
  --problems 5 \
  --k 1 \
  --run-id smoke-pi-vanilla &

mamba run -n coding-eval python harness/runner.py \
  --suite aider_polyglot \
  --adapter pi_devstack \
  --model local/ornith-1.0-35b \
  --problems 5 \
  --k 1 \
  --run-id smoke-pi-devstack &

wait
```

The score viewer recursively discovers those wrappers. Supplying
`--results-dir` disables the default wrapper and writes exactly to that root;
use it only for intentional merges. Avoid running two processes against the
same explicit output directory and same matrix cell, because that will race on
`trial-<k>` files. Terminal-Bench runs also share Docker and model-serving
capacity, so start with low concurrency and watch provider rate limits.

For a full matrix with a stable wrapper name:

```bash
./run --run-id 20260704-smoke --problems 5 --k 1
```

## Reproducibility

Results are a pure directory tree — no database, re-scoreable without
re-running, partial runs compose by directory union. Every run records
model, adapter, sampling params, model limits/pricing when available, env
hash, timing, and token/cost usage in `manifest.json`. pi-backed runs also
copy the raw response trace to `out/pi_session.jsonl` for audit/backfill.
Terminal-Bench agents first export container-side pi traces into Harbor job
artifacts, then the runner/backfill copies those traces into the same
`out/pi_session.jsonl` location.

## Benchmarks

- **Aider Polyglot** — 225 Exercism problems (C++, Go, Java, JS, Python, Rust). Cheap signal.
- **Terminal-Bench** — canonical agentic eval via Harbor. Wall-clock probe first.

## Current Verified State

- Python tests: `mamba run -n coding-eval python -m pytest -q` reports
  `100 passed`.
- Shell harness: `bash tests/scripts/run_all.sh` reports `38` assertions
  passed.
- Setup now verifies `little-coder`, installs it with `npm install -g
  little-coder` when absent, and warns if `little-coder --list-models` cannot
  read provider config.
- Terminal-Bench Docker smoke: `local/ornith-1.0-35b` + `pi_vanilla` +
  `hello-world` completed through Harbor 0.16 with `verifier_result.rewards.reward: 1.0`.
- Smoke artifact:
  `results/e2e-smoke-terminal-bench-20260704-1100/local%2Fornith-1.0-35b/pi_vanilla/terminal_bench/hello-world/trial-1/`.
- Provider Aider Polyglot smoke run `provider-smoke-20260704T023522Z`
  completed with `pi_vanilla`, `--problems 5`, `--k 1`: local Ornith `4/5`,
  NVIDIA Nemotron `2/5`, and Zai GLM `4/5`.
- Little-coder Ornith smoke run `little-coder-ornith-smoke-20260704T0550Z`
  completed with `little_coder`, `--problems 5`, `--k 1`: local Ornith `5/5`.
