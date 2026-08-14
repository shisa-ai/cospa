# Wide-panel survey: multi-domain coverage for harness comparison

_Surveyed: 2026-08-14. Status: **input to `docs/EVALS.md`, not adopted policy.**
The `docs/EVALS.md` Decision table governs until this portfolio question is
settled there. The parallel review of repository-suite candidates is being
done separately; this document covers the domain-coverage question._

Cospa's primary experimental axis is the adapter/scaffold matrix
(`docs/PLAN.md`: "the primary variable we want to isolate is scaffold fit").
A single-suite panel — however well re-contracted — can only show scaffold
effects on one problem shape. This survey reviews existing agentic coding
benchmarks by **problem domain** (GPU/low-level, data science, visualization,
text manipulation, plus fresh repo/feature context) and asks which can be
assembled into a Cospa-owned wide panel, provisionally `cospa_wide`, that
compares harnesses across mixed languages and problem types.

Claim labels follow `docs/EVALS.md`: **Published** (benchmark authors),
**Measured here** (Cospa artifacts), **Planning ceiling**, **Estimate**,
**Unknown / pilot required**. Web sources were fetched 2026-08-14; search
engines were partially blocked, so discovery came from direct fetches of
known projects plus DuckDuckGo HTML results — coverage of very recent
releases is not guaranteed.

## What the existing portfolio already covers

| Domain | Existing Cospa role |
| --- | --- |
| Contract implementation (multilingual) | `aider_cospa` (in contract review) |
| Repository issue resolution | `cospa_repo` bake-off candidates (separate review) |
| Feature implementation | FeatureBench Lite (milestone) |
| Terminal / ops competence | Terminal-Bench Core 0.1.1 |
| Investigation / test writing | SWE Atlas pilot12 |
| One-shot code generation | BigCodeBench-Hard Instruct anchor |

Not covered anywhere: **GPU kernels / low-level performance**, **data
science over messy tabular data**, **data visualization**, **text
manipulation / structured wrangling**, and **performance optimization of
existing code**. Those are the focus below.

## GPU kernels and low-level performance

### KernelBench — leading candidate

- **Source:** ScalingIntelligence (Stanford), ICML 2025, MIT license.
  Repo, HuggingFace dataset (v0.1), paper arXiv 2502.10517.
- **Task shape:** transpile a PyTorch reference program into an efficient
  CUDA/DSL kernel. **Published:** 250 fixed tasks — Level 1 (100
  single-kernel operators), Level 2 (100 fusion patterns), Level 3 (50 full
  model architectures) — plus a growing Level 4 (HuggingFace models).
  Backends: `cuda`, `triton`, `hip`, `cute`, `tilelang`, `thunderkittens`.
- **Verification:** correctness checked against the reference torch operator
  on randomized inputs (`n_correctness` trials); performance measured as
  wall-clock speedup vs the eager PyTorch baseline (`n_trial` timings);
  headline metric `fast_p` (fraction correct and ≥ p× faster). Baselines
  must be generated per hardware; reference timings are provided for
  several NVIDIA GPUs.
- **Gates:** spec sufficiency passes (the torch program *is* the contract);
  verification is programmatic; gold/null is natural (reference
  implementation = gold; unchanged torch code = fails the speedup gate);
  artifact isolation is easy (nothing hidden except the grader).
  Reproducibility requires pinning GPU model, driver, torch/triton
  versions, and locally generated baselines — speedups are
  hardware-relative by design.
- **Risks:** timing noise and reward hacking (kernels that wrap torch ops;
  2026-era community tooling adds roofline/audit checks); results are only
  comparable within one pinned GPU configuration; GPU contention with the
  serving endpoint must be scheduled around.
- **Adoption notes:** a Harbor adapter is in progress upstream
  (harbor-framework/harbor PR #999), which matches Cospa's Harbor 0.16.1
  stack. **Published** leaderboard variants now run KernelBench agentically
  (iterative compile/profile loops), which is exactly the regime where
  scaffold differences should appear.

### TritonBench — secondary, overlapping

- **Source:** thunlp (Tsinghua), ACL 2025 Findings, arXiv 2502.14752.
- **Task shape:** generate Triton operators. Two channels: TritonBench-G
  (**Published:** 184 real-world operators from GitHub) and TritonBench-T
  (PyTorch-interface-aligned; count unstated in the README — pin at pilot).
- **Verification:** call accuracy, execution accuracy, and efficiency
  (speedup); the G channel additionally scores CodeBLEU similarity, which
  Cospa would ignore (implementation-agnostic grading).
- **Risks:** pinned to `triton==3.1.0`, `torch>=2.5.1`; license not stated
  in the README (**Unknown**); heavy overlap with KernelBench's `triton`
  backend. **Recommendation:** take Triton exposure through KernelBench's
  triton backend rather than adopting TritonBench as a separate suite,
  unless the G-channel's real-world operator set is wanted for variety.

### KernelBot / GPU MODE reference-kernels — not a suite

Competition backend (Discord-based submission, their GPU fleet). Problem
designs and reference kernels are useful inspiration for authoring Cospa
kernel tasks, but grading is not self-hostable. Not recommended.

### SWE-Perf — repository-level performance optimization

- **Source:** SWE-Perf org (TikTok internship work), arXiv 2507.12415.
- **Task shape:** given a repository and target functions, produce a patch
  that reduces test execution time without breaking correctness.
  **Published:** 140 instances from performance-improving PRs across 12
  repositories (Python). Oracle setting provides target functions; a
  realistic setting supports OpenHands/Agentless scaffolds.
- **Verification:** runtime improvement on the PR's tests, expert patch as
  reference.
- **Risks:** single shared `environment.yml` (not per-instance images) —
  Cospa would need to containerize per task; the README's oracle setting
  mentions providing "the human expert's solution for reference," which
  must be checked against the artifact-isolation gate before any adoption;
  license **Unknown**; timing-based scoring repeats the KernelBench noise
  concerns at repository scale.
- **Position:** promising *optimization-of-existing-code* signal that no
  other portfolio component has; adopt only after protocol review and a
  null/gold screen.

## Data science over messy tabular data

### DABstep — leading candidate

- **Source:** Adyen + Hugging Face, arXiv 2506.23719; dataset
  `adyen/DABstep` on HuggingFace.
- **Task shape:** multi-step analysis questions over synthetic payment
  transaction data, fee rules, and merchant documentation. **Published:**
  over 450 tasks. Answers are checked against ground-truth values —
  deterministic, implementation-agnostic grading.
- **Adoption notes:** an Inspect-Harbor registry wrapper already exists
  (meridianlabs-ai `inspect_harbor` → `adyen_dabstep`), which is the same
  Harbor path Cospa already runs. Data is synthetic (contamination-free
  and licensable). Dataset license: **Unknown / verify at pilot**.
- **Risks:** answer-matching graders can accept lucky guesses on
  single-value questions; prefer the multi-step tasks and keep the
  difficulty split visible in reporting.

### DSBench — conditional candidate

- **Source:** LiqiangJing et al., ICLR 2025, arXiv 2409.07703.
- **Task shape:** realistic analysis (Excel/tabular) and modeling tasks
  from ModelOff/Eloquence and Kaggle. **Published:** 466 analysis + 74
  modeling tasks. Graders compare computed values/ML metrics against
  ground truth (programmatic).
- **Legal gate:** the dataset is explicitly **non-commercial,
  research-only** with redistribution restrictions. Local evaluation is
  consistent with Cospa's research use, but Cospa must not redistribute
  task data in any published manifest — source IDs and pinned upstream
  revisions only.
- **Validity signal:** used by OpenAI for ChatGPT-agent evaluation (2025).
- **Risks:** heavy data files (hermeticity/pinning work); some tasks may
  need image input (**verify** — text-only requirement for local models).

### Rejected or deferred in this domain

- **MLE-bench / MLAgentBench / PaperBench:** full ML-pipeline and paper
  reproduction; costs dwarf everything else in the portfolio (EVALS.md
  already defers similarly-shaped suites like SWE-Cycle).
- **DS-1000:** one-shot generation, not agentic; duplicates the
  BigCodeBench anchor role.
- **Notebook-editing benchmarks:** no stable, adoptable public benchmark
  was located in this survey pass (**Unknown**); revisit later.

## Data visualization

**Finding:** there is no text-only, judge-free visualization benchmark.

| Candidate | Input | Size (Published) | Grader | Problem |
| --- | --- | --- | --- | --- |
| MatPlotBench (thunlp) | NL instruction + CSV | 100 human-verified | GPT-4V rubric | LLM-judge headline |
| PandasPlotBench (JetBrains) | NL description + DataFrame/CSV | test split on HF (pin at pilot) | GPT-4o judge (+ optional code similarity) | LLM-judge headline |
| Plot2Code (TencentARC) | **reference plot image** | 132 matplotlib + 236 plotly = 368 | execution + image comparison | requires vision input |
| ChartMimic | **chart image** | 4,800 triplets | execution + comparison | requires vision input |

Local models in the Cospa matrix are text-only, which rules out the
image-input suites outright. The two text-input suites (MatPlotBench,
PandasPlotBench) both lean on a VLM judge as the headline oracle, which
strains hard gate 2 in `docs/EVALS.md` ("an LLM judge should not be the
sole headline oracle where a programmatic one is possible").

**Proposal — Cospa-authored deterministic plot grader.** Adopt task
*material* from PandasPlotBench/MatPlotBench (small CSV + two-part
description → plotting code) and replace the judge with deterministic
checks:

1. structural comparison of the rendered matplotlib figure object
   (axes, marks, series data, labels, legends) against the ground-truth
   figure, and
2. a pixel-diff threshold under a pinned renderer/font stack as a
   secondary check.

Both sources ship ground-truth images/code, so the standard three-observation
gold/null screen applies before any task enters the manifest. This is a
bounded R&D unit (one grader, two candidate sources) and the same pattern
Cospa already used to qualify PolyBench images.

## Text manipulation and structured wrangling

**Finding: no established agentic benchmark exists for this domain.**
Searches (2026-08-14) surface only non-agentic regex-reasoning sets
(e.g. RegexPSPACE) and general agent lists. Terminal-Bench Core includes
some text-processing tasks, but coverage is incidental.

**Proposal — author a Cospa mini-corpus (12–16 tasks).** Formats and
invariants, not algorithms:

- log normalization / timestamp-and-field extraction from messy logs;
- format conversion (CSV ↔ JSON ↔ fixed-width ↔ INI-ish) with escaping
  and quoting rules;
- de-duplication and merge with explicit conflict-resolution rules;
- template rendering with strict whitespace/formatting contracts;
- extraction tasks with property-based edge cases (empty, malformed,
  multibyte, pathological nesting).

Grading: hidden edge-case fixtures plus reference-output comparison —
the same machinery as the `aider_cospa` contract review (visible contract,
hidden behavioral fixtures, gold/null ×3). These tasks are cheap to author
and can be ported across 3–4 languages, which also relieves the
singleton-shortage problem identified in the Aider corpus review (only 42
language-singleton instances exist for a 50/50 panel split).

## Fresh repository and feature context (brief)

Owned by the parallel repo-suite review; recorded here for completeness.

- **SWE-Lancer** (OpenAI, arXiv 2502.12115): **Published:** 1,400+ real
  Upwork freelance tasks, $1M real payouts, JS/TS-heavy, Docker-based
  (Expensify). Independent-engineering subset is a realistic
  feature/bugfix slice with task-level payout context; managerial subset
  excluded. License and protocol pinning **Unknown** — pilot gate. Overlaps
  FeatureBench's role; FeatureBench Lite stays the chosen feature suite.
- **LiveSWEBench** (LiveBench org): rolling monthly Python SWE tasks.
  Redundant with the already-decided SWE-bench-Live MultiLang freshness
  audit role; note only.
- **R2E-Gym** (COLM 2025, Apache-2.0): **Published:** 8.1K procedurally
  generated repo environments with hybrid test+equivalence verifiers.
  Quality below the human-verified sets in the bake-off; interesting later
  as a scalable source of additional repo tasks, not for v1.
- **Commit0** (ICLR 2025): 54–57 Python libraries from scratch (counts
  conflict between repo and site — pin at pilot). The interactive
  unit-test suite is agent-visible by design, which conflicts with the
  hidden-test protocol; adopting it would require the same re-contracting
  effort as Aider. Deferred.

## Hard-gate summary for new candidates

| Candidate | Size | Verifier | License | Key gate risks | v1 verdict |
| --- | ---: | --- | --- | --- | --- |
| KernelBench | 250 | randomized-input correctness + pinned-GPU timing | MIT | timing noise, GPU pinning, reward hacking | **Adopt subset** |
| TritonBench | 184+ | execution + speedup (ignore CodeBLEU) | Unknown | env pins, overlap with KernelBench | Defer (use KernelBench triton backend) |
| SWE-Perf | 140 | runtime delta on PR tests | Unknown | env isolation, expert-solution visibility, timing noise | Pilot after protocol review |
| DABstep | ~450 | deterministic answer match | verify | single-value guessing | **Adopt subset** |
| DSBench | 540 | value/metric comparison | **non-commercial** | redistribution ban, possible image inputs | Conditional subset |
| MatPlotBench | 100 | GPT-4V judge | Unknown | LLM-judge oracle | Adopt tasks + Cospa grader |
| PandasPlotBench | TBD | GPT-4o judge | Unknown | LLM-judge oracle | Adopt tasks + Cospa grader |
| Plot2Code / ChartMimic | 368 / 4,800 | execution + image compare | various | vision input required | Exclude (text-only models) |
| KernelBot | growing | their infra | — | not self-hostable | Exclude |
| Commit0 | 54–57 | visible unit tests | Unknown | test visibility | Exclude for now |
| SWE-Lancer | 1,400+ | E2E tests in Docker | verify | pinning, overlap with FeatureBench | Later pilot |
| R2E-Gym | 8.1K | hybrid test+equivalence | Apache-2.0 | procedural quality | Later source |

Every adopted task still passes the standing qualification pipeline:
pinned source revision and digests, hidden artifacts confirmed absent from
the agent workspace, three clean null and three clean gold observations,
and cold/warm verifier timing recorded.

## `cospa_wide` v1 strawman

Purpose: one manifest, many problem shapes, **adapter-first reporting**.
Per-domain scores are the headline; a blended score is never reported as
capability (domains have different difficulty floors). Sizes are
planning targets, not commitments:

| Domain | Source | Slots | Notes |
| --- | --- | ---: | --- |
| Contract implementation | `aider_cospa` reviewed subset | 24–30 | continues existing work, slotted not centered |
| Repository issue resolution | bake-off winner subset | 20–24 | from the parallel repo review |
| Terminal / ops | Terminal-Bench Core subset | 12–16 | extends existing 8-task pilot |
| GPU kernels | KernelBench L1/L2 (+ triton backend) | 16–20 | pinned GPU, local baselines, `fast_p` diagnostic |
| Repo performance optimization | SWE-Perf subset | 8–12 | after protocol review |
| Data science | DABstep subset (+ DSBench if licensed) | 12–16 | Harbor path exists |
| Visualization | PandasPlotBench/MatPlotBench + Cospa grader | 10–12 | blocked on deterministic grader |
| Text manipulation | Cospa-authored | 12–16 | blocked on authoring |
| Feature implementation | FeatureBench Lite subset | 6 | already pinned |

Total ≈ 120–150 slots. At a 30-minute planning ceiling that is 60–75
serial hours, ~19–23 ideal `c=8` hours — within the Ornith pilot's 9.6 h
campaign budget only at higher concurrency or smaller slots; real sizing
follows measured per-domain walls per the EVALS.md concurrency method.

Protocol requirements for harness comparison:

- identical task manifest, order, seeds, and capability budgets across
  adapters (per EVALS.md capability-budget methodology);
- `k≥2` independent trials per adapter×model cell; report paired
  per-task flips and Wilson intervals per domain, never best-of-k;
- kernel domain: fixed GPU, clocks and driver pinned, model serving
  scheduled off the eval GPU (or accept and record contention);
- visualization domain: deterministic grader with three-observation
  gold/null before any adapter runs;
- every domain keeps source benchmark IDs for provenance; `cospa_wide`
  is a Cospa manifest, not an external leaderboard reproduction.

## Sequencing

1. Deterministic plot grader + gold/null screen on ~30 candidate viz
   tasks (unblocks a whole domain; bounded R&D).
2. KernelBench subset: pin GPU/baselines, three-observation null/gold on
   ~20 tasks (correctness-only for nulls; speedup gates for gold).
3. DABstep subset via the Harbor path; verify license and grading
   determinism on ~16 tasks.
4. Author the text-manipulation mini-corpus (contracts + hidden
   fixtures + gold/null), 3–4 languages.
5. SWE-Perf protocol review (artifact isolation above all), then
   containerize and screen 8–12 tasks.
6. Assemble `cospa_wide` manifest v0 with per-slot provenance; run the
   first adapter A/B (pi_vanilla vs pi_devstack) on one model before
   widening the matrix.

## Open questions

- **GPU inventory:** which GPU(s) does the eval host have, and is one
  dedicated to serving? Kernel-domain comparability is per-GPU; this must
  be pinned in the manifest.
- **Judge policy:** SWE Atlas already carries a pinned LLM rubric as a
  declared exception. Confirm visualization stays programmatic-only so
  `cospa_wide` has no judge-dependent headline.
- **DSBench licensing:** confirm research-only terms are acceptable for
  Cospa's use and that manifests reference but never redistribute data.
- **Adoption authority:** this survey proposes; `docs/EVALS.md` disposes.
  The repo-suite bake-off and this domain survey should be merged into
  one portfolio decision there.

## References

- KernelBench — https://github.com/ScalingIntelligence/KernelBench ; arXiv 2502.10517
- TritonBench — https://github.com/thunlp/TritonBench ; arXiv 2502.14752
- SWE-Perf — https://github.com/SWE-Perf/SWE-Perf ; arXiv 2507.12415
- DABstep — https://huggingface.co/datasets/adyen/DABstep ; arXiv 2506.23719
- DSBench — https://github.com/LiqiangJing/DSBench ; arXiv 2409.07703
- MatPlotBench — https://github.com/thunlp/MatPlotAgent ; arXiv 2402.11453
- PandasPlotBench — https://github.com/JetBrains-Research/PandasPlotBench ; arXiv 2412.02764
- Plot2Code — https://github.com/TencentARC/Plot2Code ; arXiv 2405.07990
- ChartMimic — https://github.com/ChartMimic/ChartMimic ; arXiv 2406.09961
- Commit0 — https://github.com/commit-0/commit0 ; arXiv 2412.01769
- SWE-Lancer — https://github.com/openai/SWELancer-Benchmark ; arXiv 2502.12115
- LiveSWEBench — https://github.com/LiveBench/liveswebench
- R2E-Gym — https://github.com/R2E-Gym/R2E-Gym
- KernelBot — https://github.com/gpu-mode/kernelbot ; https://github.com/gpu-mode/reference-kernels
