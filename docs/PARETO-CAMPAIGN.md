# Cospa Pareto evaluation campaign

_Last reviewed: 2026-08-16_

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
no-tool generation with thinking disabled. Agentic baseline runs use `high`.
The completed matched Pareto60 gate rejected devstack `xhigh`: its small,
inconclusive gain over `off` cost more than three times as much. No `xhigh` arm
advances; a reasoning label alone is not evidence of benefit.

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

### What the earlier pilot tasks showed

The original BCB pilot was concentrated on very few discriminating tasks:

- DS4 `pi_devstack` at `off` and `xhigh` both resolved exactly
  `BigCodeBench/162`, `/502`, and `/879`; `xhigh` cost about 3.9 times as much.
- DS4 and Muse `pi_vanilla` Agentic both resolved only `/162` and `/879`;
  Qwen added `/287`.
- DS4 Instruct resolved `/162`, `/502`, and `/879`; Muse resolved only `/162`.

Those pilot differences therefore depended on two to four tasks. `xhigh` was
dominated by `off` on the matched DS4 devstack pilot: equal outcome,
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
billing. `CI` is the standalone 95% Wilson interval for the binary rate; WCC
itself is continuous and its any-hit interval is shown only as a secondary
diagnostic. Token columns are viewer-aggregated from trial manifests:
uncached prompt, cache-read, and completion (output) tokens.

| Suite / observed policy | Result | Task wall | Campaign elapsed | Uncached prompt | Cached read | Output | Estimated cost |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| BCB-Hard Instruct hermetic143, no thinking | 17/143 (11.9%, CI 7.6–18.2) | 41m56s | 7m10s | 28K | 0 | 140K | $0.0430 |
| BCB-Hard Agentic Pareto60, vanilla `high` | 22/60 (36.7%, CI 25.6–49.3) | 1h00m27s | 7m43s for final52 + 1m01s smoke8 | 138K | 1.5M | 168K | $0.0705 |
| Multi-SWE Flash hermetic25, vanilla `high` | 9/25 (36.0%, CI 20.2–55.5) + 1 budget-exhausted | 3h06m19s | 30m36s | 700K | 26.6M | 376K | $0.2779 on 24/25 token-covered tasks |
| Terminal-Bench Pareto20, vanilla `high` | 11/20 (55.0%, CI 34.2–74.2) + 2 budget-exhausted | 1h25m25s | 17m24s | 187K | 3.7M | 140K | $0.0758 on 18/20 token-covered tasks |
| PolyBench balanced64, vanilla `high` | 15/64 (23.4%, CI 14.7–35.1) + 2 budget-exhausted | 7h32m51s | 59m49s | 3.7M | 55.6M | 887K | $0.9187 on 63/64 token-covered tasks |
| FeatureBench Lite Pareto12, vanilla `high` | 2/12 (16.7%, CI 4.7–44.8) | 10h52m raw attempts | 2h40m raw + isolated repair | 2.0M | 140M | 1.2M | $1.02 raw + $0.30 repair |
| SWE-Explore Verified12, vanilla `high` | 0.0968 WCC; 10/12 any-hit (CI 55.2–95.3) | 26m26s | 5m28s | 157K | 1.8M | 58K | $0.0432 |
| **All 336 k=1 tasks** | — | **19h17m summed** | **≈4h50m** | **6.8M** | **229M** | **3.0M** | **$2.45** (+$0.30 repair) |

Budget-envelope observations for the one-pass portfolio:

- About 97% of processed tokens are cache reads; only 6.8M uncached prompt
  and 3.0M output tokens are new compute per full pass.
- FeatureBench consumes 47% of output tokens and 61% of cache reads for 12 of
  336 tasks; it is the budget strain point and the first place to trim.
- BCB Instruct is the cheapest per-task signal (about 18s and $0.0003 per
  task); its zero cache count reflects the single-turn protocol.
- `reasoning_tokens` is zero throughout: locally served vLLM and SGLang do
  not report a separate reasoning count in usage (reasoning text is returned
  in a separate field), while the DeepSeek official API does via
  `completion_tokens_details.reasoning_tokens`.
- The isolated SymPy transport repair added 70M cached tokens and $0.30
  outside the main-table totals.

Durable result roots for this baseline are:

- `results/qualification/bcb-agentic-pareto60-ds4-vanilla-high-c8-smoke-20260815`
- `results/runs/ds4-bcb-instruct-hermetic143-c8-20260816T0300Z`
- `results/runs/ds4-multiswe-hermetic25-c8-20260816T0300Z`
- `results/runs/ds4-terminal-pareto20-c8-20260816T0300Z`
- `results/runs/ds4-polybench-balanced64-c8-20260816T0300Z`
- `results/runs/ds4-featurebench-pareto12-c8-20260815T2300Z` plus
  `results/runs/ds4-featurebench-pareto12-sympy-repair-20260816T0115Z`
- `results/runs/ds4-swe-explore-verified12-c8-20260816T0240Z`

Linear finalist projections preserve each completed panel's measured throughput
and are planning estimates, not promises:

| Proposed run | Projected task wall | Projected c=8 elapsed | Projected cost |
| --- | ---: | ---: | ---: |
| BCB Agentic hermetic143 | 2h24m | about 21m | $0.17 |
| Terminal-Bench full80 | 5h42m | about 1h10m | $0.30, subject to token coverage |
| PolyBench full382 | 45h03m | about 5h57m | $5.48, subject to token coverage |

The full 148-task BCB public spec was screened in the pinned no-network
verifier: 143 ground-truth solutions passed, while five tasks depended on
external URLs or unavailable NLTK data. `bigcodebench_hard_*_hermetic143` is
therefore the largest scored Cospa expansion; “full148” remains only a public
source projection. The retained set had 429/429 gold observations pass and
429/429 null observations fail. DS4 then resolved 17/143 under the separate
no-tool Instruct protocol and 22/60 on Agentic Pareto60. Both cells produced
complete token/cost coverage and no infrastructure, verifier, or budget
failure. Agentic Pareto60 used 1.82M tokens and $0.0705; its 36.7% rate clears
the utility band, but its protocol remains separate from Instruct.

PolyBench qualification froze 135 support candidates without target-model
outcomes: the candidate96, a 32-task adaptive Java extension, and the final
seven eligible small/medium Java tasks. The oracle gate left 82 gold-stable
tasks. `swe_polybench_verified_balanced64` selects 16 per language with all
three task types and near-equal patch-size tertiles; all 192 selected gold
observations pass and all 192 null observations fail under the offline
verifier. Repository caps had to relax to seven Gson tasks in Java and nine MUI
tasks in TypeScript, which remain explicit limitations. The stable pools are
only 22 Java / 22 JavaScript / 21 Python / 17 TypeScript, so a balanced96 score
is not available and will not be fabricated from mechanically failing tasks.
The completed balanced64 baseline resolved 15/64: four each in Java,
JavaScript, and Python and three in TypeScript. Forty-seven tasks were ordinary
incorrect outcomes and two exhausted their 1,800-second agent budgets; there
were no infrastructure or verifier failures. It consumed 7h32m51s summed task
wall, 59m49s elapsed, 60.17M observed tokens on 63/64 tasks, and at least
$0.9187. The 23.4% rate clears the utility band. Balanced96 remains unavailable;
full382 is a finalist-only expansion.

Multi-SWE hermetic25 resolved 9/25 across six of seven languages: 2/4 C, 1/4
C++, 1/5 Go, 1/1 Java, 1/5 JavaScript, 3/4 Rust, and 0/2 TypeScript. Fifteen
outcomes were ordinary incorrect and one C++ task exhausted its 1,800-second
budget; there were no infrastructure or verifier failures. The cell used
3h06m19s summed task wall, 30m36s elapsed, 27.70M observed tokens on 24/25
trials, and at least $0.2779. Keep this source score separate from balanced64.

Terminal-Bench Pareto20 resolved 11/20, with seven ordinary incorrect outcomes
and two official agent-budget expirations. It had no setup, transport, or
verifier failure, used 1h25m25s summed task wall and 17m24s elapsed, and recorded
4.03M tokens / at least $0.0758 on 18/20 tasks. The 55% rate clears the utility
band and supersedes the earlier pilot8 projection; full80 remains a
finalist-only expansion.

FeatureBench's complete official Lite30 split was pinned before target-model
outcomes. Four Level 2 tasks have no released gold patch, and only 21 of the 26
Level 1 tasks passed a first oracle observation in Cospa's no-network Harbor
path. The final `featurebench_lite_pareto12` panel preserves the two stable
pilot rows, adds the fastest mechanically passing row from each unrepresented
repository, and permits one second Seaborn row under a repository cap of two.
It covers 11 repositories; all 36 selected gold observations pass and all 36
null observations fail. This is a distinct repeat-qualified Cospa panel, not an
official Lite30 score. Fast100 is deferred: expanding before fixing Lite's
mechanical attrition would buy cost rather than trustworthy breadth.

The first DS4 c=8 run resolved 2/12 tasks and produced eight ordinary incorrect
native verdicts, one official one-hour agent timeout, and one repeated model-
transport failure. An isolated c=1 repair converted the remaining SymPy task to
an ordinary incorrect native verdict, leaving 2 resolved, 9 incorrect, 1
`budget_exhausted`, and no unresolved infrastructure failures. The eleven native
verifier outcomes had mean task F2P pass rate 0.645 (median 0.771), so the
partial executable diagnostic carries signal beyond the coarse binary score.
The raw c=8 campaign consumed 22 task attempts after the old runner spent up to
three attempts on five initially failing tasks, including a one-hour timeout,
totaling 10h52m task wall, 2h40m elapsed, 143.2M traced tokens including cache
reads, and about $1.02 under checked-in pricing. The timeout-retry bug is fixed;
these raw numbers are a conservative stress measurement, not a clean c=8
throughput baseline. FeatureBench clears the capability utility band, but
scaffold promotion should retain an isolated repair policy and treat its long
wall/cost as milestone evidence rather than routine matrix cost.

The completed diagnostic bake-off selected SWE-Explore Verified12. Its DS4
c=8 run produced a 0.0968 task-macro weighted-core-coverage score after two
invalid answers were counted as zero, with core-line hits on 10/12 tasks, no
infrastructure/verifier failures, 26m26s summed task wall, 5m28s elapsed, 2.05M
total observed tokens, and $0.0432 estimated cost. DABstep's first ten completed
provisional tasks averaged roughly twice the wall time and 1.6 times the tokens,
while resolving only 3/10; its remaining two long tasks were canceled after the
predeclared cost/discrimination decision was already fixed. Weighted core
coverage remains separate from any-hit rate and all coding-resolution scores.

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
| BCB-Hard Instruct | completed hermetic143 | none | Cheap model-only protocol anchor |
| BCB-Hard Agentic | completed Pareto60 | hermetic143 | Function implementation + scaffold sensitivity |
| Terminal-Bench Core | completed Pareto20 | full80 finalists | Broad terminal/tool competence |
| FeatureBench | completed Pareto12 | broader Lite/Full only after new qualification | Long feature implementation + F2P diagnostic |
| SWE-Explore diagnostic | completed Verified12 | broader official strata only after a new gate | Continuous repository-localization signal |

BCB Agentic is cheap enough that DS4 vanilla should normally continue from the
Pareto60 panel to all 143 hermetic tasks. Other adapters first run the same 60
and expand only when paired evidence is unresolved or favorable. The five
full148 exclusions are mechanical no-network failures, not target-model
outcome selection.

### Phase B — repository breadth

| Suite | Routine block | Expansion | Purpose |
| --- | ---: | ---: | --- |
| Multi-SWE-bench Flash | completed hermetic25 | larger source only after utility gate | C/C++/Go/Java/JS/Rust/TS issue repair |
| SWE-PolyBench Verified | completed balanced64 | new qualification before balanced96; full382 finalists | Four-language bug/feature/refactor work |

The qualified PolyBench panel has equal language slots (16 each), all three
task types per language, and near-equal patch-size tertiles. Mechanical
attrition required disclosed effective repository caps of 7 Java / 5
JavaScript / 5 Python / 9 TypeScript. Because this changes weighting relative
to official PBv, use the distinct `swe_polybench_verified_balanced64` suite ID.
The candidate96 and Java extensions are qualification artifacts, not scored
panels; any future balanced96 requires new outcome-blind mechanical candidates.
Full382 retains the source protocol label.

The first routine repository portfolio reports Multi-SWE hermetic25 and
PolyBench balanced64 separately. Their 89 total tasks improve language/task
breadth, but must never be presented as one unweighted synthetic resolved rate.
The Multi-SWE screen excluded three Java tasks with uncached verifier
requirements and two flaky TypeScript gold tasks; its reduced strata remain
visible rather than being silently reweighted.

### Phase C — scaffold ablations

The matched BCB Pareto60 gate is complete. All arms used identical task IDs,
DS4, c=8, and k=1:

| Arm | Resolved | Task wall | Elapsed | Tokens | Cost |
| --- | ---: | ---: | ---: | ---: | ---: |
| `pi_vanilla high` | 22/60 | 1h00m27s | split smoke/resume | 1.82M | $0.0705 |
| `pi_devstack off` | 16/60 | 49m37s | 7m24s | 6.57M | $0.0792 |
| `pi_devstack high` | 19/60 | 56m00s | 8m13s | 6.19M | $0.0761 |
| `pi_devstack xhigh` | 21/60 | 3h11m31s | 47m27s | 16.74M | $0.2587 |

At matched `high`, devstack lost five percentage points to vanilla: four paired
wins, seven paired losses, 49 ties, exact McNemar `p=0.549`, and a seeded paired
bootstrap 95% effect interval of -15 to +5 points. It also cost 8% more. Within
devstack, `xhigh` beat `off` by 8.3 points, with eight wins, three losses, exact
`p=0.227`, and a -1.7 to +18.3 point bootstrap interval, but cost 3.27 times as
much and used 3.86 times the task wall. It fails every predeclared promotion
route: the interval crosses zero, improvement is below 10 points, wins:losses
is below 3:1, and cost exceeds 1.5 times baseline. `high` versus `off` was also
inconclusive (+5 points; five wins, two losses; `p=0.453`).

No devstack arm advances to Multi-SWE, Terminal, PolyBench, FeatureBench, or
SWE-Explore. `pi_vanilla high` remains the campaign scaffold. Preserve the
ablation roots under
`results/runs/ds4-bcb-pareto60-pi_devstack-{off,high,xhigh}-c8-20260815T1830Z`.
Superpowers and Little Coder remain optional future ablations rather than a
reason to launch a Cartesian matrix.

### Phase D — stability and finalist campaigns

The outcome-blind sentinel is frozen as `configs/pareto_stability32_v1.json`
before repeat outcomes exist. Its 32 tasks allocate 8 BCB tasks across every
non-empty library-count/prompt-size stratum, one retained Multi-SWE task in
each of seven languages, five Terminal tasks across a 2 easy / 2 medium / 1
hard mix and five categories, two PolyBench tasks in each of four languages
with distinct task types, and four FeatureBench tasks from distinct
repositories. Seeded SHA-256 ranks select rows only from the mechanically
qualified fixed panels; DS4 baseline outcomes are not selection inputs.

The k=3 wave completed with all 96 attempts authoritative under DS4
`pi_vanilla high` at c=8 (one isolated Lightning trial-3 repair after a
transient endpoint connection error). Results per suite:

| Suite | Tasks | Mean pass probability | Flip tasks | Flip rate | Pairwise disagreement |
| --- | ---: | ---: | ---: | ---: | ---: |
| BCB Agentic strata8 | 8 | 29.2% | 1/8 | 12.5% | 8.3% |
| Multi-SWE language7 | 7 | 14.3% | 2/7 | 28.6% | 19.0% |
| Terminal mix5 | 5 | 40.0% | 2/5 | 40.0% | 26.7% |
| PolyBench language2x4 | 8 | 8.3% | 2/8 | 25.0% | 16.7% |
| FeatureBench distinct4 | 4 | 0.0% | 0/4 | 0.0% | 0.0% |
| Panel diagnostic (not a capability score) | 32 | 18.75% | 7/32 | 21.9% | 14.6% |

Stability conclusions: 25 of 32 tasks (78%) were unanimous across three
independent attempts, so the default k=1 protocol loses little suite-level
signal; 7 flip tasks (21.9%) show stochastic outcomes concentrate in
Terminal (40% flip rate) and repository-repair suites rather than BCB.
Best-of-three was never reported as Pass@1. Durable root:
`results/runs/ds4-pareto-stability32-k3-c8-20260816` with the fail-closed
analysis at `results/reports/ds4-pareto-stability32-analysis.json` and the
one-sheet report at
`results/reports/ds4-pareto-baseline-k1-and-stability32.md`.

Promote only Pareto finalists to BCB hermetic143, full PolyBench, full
Terminal-Bench, FeatureBench Fast/full, or a frozen freshness campaign.
Publish paired effects, standalone uncertainty, language/repository/task-type
cuts, partial executable diagnostics, failure rates, task/campaign time,
tokens, and cost.

### Phase E — finalist promotion decisions

Applying the predeclared gates (paired-effect potential, uncertainty that can
change the frontier, external protocol comparability, and the one-day /
few-million-output-token budget envelope):

1. **Promote BCB-Hard Agentic to hermetic143.** External comparability with
   Instruct hermetic143 over the same 143-task universe under two protocols;
   tightens the 36.7% ±10-point Pareto60 interval to about ±7.8 points.
   Incremental cost about $0.10 and 15 minutes elapsed.
2. **Promote Terminal-Bench to full80.** Pareto20's 55% ±22-point interval
   cannot discriminate models, and Terminal showed the highest k=3 flip rate
   (40%), so breadth is the correct spend on the noisiest suite. Incremental
   cost about $0.23 and roughly one hour elapsed.
3. **Defer SWE-PolyBench full382.** About $5.48 incremental and roughly 5.3M
   additional output tokens would exceed the entire current portfolio and
   break the declared envelope for a ±4-point interval improvement that no
   pending decision needs. balanced64 remains the routine panel; full382
   stays the pre-declared finalist-only expansion.
4. **No promotion** for FeatureBench (pre-declared mechanical-attrition
   deferral), Multi-SWE (no larger mechanically qualified panel exists), or a
   freshness campaign (out of scope for this wave).

Total incremental promotion spend: about $0.33, roughly 650K output tokens,
and about 1.5 hours elapsed — keeping the whole campaign near $3.10 and
3.7M output tokens, inside the envelope. Durable roots:
`results/runs/ds4-bcb-agentic-hermetic143-c8-20260816` and
`results/runs/ds4-terminal-full80-c8-20260816`.

### Phase F — four-model pi_vanilla matrix

The next routine matrix compares four models on the frozen panels under one
identical scaffold:

- **Harness:** `pi 0.84.2`, `pi_vanilla` (`--no-extensions`, seven built-in
  coding tools per `docs/HARNESS-EVAL.md`). Devstack is skipped because none
  of its real-world improvements have opportunity in these hermetic suites.
- **Protocol:** `thinking=high`, `c=8`, `k=1`; BCB Instruct keeps its declared
  no-thinking, no-tool exception.
- **Models:** `shisa/ornith-35b-fp8-block`, `local/deepseek-v4-flash-0731`,
  `local/qwen3.8-27b`, and `codex/gpt-5.3-codex-spark` (128K context — the
  tightest window in the matrix and a real constraint on long episodes).
- **Panels:** BCB Instruct hermetic143, BCB Agentic hermetic143, Multi-SWE
  hermetic25, Terminal full80, PolyBench balanced64, FeatureBench Pareto12,
  SWE-Explore Verified12 — per model.
- **DS4 row:** instruct/multiswe/poly/feature/explore reuse the completed
  baseline cells; the Phase E agentic143 and full80 cells complete the row.
- **Cost note:** Ornith bills real Shisa rates ($0.14 in / $1.04 out per 1M);
  Spark mirrors codex-pool $0 accounting; Qwen's yaml rates are external list
  prices applied to a self-hosted endpoint, so its dollar column overstates
  real spend — compare token columns for that row.
- **Execution:** cells run sequentially per model (one Harbor c=8 row at a
  time alongside unrelated campaigns at c=2, staying at the proven ten-network
  operating point); the local-model relay env is set only for `local/*` rows.
- **Report:** `scripts/generate-report.py` one-sheets per model row plus a
  combined matrix sheet; behavior columns (turns, LLM%, tool calls) are the
  primary cross-model comparison surface.

## Implementation order

Items 1–8 and the matched scaffold gate plus stability sentinel in item 9
are complete as of 2026-08-16; Phase E finalist promotions are executing
(BCB herentic143 and Terminal full80 promoted; PolyBench full382 deferred
with rationale).

1. Freeze this campaign and its nested manifests.
2. Run the qualified BCB Pareto60 and hermetic143 suite IDs.
3. Run the qualified Multi-SWE hermetic25 DS4 baseline.
4. Freeze Terminal-Bench Pareto20.
5. Run qualified PolyBench balanced64; add new mechanical candidates before
   any balanced96 claim.
6. Run the qualified FeatureBench Pareto12 panel; add new mechanically stable
   rows before any broader Lite or Fast100 claim.
7. Use the completed DABStep/SWE-Explore 12+12 bake-off winner:
   `swe_explore_verified12`, scored by task-macro weighted core coverage and
   reported separately from coding resolution.
8. Execute DS4 `pi_vanilla`, `high`, `c=8`, `k=1` suite by suite; retain
   BigCodeBench Instruct as the declared no-thinking/no-tool exception.
9. Run matched scaffold panels, then stability repeats and full finalists.

The live structured task list tracks these units and their dependencies. Every
validated implementation unit receives RED/GREEN tests, a `WORKLOG.md` append,
and an atomic commit before the next unit begins.
