# Cospa Pareto evaluation campaign

_Last reviewed: 2026-08-15_

This document is the operational campaign plan for obtaining the most useful
model/scaffold discrimination per unit of generation time, verifier time, and
estimated cost. `docs/EVALS.md` remains the methodology and benchmark-review
source of truth; `docs/PLAN.md` remains the architecture roadmap.

## Decision

The common baseline for new campaign qualification is:

| Axis | Fixed value |
| --- | --- |
| Model | `local/deepseek-v4-flash-0731` (DS4) |
| Adapter | `pi_vanilla` |
| Client concurrency | `c=8` |
| Independent attempts | `k=1` until the breadth gate passes |
| Agentic thinking | `high`, unless an upstream protocol fixes another value |
| Network | Model endpoint only during the agent phase; verifier offline |
| Headline oracle | Deterministic executable grading |

BigCodeBench-Hard Instruct remains a protocol exception: it uses one greedy,
no-tool generation with thinking disabled. Existing BCB Agentic timing at
`xhigh` is retained as a conservative projection, but new Pareto baseline runs
use `high`. Any `xhigh` arm must first beat `high` or `off` on a matched fixed
panel; a reasoning label alone is not evidence of benefit.

SWE Atlas is deferred from this campaign. Its Q&A and Test Writing tasks are
valuable, but their headline path requires a rubric LLM judge. Cospa will first
spend campaign budget on suites with reproducible executable oracles. Judge-
based suites may return later as separately labeled diagnostics; they do not
block the deterministic portfolio.

## Why the pilot scores are not ranking scores

`configs/ornith_runtime_pilot_v1.json` correctly describes the first panels as
runtime, infrastructure, and validity pilots whose scores are directional.
Their score increments and standalone 95% Wilson uncertainty are:

| Passed / tasks | Score | 95% Wilson interval |
| --- | ---: | ---: |
| 1 / 15 | 6.7% | 1.2–29.8% |
| 2 / 15 | 13.3% | 3.7–37.9% |
| 3 / 15 | 20.0% | 7.0–45.2% |
| 5 / 28 | 17.9% | 7.9–35.6% |
| 12 / 28 | 42.9% | 26.5–60.9% |

The issue is not only percentage quantization. A one-point score increment does
not imply one-point accuracy:

| Distinct tasks | Score increment | Wilson half-width near 20% | Near 40% |
| ---: | ---: | ---: | ---: |
| 15 | 6.67 pp | 19.1 pp | 22.2 pp |
| 28 | 3.57 pp | 14.7 pp | 17.0 pp |
| 60 | 1.67 pp | 10.0 pp | 12.0 pp |
| 64 | 1.56 pp | 9.7 pp | 11.7 pp |
| 96 | 1.04 pp | 7.9 pp | 9.6 pp |
| 148 | 0.68 pp | 6.4 pp | 7.8 pp |
| 382 | 0.26 pp | 4.0 pp | 4.9 pp |

Standalone intervals answer a different question from a matched scaffold
comparison. Scaffold and thinking arms must use identical tasks and be analyzed
with paired wins/losses, an exact McNemar test or paired bootstrap, and a paired
effect interval.

### What the completed tasks actually showed

The current BCB pilot is concentrated on very few discriminating tasks:

- DS4 `pi_devstack` at `off` and `xhigh` both resolved exactly
  `BigCodeBench/162`, `/502`, and `/879`; `xhigh` cost about 3.9 times as much.
- DS4 and Muse `pi_vanilla` Agentic both resolved only `/162` and `/879`;
  Qwen added `/287`.
- DS4 Instruct resolved `/162`, `/502`, and `/879`; Muse resolved only `/162`.

The current aggregate differences therefore depend on two to four tasks.
`xhigh` is dominated by `off` on the matched DS4 devstack pilot: equal outcome,
higher time and cost. This is a stop signal for that arm, not proof that
thinking never helps on the other 133 tasks.

PolyBench provides stronger directional evidence. Every one of DS4's five
resolved tasks is included in Muse's twelve, with seven one-way discordances
and none in the other direction (two-sided exact paired `p = 0.015625` on this
fixed panel). This supports a real difference on pilot28, but not a precise
382-task population estimate. The retained panel is also 22 bug fixes, five
features, and one refactor, with language counts 4 Java / 9 JavaScript /
9 Python / 6 TypeScript; it is not a balanced routine panel.

## Measured DS4 c=8 baseline and projections

These measurements come from the durable 2026-08-15 result trees. `Task wall`
is summed per-task model wall time. `Campaign elapsed` is latest task end minus
earliest task start for the matching cell; it includes the observed c=8
scheduling and contention. Estimated dollars use the viewer's current
checked-in pricing metadata, even when an older manifest recorded zero local
billing.

| Suite / observed policy | Result | Task wall | Campaign elapsed | Estimated cost |
| --- | ---: | ---: | ---: | ---: |
| BCB-Hard Instruct pilot15, no thinking | 3/15 | 1m43s | 24.5s | $0.0023 |
| BCB-Hard Agentic pilot15, vanilla `xhigh` | 2/15 | 29m04s | 5m25s | $0.0350 |
| SWE-PolyBench pilot28, vanilla `high` | 5/28 | 2h30m | 2h05m | $0.3201 |

Linear projections preserve the observed per-task throughput and are planning
estimates, not promises:

| Proposed run | Projected task wall | Projected c=8 elapsed | Projected cost |
| --- | ---: | ---: | ---: |
| BCB Agentic 60 | 1h56m | 21m40s | $0.14 |
| BCB Agentic 75 | 2h25m | 27m05s | $0.18 |
| BCB Agentic hermetic143 | 4h37m | 51m38s | $0.33 |
| PolyBench balanced64 | 5h43m | 4h46m | $0.73 |
| PolyBench balanced96 | 8h35m | 7h09m | $1.10 |
| PolyBench full382 | 34h08m | 28h25m | $4.37 |

The BCB Agentic projection uses the observed `xhigh` cell and should be an
upper-bound directionally if `high` is cheaper. The full 148-task public spec
was screened in the pinned no-network verifier: 143 ground-truth solutions
passed, while five tasks depended on external URLs or unavailable NLTK data.
`bigcodebench_hard_*_hermetic143` is therefore the largest scored Cospa
expansion; “full148” remains only a public source projection and is not silently
scored with verifier failures. The 143 retained tasks then had 429/429 gold
observations pass and 429/429 null observations fail. A post-integration DS4
`pi_vanilla` `high` c=8 smoke produced eight authoritative native verdicts in
about 61 seconds elapsed (0/8 resolved, 335 summed task seconds, no
infrastructure/verifier failures).
That smoke validates the path, not capability. The PolyBench projection assumes
newly qualified tasks have similar setup and repository costs; qualification
must measure that assumption.

## Pareto rules

1. **Breadth before repetition.** For the same task budget, run more distinct
   tasks before adding `k>1`. Repetition begins only after a panel is broad
   enough to discriminate.
2. **Nested fixed panels.** Freeze task order and nested panel boundaries before
   target-model outcomes. Every compared arm receives the identical panel.
3. **No outcome-selected expansion.** Do not add only tasks that one model
   failed, or drop tasks because an intended model solved them.
4. **Executable oracles first.** Headline promotion requires deterministic
   programmatic grading, repeated null/gold evidence, and hidden-artifact
   isolation. LLM-judge suites are deferred.
5. **Do not average incompatible protocols.** Instruct, agentic function work,
   repository repair, terminal work, feature work, and diagnostic exploration
   retain separate suite IDs and scores.
6. **Reject dominated arms.** Stop an arm when it has no paired correctness
   gain and costs at least 25% more, unless a predeclared diagnostic reason
   requires completion.
7. **Buy precision only when it can change a decision.** Expand a panel when
   paired uncertainty crosses a promotion boundary, not merely to make the
   displayed percentage look smoother.
8. **Separate capability from throughput.** `c=8` is the campaign execution
   baseline, not a model-quality attribute. Record task wall, makespan, queue,
   verifier time, and failures separately.

## Qualification and promotion gates

### Mechanical qualification

A task enters a scored panel only after:

- dataset, repository, image, prompt, and test-command revisions are pinned;
- hidden tests and gold artifacts are unavailable during the agent phase;
- three clean null runs fail the target behavior;
- three clean gold runs pass target and regression checks;
- the verifier runs without public network and distinguishes infrastructure
  failures from incorrect model patches;
- cold/warm setup, verifier time, and resource use are recorded.

### Panel utility

A pilot is useful for routine discrimination when:

- at least 95% of selected tasks produce authoritative native verdicts;
- infrastructure/verifier failures are at most 2% after qualification;
- DS4 vanilla resolution is between 10% and 70%, avoiding a routine floor or
  ceiling;
- at least 20% of tasks are discordant in a matched scaffold probe, or the
  suite supplies a meaningful continuous executable diagnostic;
- its measured c=8 campaign fits the 9.6-hour working budget with 20% reserve.

A suite outside the 10–70% band may remain as an orthogonal anchor, but it does
not earn broad scaffold expansion without another demonstrated signal.

### Scaffold promotion

Run matched arms on the same nested panel. Promote an arm only if one of these
predeclared conditions holds:

- the paired effect interval excludes zero in the favorable direction; or
- the point improvement is at least 10 percentage points, paired wins exceed
  paired losses by at least 3:1, and incremental estimated cost is no more than
  1.5 times baseline.

Do not promote if there are no additional paired wins and time or cost rises by
25% or more. Borderline cells receive more distinct tasks before repetitions.

### Repetition and full-suite promotion

After breadth-first screening, finalists run a fixed 32-task sentinel at `k=3`.
Report all attempts, per-task mean pass probability, and outcome-flip rate.
Never report best-of-k as Pass@1. A finalist reaches a full suite only when the
larger run could plausibly change the Pareto frontier or is needed for external
protocol comparability.

## Nested campaign

### Phase A — cheapest anchors and infrastructure

| Suite | First block | Expansion | Purpose |
| --- | ---: | ---: | --- |
| BCB-Hard Instruct | hermetic143 | none | Cheap model-only protocol anchor |
| BCB-Hard Agentic | Pareto60 | hermetic143 | Function implementation + scaffold sensitivity |
| Terminal-Bench Core | existing 8 | Pareto20, then full80 | Broad terminal/tool competence |
| FeatureBench | existing 6 | Lite30; Fast100 only if promoted | Long feature implementation |
| Diagnostic bake-off | 12 DABStep + 12 SWE-Explore | select one fixed panel | Cheap tool or localization signal |

BCB Agentic is cheap enough that DS4 vanilla should normally continue from the
Pareto60 panel to all 143 hermetic tasks. Other adapters first run the same 60
and expand only when paired evidence is unresolved or favorable. The five
full148 exclusions are mechanical no-network failures, not target-model
outcome selection.

### Phase B — repository breadth

| Suite | Routine block | Expansion | Purpose |
| --- | ---: | ---: | --- |
| Multi-SWE-bench Flash | qualified hermetic25 | larger source only after utility gate | C/C++/Go/Java/JS/Rust/TS issue repair |
| SWE-PolyBench Verified | balanced64 | nested balanced96, then full382 finalists | Four-language bug/feature/refactor work |

The PolyBench panels target equal language slots (16 each at 64; 24 each at
96), repository caps, task-type coverage, and patch-size tertiles. Because this
changes weighting relative to official PBv, use distinct suite IDs such as
`swe_polybench_verified_balanced64` and `..._balanced96`. Full382 retains the
source protocol label.

The first routine repository portfolio reports Multi-SWE hermetic25 and
PolyBench balanced64 separately. Their 89 total tasks improve language/task
breadth, but must never be presented as one unweighted synthetic resolved rate.
The Multi-SWE screen excluded three Java tasks with uncached verifier
requirements and two flaky TypeScript gold tasks; its reduced strata remain
visible rather than being silently reweighted.

### Phase C — scaffold ablations

Use DS4 and the fixed panels to compare `pi_vanilla` with shortlisted adapters.
Start with lower-cost thinking. The existing DS4 devstack `off`/`xhigh` BCB
result blocks `xhigh` expansion until a new matched panel demonstrates added
wins. Compare models only on baseline or winning scaffolds; do not launch the
full model × adapter Cartesian product.

### Phase D — stability and finalist campaigns

Run the 32-task `k=3` sentinel, then promote only Pareto finalists to BCB
hermetic143, full PolyBench, full Terminal-Bench, FeatureBench Fast/full, or a
frozen freshness campaign. Publish paired effects, standalone uncertainty,
language/repository/task-type cuts, partial executable diagnostics, failure
rates, task/campaign time, tokens, and cost.

## Implementation order

1. Freeze this campaign and its nested manifests.
2. Run the qualified BCB Pareto60 and hermetic143 suite IDs.
3. Run the qualified Multi-SWE hermetic25 DS4 baseline.
4. Freeze Terminal-Bench Pareto20.
5. Select and qualify PolyBench balanced64 plus its nested 96 extension.
6. Qualify FeatureBench pilot6 and measure whether Lite30 or Fast100 is the
   better next block.
7. Run the DABStep/SWE-Explore 12+12 diagnostic bake-off and implement only the
   winner first.
8. Execute DS4 `pi_vanilla`, `high`, `c=8`, `k=1` suite by suite.
9. Run matched scaffold panels, then stability repeats and full finalists.

The live structured task list tracks these units and their dependencies. Every
validated implementation unit receives RED/GREEN tests, a `WORKLOG.md` append,
and an atomic commit before the next unit begins.
