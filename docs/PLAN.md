# PLAN.md — cospa

> Clean-room harness for evaluating **small local coding models** across
> **agent harness variants** using a portfolio: the contract-complete
> **`aider_cospa`** protocol, pinned **Terminal-Bench Core**, the cheap
> **BigCodeBench-Hard** anchor, and cost-gated deterministic repository,
> feature, and diagnostic suites selected under `docs/EVALS.md`. The pinned
> SWE Atlas pilot is preserved but deferred because its headline requires an
> LLM judge.
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
      and is active, installs Harbor 0.16.1
      (`uv tool install --force harbor==0.16.1`), verifies Docker plus Buildx
      for Harbor's phase-network sidecar, checks out
      Terminal-Bench Core 0.1.1 at commit `91e10457b5410f16c44364da1a34cb6de8c488a5`
      and SWE Atlas at `2cac47d64a9123d915b8f6f6f53763391920f574`,
      and clones Aider Polyglot at source commit
      `7e0611e77b54e2dea774cdc0aa00cf9f7ed6144f` under `vendor/`.
      **Does not** touch models
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
- [ ] **P9. Suite: Aider source corpus.**
      `harness/suites/aider_polyglot.py` loads the 225-problem Exercism
      dataset, materializes one problem per task without behavioral tests or
      reference artifacts, runs one unrestricted workspace-only episode, then
      injects hidden tests into an isolated verifier. This implementation is
      the substrate for `aider_cospa_full`, not yet the completed protocol.
- [ ] **P9a. Contract audit and protocol cutover.** Review all 225 visible
      contracts against their hidden assertions across all six languages;
      create a versioned inclusion/augmentation/exclusion manifest; freeze an
      approximately 50% repeated-concept / 50% language-specific primary panel;
      expose complete API/ABI behavior without test leakage; register distinct
      `aider_cospa`, `aider_cospa_full`, and optional `aider_canonical` suite
      IDs. Follow the hard gates and reporting rules in `docs/EVALS.md`.
- [ ] **P10. First contract-protocol smoke.** One live model, one adapter
      (`pi_vanilla`), `k=1`, and at least one reviewed `aider_cospa` problem in
      each of the six languages. Prove the hidden-test boundary,
      manifest/verdict path, and native grader before scaling.
- [ ] **P11. Suite: Terminal-Bench.** `harness/suites/terminal_bench.py`
      wraps `harbor run` against the checked-in 80-task
      `terminal-bench-core==0.1.1` manifest and immutable upstream commit.
      Each adapter uses a distinct custom Harbor agent. The frozen
      `terminal_bench_core_pilot8` DS4 c=8 smoke resolved 3/8, returned one
      ordinary incorrect outcome and four official agent timeouts, and had no
      infrastructure/verifier failures after migration compatibility fixes.
      The nested `terminal_bench_core_pareto20` panel preserves pilot8 and
      targets 9 capability categories, 5 easy / 9 medium / 6 hard tasks, and
      15 short / 3 medium / 2 long declared-runtime buckets without using
      target-model outcomes. Its DS4 baseline resolved 11/20, returned seven
      ordinary incorrect outcomes and two budget expirations, and had no
      infrastructure/verifier failure. Keep the official 80-task suite under
      `terminal_bench` and reserve full80 for finalists.
- [ ] **P11b. Suite: SWE Atlas pilot12 (deferred).**
      `harness/suites/swe_atlas.py` preserves a predeclared Harbor-native slice:
      eight Test Writing and four Codebase Q&A tasks, with three total tasks
      per Go/Python/C/TypeScript stratum. Keep its upstream and rubric-judge
      pins, but do not make it an active Pareto-campaign dependency: the current
      campaign prefers deterministic executable headline graders.
- [ ] **P11c. Suite: BigCodeBench-Hard hermetic143 + Pareto60.**
      `harness/suites/bigcodebench.py` and the protocol-specific
      `bigcodebench_openai` adapter preserve a separate non-agentic baseline:
      one OpenAI-compatible user message, no system/tools/context, greedy
      `n=1`, upstream sanitization, and calibrated evaluation in the immutable
      Linux/amd64 verifier image. The full148 public prompt projection contains
      no tests or solutions. A no-network gold screen excluded five tasks that
      require external URLs or unavailable NLTK data; each of the 143 retained
      tasks then passed three gold observations and failed three null
      observations. Distinct
      `bigcodebench_hard_instruct_hermetic143`,
      `bigcodebench_hard_agentic_hermetic143`, and nested
      `bigcodebench_hard_agentic_pareto60` suite IDs prevent protocol or panel
      merging. Agentic suites materialize editable `solution.py` workspaces;
      their scores never merge with the Instruct anchor or claim full148
      comparability. DS4 resolved 17/143 Instruct and 22/60 Agentic Pareto tasks
      with no infrastructure, verifier, or budget failure.
- [ ] **P11d. Suite: SWE-PolyBench Verified pilot28 + balanced64.**
      `harness/suites/swe_polybench.py` retains the original repeat-qualified
      pilot28 and adds the distinct `swe_polybench_verified_balanced64` routine
      panel. The expansion froze an outcome-blind candidate96 before target-model
      outcomes, then screened two adaptive Java-only support sets after the
      mechanical oracle gate exposed small/medium Java shortages. Across 135
      source candidates, 82 had three stable gold observations; the final panel
      selects 16 tasks per language, all three task types, near-equal patch-size
      tertiles, repository-diversity/cost tradeoffs, and no selected task whose
      mean gold verifier exceeds the fixed ten-minute threshold. All 192 gold
      observations resolve and all 192 selected null observations fail with empty
      patches under the no-network verifier. The candidate96 and Java extensions
      remain support artifacts, not scored suites, and no balanced96 score is
      claimed. Derived images reset repositories to declared base commits;
      hidden tests and gold patches enter only their Harbor phases, and scoring
      uses the pinned upstream parser. The DS4 balanced64 baseline resolved
      15/64, returned 47 ordinary incorrect outcomes and two budget expirations,
      and had no infrastructure/verifier failure.
- [ ] **P11e. Suite: Multi-SWE-bench Flash hermetic25.**
      `harness/suites/multi_swe_bench.py` materializes an outcome-blind
      seven-language screen over digest-pinned upstream images, removes
      construction-time gold/test artifacts before the agent, captures a clean
      model patch, injects hidden tests only in the verifier, and scores with
      pinned upstream transition parsers. The scored suite retains 25 of 30
      screened tasks after three clean null/gold observations: three Java tasks
      required uncached verifier dependencies and two TypeScript tasks had
      unrelated flaky gold failures. The DS4 baseline resolved 9/25, returned
      15 ordinary incorrect outcomes and one budget expiration, and had no
      infrastructure/verifier failure. Keep the source score separate and
      disclose the retained 4 C / 4 C++ / 5 Go / 1 Java / 5 JavaScript / 4 Rust /
      2 TypeScript distribution.
- [ ] **P11f. Suite: FeatureBench Lite Pareto12.**
      `harness/suites/featurebench.py` materializes digest-pinned official Lite
      rows as Harbor tasks, removes the unmasked source repository before the
      agent phase, injects tests and gold artifacts only afterward, and scores
      binary resolution plus task-level F2P partial credit with the pinned
      upstream parser. The official Lite30 screen has four Level 2 rows without
      released gold and five Level 1 rows that failed or flaked mechanically.
      `featurebench_lite_pareto12` retains 12 repeat-qualified Level 1 tasks
      across 11 repositories; all 36 selected gold observations pass and all 36
      null observations fail offline. Keep this Cospa panel distinct from the
      official Lite30 score, and require new mechanical qualification before
      claiming broader Lite or Fast100 coverage.
- [ ] **P11g. Suite: SWE-Explore Verified12 diagnostic.**
      `harness/suites/swe_explore.py` freezes one mechanically valid
      Verified-derived task from each of 12 Python repositories without using
      target-model outcomes. Agents explore immutable base-commit snapshots and
      emit at most five ranked file/line regions; ground truth stays outside the
      sandbox and the pinned official evaluator reports continuous weighted
      core coverage. Thirty-six oracle observations score 1.0 and 36 null
      observations score 0.0. The DS4 bake-off run selected this suite over the
      slower third-party DABstep Harbor conversion. Keep the task-macro
      continuous headline, any-core-line-hit diagnostic, and binary coding
      resolution as distinct quantities.
- [ ] **P12. Score viewer (`view-scores/`).** Static HTML + a tiny
      `server.py` that walks `results/` and renders a table:
      rows = `(model, adapter, suite)`, cells = pass-rate with CI for binary
      suites or task-macro headline score for explicitly continuous non-coding
      diagnostics, drill-down to per-task verdicts. Verbose terminal and HTML
      views expose weighted inference/tool percentages plus mean tool/search
      calls; score and task APIs retain aggregate exact tool/category maps,
      error/long-call counts, slowest calls, and per-trial behavior rollups.
      Missing legacy timing remains `-`, never inferred from ambiguous session
      timestamps.
      Borrow the *shape* from multieval's viewer; this is a clean-room write,
      not a port.
- [ ] **P13. Cost-gated campaigns.** Do not launch a full Cartesian matrix.
      Concurrency qualification still begins on fixed `c=1`/`c=2` blocks and
      advances only while throughput and tail-error gates pass. The current
      operational baseline is DS4 + `pi_vanilla` + `c=8`. The completed
      breadth-first wave covers BCB Instruct143, BCB Agentic60, Multi-SWE25,
      Terminal20, PolyBench64, FeatureBench12, and SWE-Explore12;
      suite-specific outcomes, costs, nested expansion, and Pareto promotion
      rules live in `docs/PARETO-CAMPAIGN.md`. The matched BCB Pareto60 gate
      retained `pi_vanilla high`: devstack `high` lost 4-to-7 discordant tasks,
      while devstack `xhigh` cost 3.27 times `off` for an inconclusive 8-to-3
      paired gain. No devstack arm advances to expensive suites. Compare models
      only on the retained baseline scaffold. Reserve full repository/feature
      suites and `k>1` for cells that pass those gates; report independent
      repetitions rather than best-of-k.
- [ ] **P14. Superpowers ablation (2×2).** Add adapters `pi_superpowers`
      and `little_coder_superpowers`. For bench runs, **strip interactive
      skill-check flows** (no user present to answer clarifying questions)
      and use the pinned, headless-safe `superpowers-bench-v1` subset:
      systematic-debugging, test-driven-development, and
      verification-before-completion with their referenced support files.
      The TDD skill is required because the debugging workflow delegates its
      implementation phase to it. 2×2 = {pi, little_coder} × {baseline,
      +superpowers-bench}. Optional / last — depends on TB timing (P11).
- [ ] **P15. Write up.** Results table, harness comparison, per-model
      findings. `RESULTS.md` at the repo root.

Defer / out of scope for v1: full Terminal-Bench 2.0 (use Core for now),
model serving automation, automated regression on every commit.

---

## 1. What we're measuring, and why

The primary variable we want to isolate is **scaffold fit** — how well the
agent's context engineering (system prompt, tool descriptions, skill
selection, recovery behaviors) fits a *small* model's capabilities. The
agentic adapters use the same loop on the same model; what differs is what
surrounds the model call. `bigcodebench_openai` is intentionally excluded from
that scaffold matrix: it is a no-tool, one-generation orthogonal anchor.

| Adapter | What it is | Why it's in the matrix |
|---|---|---|
| `pi_vanilla` | `pi --no-extensions` — 4 tools, ~1K-token prompt | Floor. Minimal scaffold. |
| `pi_devstack` | devstack pi profile (curated extensions + skills) | "Pi as we run it." Mid-scaffold. |
| `little_coder` | little-coder launcher (pi + 20 ext + 30 skills) | Maximal targeted scaffold for small models. |
| `pi_superpowers` | `pi_vanilla` + pinned Superpowers debugging/TDD/verification profile | Ablation: does generic methodology help or hurt without devstack extensions? |
| `pi_devstack_superpowers` | devstack extensions + the same pinned Superpowers profile | Direct `pi_devstack` vs `pi_devstack` + Superpowers bench ablation. |
| `little_coder_superpowers` | `little_coder` + the same pinned Superpowers profile | Same Superpowers ablation for little-coder. |
| `bigcodebench_openai` | One OpenAI-compatible user message; no system prompt or tools | Separate BigCodeBench protocol anchor; never compared as a scaffold arm. |

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

### `aider_cospa` contract implementation (P9/P9a, first)

The 225 Aider/Exercism instances across C++, Go, Java, JavaScript, Python, and
Rust are a **source corpus**, not the final benchmark definition. They contain
100 concepts: 183 task instances belong to repeated cross-language concepts and
42 are singletons. The protocol and task-review criteria are normative in
`docs/EVALS.md`.

- Suites: `aider_cospa` is the reviewed frequent-run panel;
  `aider_cospa_full` is all retained/augmented source instances;
  `aider_canonical` is an optional legacy reproduction whose scores never merge
  with the Cospa protocol.
- Public contract: expose complete observable behavior and exact API/ABI
  requirements. Hidden tests may contain surprising inputs, never secret
  requirements. Do not call the suite `aider_cospa` until all 225 contracts and
  hidden assertions have a versioned review decision.
- Episode: materialize starter/build artifacts into a fresh workdir without
  behavioral tests, `.meta` solutions, or `.approaches`; run one unrestricted
  workspace-only agent episode; do not provide verifier feedback or an
  in-episode retry; inject hidden tests only after the agent stops.
- Isolation: all local adapters run through an empty-root bubblewrap namespace.
  Its allowlist contains the active workdir, selected system and language
  runtimes, selected provider/model config, read-only scaffold packages,
  disposable dependency/browser caches, and the trial's unique telemetry
  session. Shared repositories, general home state, `vendor/`, `results/`, and
  prior sessions are absent. The network namespace has no public route; a host
  socat process and Unix socket expose only the configured model endpoint.
  Model-written code is verified inside a workdir-only, no-network namespace.
  JavaScript, Java, and Rust dependencies are prefetched before agent launch and
  consumed offline; Java uses JDK 21 for the vendored Gradle 8.7 wrapper. This
  is a fail-closed Linux requirement: `bwrap` and `socat` must exist.
- Verdict: all required behavioral checks and the public API/ABI must pass for
  resolution. Test-level partial credit is diagnostic only. Report task-,
  language-, and concept-weighted scores plus paired repeated-concept outcomes.
- Budgets: capability limits and safety wall time are separate. A safety-wall
  hit is `budget_exhausted`, not an ordinary wrong answer. Measure model,
  tool, verifier, and total timing and calibrate serving `c=1` versus `c=2`
  before any full run.

### Terminal-Bench (P11, second)

Terminal-Bench Core 0.1.1 is the canonical 80-task set behind the original
leaderboard. Cospa runs it through Harbor as the immediate external anchor;
Terminal-Bench 2.1 remains a separate milestone campaign.

- Archived Core repository: https://github.com/harbor-framework/terminal-bench-1
  (the newer `terminal-bench` repository no longer exposes the 0.1.1 commit).
- Dataset manifest: `configs/terminal_bench_core_0.1.1.json`.
- Upstream pin: `91e10457b5410f16c44364da1a34cb6de8c488a5` on
  `dataset/terminal-bench-core/v0.1.x`; setup checks it out detached and task
  discovery refuses a partial or differently pinned real checkout.
- Driven by Harbor with one local migrated task path per cospa trial and one
  Harbor attempt per outer trial.
- Every adapter maps to a distinct custom Harbor agent, preserving scaffold
  identity inside the task container. Because Harbor containers have an empty
  pi home, the `pi_devstack*` agents additionally mount a read-only package
  profile with a deterministic settings snapshot. Container activation removes
  browser, TUI, and host-native fetch packages from its private copy before Pi
  package discovery; distinct class names alone do not establish a distinct
  scaffold.
- Network boundary: Harbor environment build and installed-agent setup may use
  public network for images/packages. Migrated local tasks are patched so the
  prompt-bearing `[agent]` phase uses `network_mode = "allowlist"` with only
  the selected model hostname, also passed via `--allow-agent-host`. Registry
  fallback is disabled because it cannot guarantee the patch. Host-loopback
  model URLs require `CODING_EVAL_HARBOR_MODEL_BASE_URL` set to a
  container-reachable relay address.
- **Measured gate.** The DS4 `pi_vanilla` Pareto20 completed in 17m24s at c=8:
  11 resolved, 7 incorrect, and 2 official agent-budget expirations, with no
  infrastructure/verifier failure. Add repetitions or full80 only after a
  matched scaffold arm and the stability gate justify the cost.

### SWE Atlas pilot12 (P11b, preserved but deferred)

This cost/reliability pilot remains implemented and pinned, but it is not an
active dependency of the deterministic Pareto campaign in
`docs/PARETO-CAMPAIGN.md`. Its headline requires an LLM rubric judge, so current
campaign budget goes first to executable-oracle suites.

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
- Campaign: deferred. If judge-based diagnostics are explicitly restored,
  start with one representative model using `pi_vanilla`, all 12 at k=1, and
  apply the runtime/token/telemetry/infrastructure/difficulty gates in
  `docs/EVALS.md` before a matched k=2 pass or adapter expansion.

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
