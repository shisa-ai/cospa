# RESULTS.md — Coding Eval Results

> Clean-room harness for evaluating small local coding models across agent
> harness variants on **Aider Polyglot** and **Terminal-Bench**.

## Executive Summary

**Hypothesis:** Scaffold fit dominates raw model quality for small models.
The same agent loop on the same model should score differently depending on
what surrounds the model call (system prompt, tool descriptions, skill
selection, recovery behaviors).

**Prediction:** `little_coder > pi_devstack > pi_vanilla` on both suites,
with the gap widest on the smallest models. Superpowers helps pi_vanilla
on TB (recovery discipline) and *hurts* on Polyglot (token overhead per
turn in a small context).

## Harness Comparison

| Adapter | What it is | Why it's in the matrix |
|---|---|---|
| `pi_vanilla` | `pi --no-extensions` — 4 tools, ~1K-token prompt | Floor. Minimal scaffold. |
| `pi_devstack` | devstack pi profile (curated extensions + skills) | "Pi as we run it." Mid-scaffold. |
| `little_coder` | little-coder launcher (pi + 20 ext + 30 skills) | Maximal targeted scaffold for small models. |
| `pi_superpowers` | pi_vanilla + Superpowers skills (bench mode) | Ablation: generic methodology without devstack extensions. |
| `pi_devstack_superpowers` | pi_devstack extensions + Superpowers skills (bench mode) | Direct devstack + methodology ablation. |
| `little_coder_superpowers` | little_coder + Superpowers skills (bench mode) | Ablation: same, for little-coder. |

## Results

### Aider Polyglot

| Model | Adapter | Score | Passed | Tasks | Cost | $/Task | Pass/$ |
|---|---|---|---|---|---|---|---|
| *Run the matrix to populate this table* | | | | | | | |

### Terminal-Bench

| Model | Adapter | Score | Passed | Tasks | Cost | $/Task | Pass/$ |
|---|---|---|---|---|---|---|---|
| *Run the matrix to populate this table* | | | | | | | |

## Per-Model Findings

*Populate after running the matrix.*

## Methodology

### Suites

- **Aider Polyglot** — 225 Exercism problems across C++, Go, Java, JS,
  Python, Rust. Cheap signal (~minutes per problem).
- **Terminal-Bench** — canonical agentic eval via Harbor. Wall-clock probe
  first, then scale.

### Adapters

All adapters launch the model in headless mode (`--print`) and capture
stdout/stderr. The harness records:

- Model ID + provider
- Provider model metadata when available: served model, context window,
  max output tokens, input modalities, reasoning support, and per-million
  token pricing
- Adapter ID + version
- Sampling params, including pinned thinking level and local thinking-token
  budget when configured
- Env hash (mamba env)
- Pi version
- Little-coder version
- Wall-clock time
- Token usage and cost: input/output/cache-read/cache-write/reasoning tokens,
  response count, response IDs/models, and direct provider-reported cost
  when available
- Exit code

### Results Layout

```
results/<model>/<adapter>/<suite>/<task_id>/trial-<k>/
├── manifest.json     # model, adapter, params, env hash, timing
├── out/              # adapter stdout/stderr, session log, pi_session.jsonl
├── workdir/          # final state of the task workdir
└── verdict.json      # suite-specific: pass/fail, test counts, grader output
```

### Reproducibility

Results are a pure directory tree — no database, re-scoreable without
re-running, partial runs compose by directory union.

Reproducibility levers we record but do not enforce: pi version,
little-coder version, Harbor version, TB pin, mamba env hash, sampling
params, model limits/pricing, and observed token/cost usage. A run is
"comparable" to another only if these match.

Existing pi-backed runs can be updated from pi's session store without
rerunning:

```bash
scripts/backfill-usage.py --results-dir results/runs/<run-wrapper>
```

## How to Run

### Smoke test (5 problems, 1 model, 1 adapter)

```bash
./run \
  --suite aider_polyglot \
  --adapters pi_vanilla \
  --models nvidia/nemotron-3-ultra-550b-a55b \
  --problems 5 \
  --k 1
```

### Full matrix

```bash
./run \
  --models nvidia/nemotron-3-ultra-550b-a55b,aiand/qwen/qwen3.6-27b \
  --adapters pi_vanilla,pi_devstack,little_coder \
  --k 3 \
  --problems 225
```

### View scores

```bash
./view
./view --show-ci
./view serve
```

## Next Steps

- [ ] Run full matrix (P13)
- [ ] Run Superpowers ablation (P14)
- [ ] Populate RESULTS.md with findings
- [ ] Write up conclusions
