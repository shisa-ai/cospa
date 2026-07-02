# PLAN.md — coding-eval

> Clean-room harness for evaluating **small local coding models** across
> **agent harness variants** on **Aider Polyglot** and **Terminal-Bench Core**.
>
> Scope is deliberately narrow: no model serving, no vLLM/SGLang config, no
> training. Models are an *input* (provider IDs in `models.json`); results are
> an *output* (a scored directory tree). The thing we are measuring is the
> **harness**, on the theory that scaffold–model fit dominates raw model quality
> for small models (cf. *Honey, I Shrunk the Coding Agent*).

All Python code runs inside the `coding-eval` mamba environment
(`python=3.12`). Use `mamba run -n coding-eval <cmd>` or `conda activate
coding-eval` before invoking any harness script. The setup script (P2)
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
      version), verifies the `coding-eval` mamba env (python=3.12) exists
      and is active, installs Harbor (`uv tool install harbor`), clones
      Terminal-Bench (latest, `harbor-framework/terminal-bench`) and
      Aider Polyglot dataset under `vendor/`. **Does not** touch models
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
      `results/<model>/<adapter>/<suite>/<task_id>/trial-<k>/{manifest.json,out/,verdict.json}`.
      Manifest records: model id + provider, adapter id + version,
      sampling params, env hash, start/end time, token usage (if known).
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
- [ ] **P11. Suite: Terminal-Bench Core.** `harness/suites/terminal_bench.py`
      wraps `harbor run` against `terminal-bench-core@0.1.1` using
      `--agent-import-path` per adapter. **Patch the Harbor `upload_dir`
      bug first** (agent-created `/tests` dir → verifier paths at
      `/tests/tests/test.sh`). Start with k=1 on a 5-task slice to
      measure wall-clock before committing to full runs.
- [ ] **P12. Score viewer (`view-scores/`).** Static HTML + a tiny
      `server.py` that walks `results/` and renders a table:
      rows = `(model, adapter, suite)`, cells = pass-rate with CI,
      drill-down to per-task verdicts. Borrow the *shape* from
      multieval's viewer; this is a clean-room write, not a port.
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
| `*_superpowers` | above + Superpowers debugging/verification skills | Ablation: does generic methodology help or hurt? |

Prediction (worth testing): little_coder > pi_devstack > pi_vanilla on
both suites, with the gap widest on the smallest models. Superpowers
helps pi_vanilla on TB (recovery discipline) and *hurts* on Polyglot
(token overhead per turn in a small context) — but that's the hypothesis,
not a foregone conclusion.

## 2. Models

Input, not output. We do not serve or configure models here. Models live
in `~/.pi/agent/models.json` (already populated) and are surfaced to the
harness via `configs/models.yaml`, which is just:

```yaml
models:
  - id: nvidia/nemotron-3-ultra-550b-a55b
  - id: aiand/qwen-3.6-27b
  - id: glm/glm-5.2
  - id: minimax/minimax-3
  - id: minimax/minimax-2.7
  - id: nvidia/stepfun-3.7-flash
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
  run the adapter with the problem statement as the initial prompt, then
  run the existing test suite.
- Verdict: pass/fail per problem; partial credit possible per-language if
  tests are tiered (record raw pass count, derive binary for the headline).

### Terminal-Bench (P11, second)

Latest from `harbor-framework/terminal-bench` — the canonical agentic
eval. We use it via Harbor; Core is the subset we run first for cheap
iteration, then graduate to the full suite if Core separates the
harnesses cleanly.

- Repo: https://github.com/harbor-framework/terminal-bench (latest)
- Driven by Harbor: `harbor run -d terminal-bench@latest \
  --agent-import-path <adapter> -m <model> -n <k>`.
- Per-adapter `--agent-import-path`:
  - `pi_vanilla`, `pi_devstack`, `*_superpowers` → adapter wraps the
    `pi_terminal_bench:PiAgent` import with the right launch flags.
  - `little_coder` → `benchmarks.harbor_adapter.little_coder_agent:LittleCoderAgent`
    (from the little-coder repo, used as a library reference).
- **Landmine:** Harbor `upload_dir` bug — if the agent creates `/tests`
  during a task, the verifier's files land at `/tests/tests/test.sh` and
  scoring silently breaks. Patch before any TB run; record the patch hash
  in the manifest.
- **Wall-clock probe first.** Before scaling, run k=1 on a 5-task slice,
  measure time, *then* decide k for the real matrix. TB on small models
  is slow; we don't want to discover a 40-hour run after launching it.

## 4. Reproducibility & results layout

Every task run produces a self-contained directory:

```
results/<model>/<adapter>/<suite>/<task_id>/trial-<k>/
├── manifest.json     # model, adapter, params, env hash, timing
├── out/              # adapter stdout/stderr, session log
├── workdir/          # final state of the task workdir (git diff vs initial)
└── verdict.json      # suite-specific: pass/fail, test counts, grader output
```

Aggregation is a pure function over this tree — no in-flight state, no
database. `view-scores/` (P12) reads it cold. This means we can re-score
without re-running, and partial runs compose by directory union.

Reproducibility levers we record but do not enforce: pi version,
little-coder version, Harbor version, TB pin, mamba env hash, sampling
params. A run is "comparable" to another only if these match; the viewer
flags mismatches in the comparison view.

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
