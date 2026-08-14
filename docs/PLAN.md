# PLAN.md — cospa

> Clean-room harness for evaluating **small local coding models** across
> **agent harness variants** on **Aider Polyglot**, **Terminal-Bench Core**, and
> the pinned **SWE Atlas Q&A + Test Writing pilot**.
>
> Scope is deliberately narrow: no model serving, no vLLM/SGLang config, no
> training. Models are an *input* (provider IDs in `models.json`); results are
> an *output* (a scored directory tree). The thing we are measuring is the
> **harness**, on the theory that scaffold–model fit dominates raw model quality
> for small models (cf. *Honey, I Shrunk the Coding Agent*).

All Python code runs inside the `cospa` mamba environment
(`python=3.12`). Use `mamba run -n cospa <cmd>` or `conda activate
cospa` before invoking any harness script. The setup script (P2)
verifies the env exists and is on the right version.

---

## 0. Punchlist (do these, in order)

A linear, checkboxable list. Each item maps to a task in the TaskList. Do not
reorder — earlier items unblock later ones.

- [ ] **P1. Scaffold the repo.** Create directory layout (`harness/`,
      `configs/`, `scripts/`, `results/`, `view-scores/`). `.gitignore`
      for `results/` (keep one example), `node_modules/`, `.venv/`,
      `vendor/`. README stub.
- [ ] **P2. Install script (`scripts/setup.sh`).** Verifies pi (≥ some
      version), verifies the `cospa` mamba env (python=3.12) exists
      and is active, installs Harbor (`uv tool install harbor`), checks out
      Terminal-Bench Core 0.1.1 at commit `91e10457b5410f16c44364da1a34cb6de8c488a5`
      and SWE Atlas at `2cac47d64a9123d915b8f6f6f53763391920f574`,
      and clones Aider Polyglot under `vendor/`. **Does not** touch models
      or providers — model setup is a separate concern, by design.
- [ ] **P3. Models check (`scripts/check-models.sh`).** Reads model IDs
      from a `configs/models.yaml` (or `~/.pi/agent/models.json`), pings
      each provider with a 1-token completion, reports alive/dead +
      latency. No setup, no edits.
- [ ] **P4. Little Coder install.** `npm install -g little-coder`
      (published package is fine — benchmarks harness is *not* shipped,
      but we use our own harness here). Verify `little-coder --version`
      and `little-coder --list-models` sees our providers. Keep pi and
      little-coder as **separate launchers** — never let little-coder's
      `--no-extensions` bootstrap touch the canonical devstack pi install.
- [ ] **P5. Harness core: runner + manifest.** `harness/runner.py` takes
      `(suite, model, adapter, trial_k)` and runs *one task*: spawns the
      adapter as a subprocess, captures stdout/stderr/exit, runs the
      suite's verifier, writes
      `results/runs/<encoded-model>-<run-id>/<model>/<adapter>/<suite>/<task_id>/trial-<k>/{manifest.json,out/,verdict.json}`
      by default. Explicit `--results-dir` remains an exact output root for
      intentional merges.
      Manifest records: model id + provider, adapter id + version,
      model limits/pricing from pi config when available, sampling params
      including pinned thinking effort/budget, env hash, start/end time,
      token/cost usage, and behavioral telemetry. pi-backed runs preserve the
      raw pi JSONL response trace under `out/` and load a telemetry-only
      extension that records compact provider/message/tool boundary events.
      The runner rolls those events into each manifest: inference/tool/other
      timing, parallel-safe tool wall time, exact tool and behavior-category
      counts/times/errors, search activity, and slow/incomplete calls. Full
      tool arguments/results stay in the pi session trace. Legacy traces can
      backfill counts/types/errors/search examples, but are explicitly marked
      `counts_only` because exact timing cannot be reconstructed.
      This is the single load-bearing component of the harness.
- [ ] **P6. Adapter: `pi_vanilla`.** Launches `pi --no-extensions -m <model>`
      in headless mode against a task workdir. The baseline — pi's four
      built-in tools, ~1000-token system prompt, nothing else.
- [ ] **P7. Adapter: `pi_devstack`.** Launches the canonical devstack pi
      profile (whatever `pi-setup.sh` configures — extensions, skills,
      settings). This is "pi as we actually run it day-to-day."
- [ ] **P8. Adapter: `little_coder`.** Launches `little-coder -m <model>`.
      pi + 20 extensions + 30 skills, but the same loop and tools API.
- [ ] **P9. Suite: Aider Polyglot.** `harness/suites/aider_polyglot.py`
      loads the 225-problem dataset, materializes one problem per task
      into a workdir, runs the adapter, then grades via the existing
      Exercism test runner per language. **Do this suite first** — it's
      the cheap signal (~minutes per problem vs hours for TB).
- [ ] **P10. First end-to-end smoke.** One model (Nemotron 550B or
      Qwen 3.6 27B — whichever is alive), one adapter (`pi_vanilla`),
      one suite (Aider Polyglot), k=1 trial, **5 problems** only. Prove
      the manifest/verdict path works before scaling.
- [ ] **P11. Suite: Terminal-Bench.** `harness/suites/terminal_bench.py`
      wraps `harbor run` against the checked-in 80-task
      `terminal-bench-core==0.1.1` manifest and immutable upstream commit.
      Each adapter uses a distinct custom Harbor agent. Start with k=1 on a
      5-task slice to measure wall-clock before committing to full runs.
- [ ] **P11b. Suite: SWE Atlas pilot12.**
      `harness/suites/swe_atlas.py` runs a predeclared Harbor-native slice:
      eight Test Writing and four Codebase Q&A tasks, with three total tasks
      per Go/Python/C/TypeScript stratum. Preserve upstream verification,
      pin the rubric judge, and qualify cost/reliability at k=1 before k=2.
- [ ] **P12. Score viewer (`view-scores/`).** Static HTML + a tiny
      `server.py` that walks `results/` and renders a table:
      rows = `(model, adapter, suite)`, cells = pass-rate with CI,
      drill-down to per-task verdicts. Verbose terminal and HTML views expose
      weighted inference/tool percentages plus mean tool/search calls; score
      and task APIs retain aggregate exact tool/category maps, error/long-call
      counts, slowest calls, and per-trial behavior rollups. Missing legacy
      timing remains `-`, never inferred from ambiguous session timestamps.
      Borrow the *shape* from multieval's viewer; this is a clean-room write,
      not a port.
- [ ] **P13. Scale-up matrix run.** Full Aider Polyglot × {pi_vanilla,
      pi_devstack, little_coder} × {models in `configs/models.yaml`} ×
      k=3. Measure TB wall-clock first, then decide whether to run TB
      at k=3 or k=5 (TB runs are long; the TODO notes ±2–3pt error bars
      at k=5).
- [ ] **P14. Superpowers ablation (2×2).** Add adapters `pi_superpowers`
      and `little_coder_superpowers`. For bench runs, **strip interactive
      skill-check flows** (no user present to answer clarifying questions)
      and keep only systematic-debugging + verification-before-completion
      skills. 2×2 = {pi, little_coder} × {baseline, +superpowers-bench}.
      Optional / last — depends on TB timing (P11).
- [ ] **P15. Write up.** Results table, harness comparison, per-model
      findings. `RESULTS.md` at the repo root.

Defer / out of scope for v1: full Terminal-Bench 2.0 (use Core for now),
model serving automation, automated regression on every commit.

---

## 1. What we're measuring, and why

The single variable we want to isolate is **scaffold fit** — how well the
agent's context engineering (system prompt, tool descriptions, skill
selection, recovery behaviors) fits a *small* model's capabilities. All
three harnesses are the same agent loop on the same model; what differs
is what surrounds the model call.

| Adapter | What it is | Why it's in the matrix |
|---|---|---|
| `pi_vanilla` | `pi --no-extensions` — 4 tools, ~1K-token prompt | Floor. Minimal scaffold. |
| `pi_devstack` | devstack pi profile (curated extensions + skills) | "Pi as we run it." Mid-scaffold. |
| `little_coder` | little-coder launcher (pi + 20 ext + 30 skills) | Maximal targeted scaffold for small models. |
| `pi_superpowers` | `pi_vanilla` + Superpowers debugging/verification skills | Ablation: does generic methodology help or hurt without devstack extensions? |
| `pi_devstack_superpowers` | devstack extensions + Superpowers debugging/verification skills | Direct `pi_devstack` vs `pi_devstack` + Superpowers bench ablation. |
| `little_coder_superpowers` | `little_coder` + Superpowers debugging/verification skills | Same Superpowers ablation for little-coder. |

Prediction (worth testing): little_coder > pi_devstack > pi_vanilla on
both suites, with the gap widest on the smallest models. Superpowers
helps pi_vanilla on TB (recovery discipline) and *hurts* on Polyglot
(token overhead per turn in a small context) — but that's the hypothesis,
not a foregone conclusion.

## 2. Models

Input, not output. We do not serve or configure models here. Runtime
provider endpoints live in `~/.pi/agent/models.json` (already populated)
and are surfaced to the harness via `configs/models.yaml`. Entries can be
just an ID, or they can carry benchmark accounting metadata such as context
limits and per-million-token pricing. Repo metadata overrides local provider
stubs for manifest/backfill accounting, so cost/intelligence comparisons do
not silently inherit zero-priced development configs.

```yaml
models:
  - id: bonsai/Ternary-Bonsai-27B-Q2_0.gguf
  - id: nvidia/nemotron-3-ultra-550b-a55b
  - id: aiand/qwen/qwen3.6-27b
  - id: zai/glm-5.2
    name: GLM 5.2
    context_window: 1000000
    max_tokens: 128000
    reasoning: true
    cost:
      input: 1.4
      cacheRead: 0.26
      cacheWrite: 0
      output: 4.4
    pricing_unit: usd_per_1m_tokens
  - id: minimax/MiniMax-M3
  - id: minimax/MiniMax-M2.7
  - id: nvidia/stepfun-ai/step-3.7-flash
  - id: local/ornith-1.0-35b
```

`scripts/check-models.sh` (P3) tells us which are actually alive before a
run; the runner refuses to start if a model in the matrix is unreachable.

Critical invariant across all arms: **identical sampling params and
tool-call parser config on the server side.** vLLM's `--tool-call-parser`
choice will dominate any scaffold difference if mismatched. We do not
control the server here, but we record the served model name + provider
in the manifest so a mismatch is detectable in post.

## 3. Suites

### Aider Polyglot (P9, first)

225 Exercism problems across C++, Go, Java, JS, Python, Rust. Each problem
is independent, fast (minutes), and graded by the language's native test
runner. Cheap signal; do this before any TB run.

- Dataset: vendored at `vendor/aider-polyglot/` (clone the public repo).
- Per-task: materialize the problem's starter files into a fresh workdir,
  excluding solution-bearing `.meta/` examples and `.approaches/` guides.
  Prefix the problem statement with the task ID, required language, and an
  explicit current-workdir-only boundary, then run the existing test suite.
- Isolation: all local Aider adapters run through an empty-root bubblewrap
  namespace. Its allowlist contains the active workdir, selected system and
  language runtimes, the selected provider/model config, read-only scaffold
  packages, disposable dependency/browser caches, and the trial's unique
  telemetry session. Shared repositories, general home state, `vendor/`,
  `results/`, and prior sessions are absent. The network namespace has no
  public route; a host socat process and Unix socket expose only the configured
  model endpoint. Model-written code is also verified inside a workdir-only,
  no-network namespace. JavaScript, Java, and Rust dependencies are prefetched
  before agent launch and consumed offline; Java uses JDK 21 for the vendored
  Gradle 8.7 wrapper. This is a fail-closed Linux requirement: `bwrap` and
  `socat` must exist.
- Verdict: pass/fail per problem; partial credit possible per-language if
  tests are tiered (record raw pass count, derive binary for the headline).

### Terminal-Bench (P11, second)

Terminal-Bench Core 0.1.1 is the canonical 80-task set behind the original
leaderboard. Cospa runs it through Harbor as the immediate external anchor;
Terminal-Bench 2.1 remains a separate milestone campaign.

- Repo: https://github.com/harbor-framework/terminal-bench
- Dataset manifest: `configs/terminal_bench_core_0.1.1.json`.
- Upstream pin: `91e10457b5410f16c44364da1a34cb6de8c488a5` on
  `dataset/terminal-bench-core/v0.1.x`; setup checks it out detached and task
  discovery refuses a partial or differently pinned real checkout.
- Driven by Harbor with one local migrated task path per cospa trial and one
  Harbor attempt per outer trial.
- Every adapter maps to a distinct custom Harbor agent, preserving scaffold
  identity inside the task container. Because Harbor containers have an empty
  pi home, the `pi_devstack*` agents additionally mount a read-only, sanitized
  package-profile snapshot; distinct class names alone do not establish a
  distinct scaffold.
- Network boundary: Harbor environment build and installed-agent setup may use
  public network for images/packages. Migrated local tasks are patched so the
  prompt-bearing `[agent]` phase uses `network_mode = "allowlist"` with only
  the selected model hostname, also passed via `--allow-agent-host`. Registry
  fallback is disabled because it cannot guarantee the patch. Host-loopback
  model URLs require `CODING_EVAL_HARBOR_MODEL_BASE_URL` set to a
  container-reachable relay address.
- **Wall-clock probe first.** Before scaling, run k=1 on a 5-task slice,
  measure time, *then* decide k for the real matrix. TB on small models
  is slow; we don't want to discover a 40-hour run after launching it.

### SWE Atlas pilot12 (P11b, third)

The first new harness-discrimination suite is the cost/reliability pilot from
`docs/EVALS.md`, not a full SWE Atlas leaderboard reproduction.

- Upstream repository: https://github.com/scaleapi/SWE-Atlas at immutable
  commit `2cac47d64a9123d915b8f6f6f53763391920f574`.
- Pilot manifest: `configs/swe_atlas_pilot12.json`; exactly eight Test Writing
  and four Codebase Q&A tasks, with two Test Writing plus one Q&A task in each
  of Go, Python, C, and TypeScript. Q&A also spans onboarding, root-cause,
  architecture, and security; Test Writing spans unit, integration, and
  acceptance work.
- Harbor execution: each task's upstream `task.toml`, prompt, environment,
  tests, mutation patch, rubrics, and judge prompts are copied unchanged into
  the trial workdir. The same distinct custom Harbor agents used by
  Terminal-Bench preserve adapter identity.
- Judge: fixed to `anthropic/claude-opus-4-5-20251101`; credentials come from
  `SWE_ATLAS_JUDGE_API_KEY` and `SWE_ATLAS_JUDGE_BASE_URL`. Missing judge
  setup fails before agent execution. The pinned upstream commit also pins the
  judge prompts and rubrics.
- Results: strict Harbor reward remains the headline. Test Writing additionally
  preserves rubric, manifest, and mutation subchecks; Q&A preserves aggregate
  rubric coverage. Manifests record workflow, language, repository/base commit,
  upstream commit, and judge model.
- Status: `wired (unit test + real pinned artifact)`. All 12 tasks discover and
  materialize from the real checkout; a real rubric-scoring path is still
  required before upgrading this to `fixed (end-to-end)`.
- Campaign: one representative model with `pi_vanilla`, all 12 at k=1. Apply
  the runtime/token/telemetry/infrastructure/difficulty gates in `docs/EVALS.md`
  before a matched k=2 pass or any adapter expansion.

## 4. Reproducibility & results layout

Every normal CLI invocation writes under a model-prefixed run wrapper, so
parallel invocations do not race by default:

```
results/runs/<encoded-model>-<run-id>/<encoded-model>/<adapter>/<suite>/<task_id>/trial-<k>/
├── manifest.json     # model, adapter, params, env hash, timing
├── out/              # adapter stdout/stderr, session log, pi_session.jsonl
├── workdir/          # final state of the task workdir (git diff vs initial)
└── verdict.json      # suite-specific: pass/fail, test counts, grader output
```

Direct `run_trial()` callers and explicit `--results-dir` users can still
write to a chosen root; doing so is an intentional merge/rebaseline behavior,
not the safe default.

Aggregation is a pure function over this tree — no in-flight state, no
database. `view-scores/` (P12) reads it cold. This means we can re-score
without re-running, and partial runs compose by directory union.

Reproducibility levers we record but do not enforce: pi version,
little-coder version, Harbor version, TB pin, SWE Atlas upstream/judge pins,
mamba env hash, sampling params, model context/output limits, pricing, and
observed token/cost usage. For Terminal-Bench, the custom Harbor agents export
container-side pi JSONL traces into Harbor artifacts so the runner/backfill can
preserve
the same raw response metadata under each trial's `out/` directory. A run
is "comparable" to another only if these match; the viewer flags mismatches
in the comparison view.

## 5. What we are explicitly NOT doing (v1)

- **No model serving.** Models are inputs. Use the existing stack.
- **No vLLM/SGLang config automation.** Tool-call parser is the server
  operator's responsibility; we just record what was advertised.
- **No full Terminal-Bench 2.0.** Core first; upgrade only if Core
  separates the harnesses cleanly and we need more signal.
- **No interactive skill flows under bench.** Superpowers ablation strips
  anything that expects a human in the loop.
- **No porting multieval code.** It's reference for *shape* (run/view
  patterns, results tree) only. Clean-room write.
