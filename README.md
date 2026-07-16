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
harness variants with a cost-aware portfolio: the in-progress **`aider_cospa`**
contract protocol, **Terminal-Bench Core 0.1.1**, the **SWE Atlas 12-task
pilot**, a no-tool **BigCodeBench-Hard Instruct pilot**, and later
validity-gated repository/feature suites. The harness does not serve models; it
consumes provider definitions from
`~/.pi/agent/models.json` and writes durable results under `results/`.

## What we're measuring

The primary variable we want to isolate is **scaffold fit** — how well the
agent's context engineering (system prompt, tool descriptions, skill
selection, recovery behaviors) fits a small model's capabilities.
BigCodeBench is a separate one-generation capability anchor, not a scaffold
variant.

Harness variants, same agent loop, same model:

| Adapter | What it is |
|---|---|
| `pi_vanilla` | `pi --no-extensions` — 4 tools, ~1K-token prompt |
| `pi_devstack` | devstack pi profile (curated extensions + skills) |
| `little_coder` | little-coder launcher (pi + 20 ext + 30 skills) |
| `pi_superpowers` | vanilla pi plus the benchmark-safe Superpowers skill subset |
| `pi_devstack_superpowers` | devstack extensions plus the same benchmark-safe skills |
| `little_coder_superpowers` | `little-coder` plus the same benchmark-safe skills |

**OpenCode is not implemented or registered as a Cospa adapter.** Historical
qualification notes and an interrupted campaign scaffold do not constitute a
supported benchmark arm.

## Evaluation protocol

Aider's 225 Exercism tasks are a useful multilingual source corpus, not Cospa's
final protocol. Aider selected them because at most three of seven 2024 models
solved each task, and its canonical retry/test-feedback loop conflates learning
the contract from the grader with implementing a public contract.

Cospa's target **`aider_cospa`** protocol instead provides the complete public
API/ABI and behavioral contract, gives the agent full freedom inside one
isolated workspace episode, keeps behavioral tests and reference solutions
hidden, and verifies only after the episode with no test-feedback retry.
Independent `k>1` trials restart from pristine workspaces. The primary panel
will be approximately 50% repeated concepts across languages and 50%
language-specific tasks; reports will include task-, language-, and
concept-weighted scores.

The existing `aider_polyglot` command is currently the isolated source-corpus
implementation: it hides tests and references, but it must not be relabeled
`aider_cospa` until all 225 contracts have been reviewed against their hidden
assertions. `aider_canonical` will remain an optional, separately scored legacy
comparator. See [`docs/EVALS.md`](docs/EVALS.md) for the normative protocol,
methodology review, candidate portfolio, and runtime estimates.

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
  adapters/       # agentic variants + bigcodebench_openai
  suites/         # Aider, Terminal-Bench, SWE Atlas, BigCodeBench
  runner.py       # Single load-bearing component
configs/          # models.yaml, suite configs
scripts/          # setup.sh, check-models.sh
results/          # Generated per-run (gitignored)
view-scores/      # Score viewer (static HTML + server)
vendor/           # Vendored datasets (TB, SWE Atlas, Polyglot)
```

## Environments

All Python code runs inside the `cospa` mamba environment
(`python=3.12`). Use `mamba run -n cospa <cmd>` or
`conda activate cospa` before invoking any harness script.

Aider Polyglot adapters require Linux bubblewrap (`bwrap`) and socat. Each
trial gets an empty-root namespace containing only its writable workdir,
selected system/language runtimes, a private pi config for the selected model,
disposable dependency/browser caches, and its own telemetry session. Public
networking is disabled; a Unix-socket relay exposes only the selected model
endpoint. Shared repositories, `vendor/`, `results/`, other home-directory
state, and prior pi sessions are absent. Model-written code is graded in a
second workdir-only namespace with no network access. The harness fails closed
if it cannot construct either boundary.

Java exercises use the benchmark's Gradle 8.7 wrapper and require JDK 21 in the
`cospa` environment (`mamba install -n cospa openjdk=21`). JavaScript, Java,
and Rust dependencies are prefetched before the agent starts, then both agent
and verifier use only the warmed read-only/disposable caches.

Terminal-Bench Core is pinned to the 80-task `0.1.1` release at upstream commit
`91e10457b5410f16c44364da1a34cb6de8c488a5`. SWE Atlas is pinned at
`2cac47d64a9123d915b8f6f6f53763391920f574`, with the selected 12 task IDs and
strata in `configs/swe_atlas_pilot12.json`. `scripts/setup.sh` checks out both
commits detached and verifies Docker Buildx, which Harbor needs for phase-scoped
network isolation. Their runs go through Harbor and Docker. If your shell was
opened before you were added to the `docker` group, use
`sg docker -c '<command>'` or open a new login shell before running
Harbor-backed smoke tests.

Terminal-Bench task containers start with an empty pi home. For
`pi_devstack` and `pi_devstack_superpowers`, the harness therefore bind-mounts
a read-only devstack profile and activates its package cache before running the
agent. The profile defaults to `~/.pi/agent`, or can be pinned with
`CODING_EVAL_DEVSTACK_PROFILE_DIR`; it must contain `npm/`, `git/`, and a
sanitized `settings.json`. For comparable long runs, use an immutable snapshot
whose settings contain only the intended package sources and no auth/model
files. Headless-incompatible resources can be disabled with pi package filters
(for example, an extension that downloads a browser or assumes a TUI).

Terminal-Bench image build and agent install retain public network access, but
the prompt-bearing agent phase is patched to Harbor `allowlist` mode for only
the model host. Runs fail closed unless a local migrated `task.toml` can carry
that policy, and also refuse explicit `main` Compose networking that bypasses
Harbor's sidecar. This does **not** yet make the full 80-task campaign clean:
public-runtime tasks conflict with model-only egress, and the shared verifier
retains public network/hidden-test exposure. Read `docs/PROTECTION-AUDIT.md`
before running or interpreting Terminal-Bench scores.

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

For Aider Polyglot, `http://127.0.0.1:8000/v1` is fine: the sandbox reaches it
only through cospa's model relay. For Terminal-Bench, the agent runs inside
Docker, so set a container-reachable override while keeping the normal host pi
configuration unchanged:

```bash
export CODING_EVAL_HARBOR_MODEL_BASE_URL=http://model-relay.internal:8000/v1
```

The override must use a dedicated, container-resolvable relay **hostname**;
loopback and IP-literal URLs fail closed. Do not point that hostname at a
general Docker host gateway: Harbor's hostname policy is not port- or
path-scoped, so every reachable service on the resolved address would enter the
model's network boundary. Use a relay host/container that exposes only the
selected model route. Harbor adds this hostname to the agent-phase allowlist;
URLs, ports, and paths are not themselves allowlist entries.

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

mamba run -n cospa python harness/runner.py \
  --suite aider_polyglot \
  --adapter pi_vanilla \
  --model hf/Qwen/Qwen2.5-Coder-7B-Instruct \
  --problems 5 \
  --k 1
```

The same model id can be used with `--suite terminal_bench`,
`--suite swe_atlas_pilot12`, or the currently gated
`--suite swe_polybench_verified`; the Harbor custom agent copies the selected
provider config into the task container before it runs. The provider `baseUrl`
still has to be reachable from inside Docker. SWE-PolyBench has a passing
representative offline gold/null gate, but do not launch model scoring until
all 38 selected images complete gold/null/repeat validation.

Use the same pattern for SGLang, llama.cpp, Ollama, or any other HF-serving
stack as long as it exposes OpenAI-compatible chat completions.

## Running the SWE Atlas pilot

SWE Atlas uses its upstream programmatic checks plus a pinned rubric judge. Set
judge credentials separately from the agent model credentials:

```bash
export SWE_ATLAS_JUDGE_API_KEY='<key>'
export SWE_ATLAS_JUDGE_BASE_URL='https://judge.example/v1'

./run \
  --suite swe_atlas_pilot12 \
  --adapters pi_vanilla \
  --models local/ornith-1.0-35b \
  --problems 1 \
  --k 1 \
  --run-id swe-atlas-pilot12-k1
```

The judge model is fixed to `anthropic/claude-opus-4-5-20251101`; changing only
credentials or endpoint must still route that exact model. The suite refuses to
start an agent without both judge values, preserving missing judge setup as an
infrastructure failure rather than an ordinary zero. Test Writing verdicts keep
rubric, manifest, and mutation subchecks; Q&A verdicts keep rubric coverage and
aggregate score alongside the strict reward.

This is a custom cost/reliability pilot, not a directly comparable leaderboard
run. The sorted pilot begins with Q&A tasks, so `--problems 1` is the current
single-Q&A smoke. Q&A still needs that judge-backed end-to-end evidence. Test
Writing remains experimental because its trusted verifier executes
model-authored tests beside hidden rubrics and judge credentials; do not call
those scores cheating-protected until candidate-code isolation is implemented.
See `docs/PROTECTION-AUDIT.md`. Do not launch the full adapter matrix first.

## Running the BigCodeBench-Hard pilot

BigCodeBench intentionally bypasses the coding-agent scaffold. Its dedicated
adapter sends one user message with no system prompt or tools, requests one
greedy sample, preserves the raw completion, and runs upstream sanitization
plus calibrated scoring in the pinned network-disabled verifier image:

```bash
mamba run -n cospa python harness/runner.py \
  --suite bigcodebench_hard_instruct \
  --adapter bigcodebench_openai \
  --model shisa/ornith-35b-fp8-block \
  --problems 1 \
  --k 1
```

The first verifier pull is about 15 GB. This protocol records zero tool calls
by construction and must not be substituted into the agent scaffold matrix.

For a scaffold comparison over the same public pilot15 and pinned hidden
verifier, use the separately labeled workspace adaptation. It directs the
agent to implement `solution.py` and uses normal model-card sampling and tool
access:

```bash
mamba run -n cospa python harness/runner.py \
  --suite bigcodebench_hard_agentic \
  --adapter pi_vanilla \
  --model local/qwen3.8-27b \
  --thinking xhigh \
  --concurrency 8 \
  --k 1
```

Run the same suite with `pi_devstack` for the matched scaffold arm. Agentic
scores are a Cospa adapter diagnostic and are never merged with official
BigCodeBench Instruct Pass@1 rows.

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
mamba run -n cospa python harness/runner.py \
  --suite aider_polyglot \
  --adapter pi_vanilla \
  --model local/ornith-1.0-35b \
  --problems 5 \
  --k 1 \
  --run-id smoke-pi-vanilla &

mamba run -n cospa python harness/runner.py \
  --suite aider_polyglot \
  --adapter pi_devstack \
  --model local/ornith-1.0-35b \
  --problems 5 \
  --k 1 \
  --run-id smoke-pi-devstack &

wait
```

The score viewer recursively discovers those wrappers. A single runner can
also bound parallel task trials with `--concurrency N`; each slot owns one
complete task trial including infrastructure retries:

```bash
mamba run -n cospa python harness/runner.py \
  --suite swe_polybench_verified \
  --adapter pi_vanilla \
  --model local/deepseek-v4-flash-0731 \
  --concurrency 8 \
  --k 1 \
  --run-id polybench-c8
```

Supplying `--results-dir` disables the default wrapper and writes exactly to
that root; use it only for intentional merges. Avoid running two processes
against the same explicit output directory and same matrix cell, because that
will race on `trial-<k>` files. Harbor-backed suites share Docker and model-
serving capacity, and SWE Atlas also uses an external judge, so advance
concurrency only after measuring endpoint, host, and verifier pressure.

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

Aider results created before the 2026-08-12 hidden-test cutover are not clean
capability evidence. Before 2026-07-16, agents could also see reference
artifacts and shared state; between that isolation cutover and 2026-08-12, the
exact behavioral test files were still copied into agent workspaces. Preserve
any such artifacts only for protocol audit and never mix them with
post-cutover scores.

## Benchmarks

- **`aider_cospa` / `aider_cospa_full` (in design)** — reviewed contract-visible, behavior-hidden panels derived from 225 C++/Go/Java/JavaScript/Python/Rust source tasks. The current `aider_polyglot` suite is only their hidden-test substrate pending the 225-task contract audit.
- **`aider_canonical` (planned, optional)** — exact legacy protocol comparator; scores remain separate.
- **Terminal-Bench Core 0.1.1** — pinned 80-task external anchor via Harbor. Wall-clock probe first.
- **SWE Atlas pilot12** — eight Test Writing + four Codebase Q&A tasks, balanced across Go, Python, C, and TypeScript. Cost/reliability gate before `k=2`.
- **BigCodeBench-Hard Instruct pilot15** — pinned one-sample, no-tool Python generation anchor with upstream calibrated scoring; kept separate from agentic scores.
- **Repository/feature portfolio (candidate)** — Multi-SWE-bench Flash, SWE-bench Multilingual, SWE-PolyBench, and FeatureBench enter only after the validity/runtime bake-off in `docs/EVALS.md`.

## Current Verified State

- Python tests: `mamba run -n cospa python -m pytest -q` reports 416 passed.
  `bash tests/scripts/run_all.sh` also passes all shell checks.
- Focused BigCodeBench/lock tests report 34 passes; real offline verification
  passes all 15 gold tasks, rejects all 15 null tasks, and leaves no hidden
  dataset export in retained trial workdirs.
- Setup pins Terminal-Bench Core 0.1.1 and SWE Atlas pilot12, then verifies
  `little-coder`, installing it with `npm install -g little-coder` when absent
  and warning if `little-coder --list-models` cannot read provider config.
- SWE Atlas is `wired (unit test + real pinned artifact)`: all 12 public tasks
  discover and materialize with the declared workflow/language strata. A real
  rubric-scoring run still requires the pinned judge endpoint and is not yet
  claimed as end-to-end verified.
- BigCodeBench-Hard is `ready_smoke (real verifier)`: all 15 frozen gold
  solutions pass, all 15 null solutions fail, and the upstream ground-truth
  rate is 1.000 in the immutable offline evaluator. No target-model result is
  claimed yet.
- Terminal-Bench Docker smokes: `local/ornith-1.0-35b` + `hello-world`
  passed through Harbor 0.16 with both `pi_vanilla` and the mounted,
  sanitized `pi_devstack` profile.
- Devstack smoke artifact:
  `results/e2e-smoke-terminal-bench-devstack-profile-v5-20260716T034155Z/local%2Fornith-1.0-35b/pi_devstack/terminal_bench/hello-world/trial-1/`.
- Aider smoke scores produced before 2026-08-12 are protocol-contaminated and
  intentionally excluded from current capability claims. Post-cutover runs use
  hidden tests but remain named `aider_polyglot` until the contract audit is
  complete.

## License

Apache License 2.0. See `LICENSE`.
