# Cospa evaluation portfolio and methodology

_Last reviewed: 2026-08-14_

This document defines what Cospa should measure, how benchmark protocols are
reviewed, which external evaluations are worth adopting, and how long campaigns
are likely to take. It is a decision document, not a claim that every candidate
below is already integrated.

Numerical claims use these labels:

- **Measured here** — calculated from durable Cospa artifacts or a pinned local
  dataset.
- **Published** — reported by the benchmark authors in a paper, repository,
  dataset card, or first-party leaderboard.
- **Planning ceiling** — task count multiplied by a declared per-task budget;
  it is not observed runtime.
- **Estimate** — an explicit extrapolation with its assumptions stated.
- **Unknown / pilot required** — the source does not publish enough evidence.

## Decision

No single benchmark adequately measures modern coding agents. Cospa should use
a portfolio whose components have distinct jobs:

| Role | Evaluation | Policy |
| --- | --- | --- |
| Fast multilingual contract implementation | **`aider_cospa`** | Primary frequent-run panel: complete public contract, hidden behavioral tests, one unrestricted agent episode, no verifier feedback |
| Full source-corpus audit | **`aider_cospa_full`** | All 225 Aider/Exercism instances under the Cospa protocol; releases and corpus research, not every matrix run |
| Legacy comparison | **`aider_canonical`** | Optional reproduction only; never merge its scores with `aider_cospa` |
| Real repository issue resolution | **`cospa_repo`**, selected after a source bake-off | Curate from pinned, revalidated multilingual SWE sources; keep source benchmark IDs and report source-specific results |
| Feature implementation | **FeatureBench Lite**, then selected full tasks | Milestone suite; too expensive for a Cartesian model × adapter matrix |
| Terminal and broad tool competence | **Terminal-Bench Core 0.1.1 now; 2.x at milestones** | Preserve as a separate external anchor with exact task IDs and protocol |
| Harness-sensitive investigation/testing | **SWE Atlas Q&A + Test Writing** | Continue the existing 12-task cost/reliability pilot before expanding |
| Freshness audit | **SWE-bench-Live MultiLang** or a genuinely post-cutoff rolling set | Freeze each evaluated release; use as an audit, not a stable longitudinal score |
| Cheap orthogonal code-generation anchor | **BigCodeBench-Hard Instruct** and/or a post-cutoff LiveCodeBench window | Keep separate from agentic/repository scores |

`aider_cospa` is a protocol design target, not merely a rename of the current
suite. The current Aider suite already hides official tests and reference
artifacts, but the 225 visible contracts still require task-by-task review and,
where needed, augmentation before the name is earned.

## Why Aider's canonical score is not the primary Cospa protocol

Aider Polyglot remains a useful source corpus, but its selection and interaction
protocol answer a muddled question.

1. **Difficulty was model-relative.** Aider ran 697 Exercism instances through
   seven 2024-era models and retained the 225 solved by at most three. This was
   a sensible leaderboard anti-saturation rule in December 2024, not a
   representative sample of software engineering.
2. **The score conflates capabilities.** A retry-aware edit/test loop measures
   some combination of understanding the written task, inferring omitted
   behavior from tests or failures, targeting a particular test suite,
   formatting edits for Aider, and implementing the code. A public API contract
   should not be a puzzle whose answer is the hidden behavior oracle.
3. **Behavioral tests and contracts have different roles.** Tests should verify
   an already visible requirement. When tests supply a requirement that the
   prompt/starter contract omits, the benchmark rewards leakage or guessing,
   not implementation quality.
4. **The corpus is uneven and duplicated.** It is useful to repeat the same
   concept across languages, but repeated concepts must be intentional and
   separately reported rather than accidentally over-weighted.
5. **Modern systems are near the public leaderboard ceiling.** Aider's own
   leaderboard reports top scores in the high eighties. More retries or more
   visible test information would make the ceiling problem worse.

Keep `aider_canonical` only when an exact Aider leaderboard comparison is the
question. A canonical pass rate and an `aider_cospa` pass rate are different
measurements and must have different suite IDs.

## `aider_cospa`: normative protocol

### Agent-visible information

Each task must expose everything a competent developer needs to implement the
public behavior without seeing the grader:

- the complete behavioral contract in natural language;
- exact public module/package paths, symbol names, signatures, types, ownership
  and mutability rules, errors/exceptions, ordering, formatting, and boundary
  behavior where applicable;
- starter source and required build/package metadata;
- normative public examples when they clarify the contract;
- language/toolchain version and the command needed to build or run any public
  checks that are intentionally included.

The contract may permit multiple implementations. It must describe observable
behavior, not prescribe the hidden reference algorithm unless the algorithm is
itself the subject of the task.

### Agent-hidden information

The agent must not receive:

- behavioral test source, hidden fixtures, expected-output tables, or test names
  that reveal unmentioned cases;
- reference implementations, example solutions, `.meta` artifacts, or future
  repository history;
- prior trajectories or results for the same task;
- verifier output during the episode.

A hidden test is allowed to be surprising in input, not in requirement. Any
hidden assertion that cannot be traced to the visible contract is a benchmark
bug.

### Agent freedom and episode boundary

- The agent gets one ordinary coding episode and may inspect, edit, build, and
  create any file inside the task workspace.
- Cospa does not prescribe an implementation strategy or file-edit sequence.
- Public network, sibling tasks, vendor data, reference artifacts, prior
  sessions, and previous results remain unavailable.
- When the agent stops, Cospa ends the episode, injects the hidden tests into a
  clean verifier workspace, and grades once.
- There is no hidden-test feedback retry. Independent `k>1` trials start from a
  pristine workspace and are reported as repeated trials, not as an in-episode
  second chance.

### Scoring

Primary score:

```text
resolved = all required behavioral checks pass and the public API/ABI is intact
```

Diagnostic scores may include hidden assertions passed, compile/build success,
contract sections covered, tokens, turns, tool calls, and timing. Partial test
credit never changes a failed task into a resolved task.

Report at least:

- task-weighted resolution;
- language-macro resolution;
- concept-macro resolution, so a concept ported to five languages does not
  receive five times the weight of a singleton;
- paired cross-language outcomes for repeated concepts;
- infrastructure failure and budget-exhaustion rates, separate from incorrect
  solutions.

## What the 225 tasks actually contain

**Measured here** from the currently vendored source corpus:

| Language | Tasks |
| --- | ---: |
| C++ | 26 |
| Go | 39 |
| Java | 47 |
| JavaScript | 49 |
| Python | 34 |
| Rust | 30 |
| **Total** | **225** |

The 225 instances contain only **100 unique exercise names**. Fifty-eight
concepts occur in two to five languages, accounting for **183 task instances**;
42 concepts are language singletons. Multiplicity is: 42 concepts in one
language, 21 in two, 17 in three, 10 in four, and 10 in five. Every task has an
instruction file and at least one non-empty implementation artifact, but that
structural check does **not** prove that its public contract is complete.

### Target composition

The primary panel should target approximately:

- **50% repeated-concept task slots**, selected to support direct cross-language
  comparisons; and
- **50% language-specific or singleton task slots**, selected for idioms and
  capabilities that generic algorithm ports miss.

The unit is a task slot, not a concept. Otherwise a five-language family would
silently distort the ratio. The checked-in manifest must state every concept,
language, source revision, category, and inclusion reason.

### Required 225-task review

Every source instance receives a versioned annotation before inclusion:

| Field | Review question |
| --- | --- |
| Contract completeness | Can every hidden assertion be justified from visible text, signatures, and public artifacts? |
| API/ABI | Are paths, names, types, errors, mutation, ownership, ordering, and formatting explicit? |
| Behavioral value | Does the task require meaningful implementation rather than boilerplate, trivia, or output transcription? |
| Hermeticity | Does it run offline with pinned tools/dependencies and deterministic inputs? |
| Grader validity | Does the gold implementation pass and the starter/null implementation fail for the intended reason? |
| Flakiness | Do gold, starter, and verifier outcomes remain stable across repeated clean runs? |
| Security/integrity | Are tests and references absent from the agent workspace and inaccessible through paths/history/network? |
| Category | Algorithm/data structure, parsing/transformation, stateful API, concurrency, numeric, systems/I/O, domain simulation, or language-specific idiom |
| Duplication role | Repeated cross-language control or language-specific signal? |
| Decision | Include, include after contract augmentation, exclude, or replace—with a written reason |

Exclusion is appropriate for ambiguous contracts, invalid or flaky tests,
formatting-only work, dependence on unavailable external state, or tasks whose
starter already contains the substantive solution. Difficulty alone is not an
inclusion criterion. Replacements should come from a pinned, licensed source
and pass the same review.

## Cospa benchmark acceptance criteria

These criteria apply to external suites as well as Cospa-authored tasks.

### Hard gates

1. **Specification sufficiency.** All required observable behavior is visible
   to the agent. The verifier may hide examples, not requirements.
2. **Independent verification.** Correctness is established by executable,
   implementation-agnostic checks. An LLM judge may score qualitative subchecks
   but should not be the sole headline oracle where a programmatic one is
   possible.
3. **Gold/null evidence.** A gold artifact passes; the pre-solution or null
   artifact fails the target checks; regressions remain passing.
4. **Artifact isolation.** Hidden tests, gold patches, oracle solutions, and
   future commits are not agent-readable.
5. **Reproducibility.** Dataset revision, task IDs, images, commands, model,
   scaffold, prompts, sampling, budgets, and verifier resources are pinned.
6. **Failure separation.** Setup, image, model transport, timeout/budget,
   verifier, and incorrect-solution outcomes are distinct.
7. **Legal usability.** Dataset and source-repository licenses permit the
   intended local evaluation and redistribution of any Cospa manifest or
   patches.

### Selection criteria

Prefer evaluations that add one of these missing signals:

- balanced multilingual behavior on comparable work;
- repository exploration, localization, multi-file editing, and regression
  avoidance;
- feature implementation rather than predominantly small bug fixes;
- build/test/debug loops and recovery from tool errors;
- fresh, post-training-cutoff tasks;
- deterministic terminal or production-system outcomes;
- behaviorally rich trajectories that Cospa can normalize and inspect.

Avoid selecting a suite merely because it is large, popular on model cards, or
hard for an old model cohort. Measure repository, language, task-type, patch
size, and concept concentration before freezing a subset.

## Time and budget methodology

### Do not score GPU speed as coding ability

A hard 600-second deadline currently allows the same model to pass or fail based
on serving throughput, GPU placement, queueing, cache state, and concurrent
load. Cospa should separate:

- **capability budget:** output tokens, model calls/turns, tool calls, and
  optionally normalized total tokens;
- **safety wall:** a generous deadlock/runaway bound, recorded as
  `budget_exhausted` or infrastructure-limited rather than ordinary
  `incorrect`;
- **efficiency measurements:** queue time, provider inference time, tool time,
  verifier time, total wall time, tokens, and cost.

The safety wall can still terminate a pathological run, but leaderboard
capability should be compared under matched capability budgets. Latency and
throughput should be reported alongside correctness, not baked invisibly into
it.

### Concurrency must be measured, not assumed

For `N` tasks, mean per-task wall time `m_c` under concurrency `c`, and negligible
setup overhead:

```text
makespan(c) ≈ N × m_c / c
speedup(c)  ≈ c × m_1 / m_c
```

If two simultaneous requests leave per-task latency unchanged, `c=2` approaches
2× speedup. If contention doubles per-task latency, `c=2` provides no speedup.
`c=N` is not a meaningful default for one GPU-backed endpoint: it can increase
queueing, memory pressure, tail latency, and timeout rates while reducing
throughput.

For every model/server configuration, run the same randomized task block at
`c=1` and `c=2`; record completed tasks/hour, tokens/second, p50/p90/p99 task
wall time, provider queue and generation time, timeout rate, GPU utilization,
and score. Test higher concurrency only after `c=2` improves throughput without
changing failure semantics. Keep model, weights, quantization, sampling,
scaffold, task order, and server settings fixed.

### Current clean Aider timing snapshot

**Measured here** from post-hidden-test-cutover `pi_vanilla` trials present on
2026-08-14. These runs were still in progress, so projections are provisional.

| Model | Completed trials | Mean/task | Median/task | Projected 225-task serial wall | Ideal `c=2` makespan |
| --- | ---: | ---: | ---: | ---: | ---: |
| DeepSeek V4 Flash 0731 | 86 | 2.81 min | 2.14 min | 10.5 h | 5.3 h |
| Muse-Glimmer 30B | 13 | 4.14 min | 3.84 min | 15.5 h | 7.8 h |
| Ornith 35B | 2 | 10.0 min | 10.0 min | Not estimable; both hit the current cap | Not estimable |

The `c=2` column is arithmetic, **not a measured speedup**. It assumes `m_2 =
m_1`, no retries, and no additional timeouts. The current 10-minute wall cap
also makes the Ornith sample censored. A 100-task contract panel would project
to about 4.7 serial hours for DeepSeek and 6.9 for Muse at these provisional
means.

### Cross-benchmark planning table

Agent-generation time usually dominates, but image pulls/builds and verification
can dominate a cold first run. Except where noted, external authors do not
publish end-to-end elapsed time, so a local pilot is required.

| Evaluation | Size / official repetition | Published timing or budget evidence | Practical one-pass planning |
| --- | --- | --- | --- |
| `aider_cospa_full` | 225 × `k=1` | Cospa currently has a 10-minute safety wall | Provisional measured projections above; absolute cap is 37.5 serial hours |
| Terminal-Bench Core 0.1.1 | 80 × `k=1` in Cospa | No complete local row | At a hypothetical 30-minute episode ceiling: 40 serial h, 20 h ideal `c=2`, 5 h ideal `c=8`; pilot required |
| Terminal-Bench 2.x | 89 tasks; official campaigns commonly repeat | **Published:** most agent trials finish under 20 minutes; extremes reach two hours | If every trial took 20 minutes: 29.7 serial h for `k=1`; 148.3 h for `k=5`. Actual distribution and compatible task list must be pinned |
| SWE Atlas pilot | 12 × `k=1`, then matched `k=2` if promoted | Published cost for selected Q&A/Test Writing systems is about $0.35–$1.90/task; wall time unknown | Cospa gate: ≤2 h summed agent time and ≤4 h setup+agent+judge for first 12; pilot required |
| Multi-SWE-bench Flash | 300 × `k=1` | No published E2E runtime | At a 30-minute Cospa episode ceiling: 150 serial h; 75 h ideal `c=2`; 18.8 h ideal `c=8`, plus verification |
| SWE-bench Multilingual | 300 × `k=1` | Baseline used a $2.50/task cost limit; time unknown | Same 150 h / 75 h / 18.8 h planning ceiling under a 30-minute policy |
| SWE-PolyBench Verified | README says 382; dataset card has stale conflicting count | Harness recommends 10–12 evaluator threads on 16 cores/64 GB; inference time unknown | At 382 × 30 minutes: 191 serial h; 95.5 h ideal `c=2`; 23.9 h ideal `c=8` |
| FeatureBench Lite / Full | 30 / 200 | Default task timeout 3,600 s; published OpenHands runs allow 500 steps and consume 2.6M–9.0M input tokens/task on Lite | Timeout ceiling: 30 / 200 serial h; ideal `c=8`: 3.75 / 25 h, before cold setup and contention |
| SWE-bench-Live MultiLang | 743 in current README | Runtime unknown; large multilingual builds/tests | At 30 minutes/task: 371.5 serial h; 185.8 h ideal `c=2`; 46.4 h ideal `c=8` |
| SWE-bench Pro public | Currently 730 leaderboard tasks; 250-turn uncapped model runs | Published task intent is hours to days for humans; agent wall distribution not published | Not a routine local run. Pilot required; use public trajectories before generating new ones |
| BigCodeBench-Hard | 148, normally one generated program/sample for Pass@1 | **Published verifier time for the whole set:** 4–5 min on hosted Gradio or 15–20 min on default E2B | Generation time is model/server dependent; verification itself is cheap |
| LiveCodeBench v6 | 1,055 problems; official setup defaults to `n=10` samples | Runtime not published; authors warn timeout settings can move score by <0.5 points | 10,550 generations before repair scenarios. Use `n=1` only if explicitly defining a different protocol |

A 30-minute row is a **planning ceiling**, not a recommendation that every
suite use the same wall timeout. Before any 300+ task campaign, measure 5–12
representative tasks at `c=1` and `c=2`, including cold and warm verifier costs.

### Frozen Ornith runtime pilot v1

`configs/ornith_runtime_pilot_v1.json` is the source of truth for the first
outcome-blind timing/validity wave. It pins source and dataset revisions,
content hashes, exact task IDs, strata, the model/scaffold, telemetry, stop
rules, and a `c=1/2/4/8/16` ladder. The pilot sizes are:

| Evaluation | Pilot | Current gate |
| --- | ---: | --- |
| Aider source corpus | 23 / 225 | Blocked until the contract audit freezes eligible tasks |
| Terminal-Bench Core 0.1.1 | 8 / 80 | Source and Harbor 0.16.1 ready; fresh Docker smoke required |
| SWE Atlas pilot12 | 12 / 12 | Pinned tasks ready; judge credentials/endpoint required |
| Multi-SWE-bench Flash | 30 / 300 | Dataset and 30 image digests locked; gold/null/repeat validation pending |
| SWE-bench Multilingual | 30 / 300 | Dataset and 30 image digests locked; gold/null/repeat validation pending |
| SWE-PolyBench Verified | 38 / 382 | Harbor adapter ready; representative Gson gold passes and null fails offline; remaining 37 plus repeats pending |
| FeatureBench Lite | 6 / 30 | Dataset and 6 image digests locked; gold/null/repeat validation pending |
| BigCodeBench-Hard Instruct | 15 / 148 | Non-agentic adapter ready; 15/15 gold pass and 15/15 null fail; Ornith smoke pending |

**Measured setup state, 2026-08-14:** the host has 683 GiB free on `/`; all
listed source repositories and external dataset files are present at the
manifested revisions/checksums. All 105 selected Linux/amd64 task/verifier
images resolve to immutable platform-manifest digests in
`configs/ornith_runtime_pilot_images_v1.json`. This is setup evidence, not
verifier evidence: do not run a target model on a repository suite until its
selected images survive repeated null/gold checks. BigCodeBench is the first
suite through that gate: its shared verifier passed all 15 selected gold/null
pairs, with three clean repeats of each condition on `BigCodeBench/15`.
SWE-PolyBench now has representative end-to-end Harbor evidence on
`google__gson-1989`: the clean null fails F2P with 4/6 tests passing and an
empty model patch, while gold resolves 6/6 with the verifier offline. This
proves the adapter path, not the remaining 37 selected images or repeat gate.

The operational goal is a result within 12 hours with 20% reserve, so the
campaign budget is 9.6 hours. If c=16 scaled perfectly, the maximum mean task
walls for a full campaign would be about 41.0 minutes for 225 tasks, 115.2 for
80, 30.7 for 300, 24.1 for 382, 307.2 for 30, and 62.3 for 148. These are
feasibility thresholds, **not runtime estimates**. Measured throughput,
tail latency, setup costs, and failure rates decide whether c=16 is retained.

## Methodology review of leading candidates

### Aider Polyglot source corpus

- **Construction:** 225 of 697 Exercism instances, selected because at most
  three of seven 2024 models solved them; six languages.
- **Evaluation:** language-native tests and Aider edit-format accounting;
  canonical harness supports multiple tries and reports `pass_rate_1`,
  `pass_rate_2`, and so on.
- **Strength:** small isolated multilingual implementations and repeated
  cross-language concepts.
- **Risk:** model-relative selection, contract/test conflation, uneven language
  weights, repeated-concept over-weighting, and current-model saturation.
- **Cospa decision:** task source only. Re-contract and revalidate all 225;
  preserve canonical protocol under a separate suite ID.

### Multi-SWE-bench and Multi-SWE-bench Flash

- **Construction:** the full benchmark has 1,632 issue/PR instances across Java,
  TypeScript, JavaScript, Go, Rust, C, and C++. Repositories must be popular,
  maintained, CI-backed, and buildable. Candidate PRs link issues, modify tests,
  and are merged.
- **Validation:** the authors run the full test suite at base, with the test
  patch, and with test+fix patches; they reject regressions and require a
  fail-to-pass transition. Sixty-eight language-qualified annotators perform
  independent dual annotation and cross-review, with an internal quality team
  requiring at least 80% annotation accuracy.
- **Evaluation:** agent receives issue context and pre-fix repository, generates
  a patch, and is scored by resolved rate against transition-based tests.
- **Flash:** 300 tasks. **Measured from the released JSONL:** C, C++, and Java
  have 40 each; Go, JavaScript, Rust, and TypeScript have 45 each, across 24
  repositories. The dataset card does not document how those 300 were sampled
  from the verified full set.
- **Strength:** strongest published multilingual human-verification pipeline in
  this group; full-suite testing catches regressions.
- **Risk:** no Python, some repositories dominate individual languages, the
  Flash selection rule is undocumented, and the full Hugging Face viewer
  currently errors on schema casting. Hints added after release also require an
  exact revision and visibility policy.
- **Cospa decision:** leading `cospa_repo` source after the Flash selection is
  audited and every chosen image passes local gold/null/repeat checks.

### SWE-bench Multilingual

- **Construction:** 300 manually curated tasks from 42 repositories in C, C++,
  Go, Java, JavaScript/TypeScript, PHP, Ruby, and Rust. Roughly 30% of candidate
  repositories were discarded because they could not be built or tested in a
  practical time.
- **Validation:** manual per-instance install/build/test procedure, requiring
  tests introduced by the PR to fail before the gold code change and pass after
  it. Existing pass-to-pass tests guard regressions.
- **Evaluation:** standard SWE-bench issue + pre-solution repository → patch →
  hidden F2P/P2P resolution.
- **Strength:** mature SWE-bench-compatible harness, nine-language breadth,
  manageable fixed size, and straightforward manual curation story.
- **Risk:** no independent human difficulty/quality annotations, only one
  initial baseline, and median gold patches modify just 10 lines. This can
  over-represent localized fixes rather than substantial engineering.
- **Cospa decision:** best operationally conservative repo candidate and useful
  external release suite; compare with Multi-SWE Flash rather than assuming one
  is superior.

### SWE-PolyBench

- **Construction:** 2,110 real issue/PR tasks from 21 repositories in Python,
  Java, JavaScript, and TypeScript. PRs must include tests and at least one F2P.
  The collection excludes cases where a new production file is tested, because
  alternate correct file placement is difficult to grade.
- **Subsets:** PB500 has 125 tasks per language and an intentional 40% bug / 40%
  feature / 20% refactor mix. A later Verified split is described as **382** in
  the current repository README after duplicate removal, while the Hugging Face
  card still says **394**. The exact dataset revision and row count are a hard
  pinning gate.
- **Evaluation:** F2P + P2P resolved rate, plus optional file- and concrete
  syntax-tree-node localization metrics. Public prebuilt instance images are
  expected to pass gold patches.
- **Strength:** explicit task-type balance in PB500, useful localization
  diagnostics, and more multi-file work than SWE-bench Verified.
- **Risk:** only four languages; task categories and issue informativeness are
  LLM-classified; new-file exclusion biases feature coverage; maintainers have
  already corrected images and duplicate-like entries.
- **Cospa decision:** include in the repo bake-off, especially for
  feature/refactor balance, but reject any unpinned “Verified” alias.

### FeatureBench

- **Construction:** 200 Python feature tasks from 24 repositories. The pipeline
  dynamically traces F2P and P2P tests, builds a dependency graph, removes the
  target implementation, and generates a visible task description and explicit
  callable interface. L1 restores a partially implemented repository; L2 asks
  for the feature from scratch. The 30-task Lite split was manually reviewed.
- **Validation:** the stripped code must retain P2P behavior, lose F2P behavior,
  and return to full passage when the extracted gold patch is reapplied.
- **Evaluation:** resolved rate requires all F2P and P2P checks; mean F2P passed
  is a partial diagnostic; token I/O is reported.
- **Strength:** explicit interfaces and substantial implementation work. The
  paper reports L1 gold solutions averaging 790 lines across 15.7 files. Its
  ablations directly support Cospa's protocol: removing interface descriptions
  hurts performance, while exposing unit tests increases resolved rate by about
  43–50 points in the reported Lite experiments.
- **Risk:** Python-only; tasks are generated by deleting traced functionality
  rather than taken directly from a natural issue; LLM classification and
  docstring generation can make boundaries artificial. Very high token use
  makes even “Lite” a milestone suite.
- **Cospa decision:** strongest fixed feature-development pilot. Run Lite with
  one winning scaffold, not across the full matrix.

### SWE-bench-Live MultiLang and RepoLaunch

- **Construction:** the current project README reports 743 tasks across six
  language groups and 381 repositories. RepoLaunch uses an LLM-driven workflow
  to select an image, build repositories, derive rebuild/test commands, and
  generate test-log parsers. A reasoning model screens whether the issue states
  enough to infer the tests and whether it leaks the solution.
- **Validation:** retain tasks whose tests fail/skip/do not run before the fix
  and pass afterward while regression tests remain passing. The dataset is
  updated over time; the paper's earlier 612-task/303-repository count and the
  current README count differ as expected for a live set.
- **Strength:** broad repository diversity, recent issues, automated
  multilingual environments, and a realistic way to generate rolling audits.
- **Risk:** LLM screening and generated parsers are weaker evidence than
  task-level human review. Large builds can timeout/OOM; public release means
  “contamination-free” decays over time. A moving dataset cannot support a
  longitudinal score unless each release and task list is frozen.
- **Cospa decision:** freshness audit after local oracle/flakiness filtering,
  not the stable primary repo score.

### SWE-rebench

- **Construction:** 21,336 Python interactive tasks from 3,468 repositories via
  automated installation recipes, execution validation, and LLM quality labels.
  Its paper benchmark uses 294 tasks from 169 repositories.
- **Quality evidence:** the quality classifier is trained from SWE-bench
  Verified annotations; reported validation accuracy is 79% for issue clarity,
  81% for complexity, and only 67% for test-patch correctness.
- **Evaluation:** a standardized ReAct scaffold and five independent runs are
  used to expose variance; the leaderboard benchmark is private even though the
  large training dataset and harness are public.
- **Strength:** scale, freshness, diversity, and explicit concern for repeated
  trials and scaffold comparability.
- **Risk:** Python-only, automated quality is imperfect, and private benchmark
  tasks prevent fully transparent local reproduction.
- **Cospa decision:** borrow its repetition/reporting discipline and consider
  its public data for training research; do not make a private leaderboard the
  primary Cospa suite.

### SWE-bench Pro

- **Construction:** 1,865 long-horizon tasks across 41 repositories: 11 public,
  12 held out, and 18 commercial/proprietary. The public evaluation currently
  reports 730 problems after test corrections; older material says 731.
- **Evaluation:** issue + repository → patch with Docker-based tests. Public
  leaderboard runs use a unified SWE-Agent setup, an uncapped model cost, and a
  250-turn limit.
- **Strength:** larger multi-file, enterprise-shaped tasks and extensive public
  trajectories for analysis.
- **Risk:** enormous run budget, only four public languages, private partitions,
  and recent removal of outdated/unintended tests. Cardinality and scripts have
  changed, so revision pinning is mandatory.
- **Cospa decision:** analyze released trajectories; do not regenerate the full
  public set for routine model screening.

### Terminal-Bench 2.x

- **Construction:** the Terminal-Bench 2.0 paper describes 89 diverse terminal
  tasks selected from 229 contributions. Each task has an instruction,
  container, tests, human solution, and time limit. Three experienced reviewers
  assess specification, solvability, and integrity, averaging about three
  reviewer-hours per retained task.
- **Evaluation:** the agent may manipulate the container freely; tests grade the
  final state, not the command sequence. Authors ran at least five trials per
  model/agent configuration and collected 32,155 trajectories.
- **Strength:** unusually strong task-level review, broad real terminal work,
  outcome-based grading, and published trajectory analysis.
- **Risk:** official agents may use the internet even though tasks and oracle
  solutions are public; resource enforcement and network behavior can vary.
  The paper calls the dataset 89 tasks while an appendix token table describes
  totals over 74 evaluated tasks, so comparison requires an exact registry
  release and task-ID list, not only the name “2.0/2.1.” Cospa's model-only
  network boundary is also stricter than the paper's internet-enabled setting.
- **Runtime:** **published:** most attempts finish in under 20 minutes, but some
  take up to two hours, hundreds of calls, and nearly 100M tokens on one task.
- **Cospa decision:** Core 0.1.1 remains the immediate 80-task anchor; use a
  current 2.x release only for milestone campaigns with protocol differences
  disclosed.

### BigCodeBench-Hard

- **Construction:** BigCodeBench has 1,140 Python function-level tasks using 139
  libraries across seven domains, produced through GPT-4-assisted synthesis,
  iterative execution, and extensive human curation. Tasks average 5.6 tests
  and reported 99% branch coverage. Hard contains 148 selected tasks.
- **Evaluation:** Complete supplies structured docstrings; Instruct supplies a
  shorter natural-language request. Program execution yields Pass@1/Pass@k.
- **Strength:** cheap, objective coverage of practical API composition and
  complex instruction following.
- **Risk:** Python-only, synthetic, one-shot, and not repository-agent work.
  “Calibrated” scores add omitted setup/imports, so the score must be labeled
  calibrated and the original model completion retained for audit.
- **Cospa protocol:** one OpenAI-compatible user message, no system prompt or
  tools, greedy `n=1`, upstream sanitizer, and calibrated scoring in the
  immutable network-disabled evaluator. The frozen public prompt spec contains
  no tests or canonical solutions. Across the pilot15, 15/15 gold solutions
  pass, 15/15 null solutions fail, and the upstream ground-truth rate is 1.000;
  `BigCodeBench/15` repeats each condition cleanly three times.
- **Cospa decision:** good low-cost orthogonal anchor, never a replacement for
  `aider_cospa` or `cospa_repo`, and never an arm in the scaffold matrix.

### LiveCodeBench

- **Construction:** contest problems from LeetCode, AtCoder, and Codeforces,
  timestamped to permit post-cutoff evaluation. The current repository lists
  release v6 with 1,055 problems through April 2025. Tests are platform-provided
  where available and generator/LLM-produced otherwise.
- **Evaluation:** code generation, self-repair with one failure, code execution,
  and test-output prediction. The published setup uses `n=10`, temperature 0.2,
  and Pass@1/Pass@5; the fast default prunes many tests.
- **Strength:** time-windowed algorithmic signal and several code reasoning
  modes, with known benchmark errata tracked publicly.
- **Risk:** not agentic or repository-level; generated tests can be imperfect;
  timeout/process settings can move scores. A set ending in April 2025 is not
  contamination-resistant for a model trained later unless newer tasks are
  added.
- **Cospa decision:** use only a pinned, genuinely post-cutoff window as an
  orthogonal algorithmic audit.

## Existing and additional Cospa candidates

### SWE Atlas

Cospa already pins a 12-task pilot: eight Test Writing and four Codebase Q&A
items balanced across Go, Python, C, and TypeScript. Upstream has 284 public
tasks: 124 Q&A, 90 Test Writing, and 70 Refactoring. Harbor-native environments
make scaffold substitution practical, but scoring combines deterministic checks
with a pinned LLM rubric judge. Published leaderboard protocols use `k=3`, up
to 250 steps, and long sandbox ceilings; actual wall-time distributions are not
published. Complete the real judge-backed 12-task run before expanding.

### Other high-value but non-routine suites

| Candidate | Signal | Scale/cost evidence | Position |
| --- | --- | --- | --- |
| APEX-SWE | Production observability and multi-service integration | 200 hidden + 50 public; one-hour task ceiling; token distribution unknown | Best later production trace stress, after a cheaper pilot |
| DeepSWE | Long-horizon multilingual repo work | 113 tasks; public rows report 46K–276K output tokens, 61–268 steps, roughly $2.36–$26.40/task | Frontier milestone only |
| FreshBrew | Java/Maven JDK 8→17/21 migration with compile, tests, and coverage guard | 228 repos, up to 100 steps | Strong deterministic specialist fallback |
| RACE-bench | Feature planning and intermediate reasoning | 100-task Lite; published medians about 156–1,121 seconds and 145K–3.49M tokens/task | Planning diagnostic, not routine matrix |
| SWE-Cycle | Environment, implementation, test generation, and full lifecycle | 489 issues; FullCycle permits three hours/task and an execution-capable judge | Long-horizon milestone |
| SWE-Explore | Repository exploration/localization without patch generation | 848 issues, ten languages; runtime distribution unknown | Useful exploration A/B, score separately |
| SWT-Bench Verified | Issue-to-test generation | 433 Python tasks; specialized systems near saturation | External testing anchor; SWE Atlas is broader |
| ProgramBench | Black-box clean-room reimplementation | 200 programs, 248K tests; near floor and some reported runs cost thousands of dollars | Future frontier, not current screening |

General reasoning sets such as MMLU-Pro, GPQA, GSM8K, or tool-free HLE may be
useful model sanity checks, but they do not test repository navigation, editing,
builds, tests, recovery, or working artifacts and therefore do not fill Cospa's
coding-agent gap.

## Recommended adoption sequence

### 1. Finish the contract corpus before restarting broad Aider comparisons

1. Create a checked-in 225-row audit manifest with source hashes and the review
   fields above.
2. Review hidden assertions against visible contracts in all six languages.
3. Augment visible contracts without leaking test implementations.
4. Run starter/null and gold artifacts three times in clean verifier sandboxes.
5. Freeze a balanced primary `aider_cospa` manifest and retain all 225 as
   `aider_cospa_full`.
6. Validate one representative task per language end to end before a full run.

### 2. Measure serving concurrency separately

Use one fixed 12–20 task block, randomized once, with the same model and
`pi_vanilla`. Gate first on matched `c=1` and `c=2`, then advance one rung at a
time through `c=4`, `c=8`, and `c=16`. Compare makespan, completed tasks/hour,
p50/p90/p99 latency, endpoint and infrastructure errors, score, and telemetry.
Stop on throughput regression, overload, changed failure semantics, host
pressure, or a p95 task wall above 2.5× the c=1 value. Repeat the block under a
second scaffold only after choosing a safe production concurrency.

### 3. Run a repository-source bake-off

Before defining `cospa_repo`, sample 12 tasks from each of Multi-SWE Flash,
SWE-bench Multilingual, and SWE-PolyBench Verified, stratified by language,
repository, task type, and patch size without looking at target-model outcomes.
For each:

- pin dataset and image digests;
- confirm tests/gold are hidden from the agent;
- run null/base, gold, and regression checks three times;
- record cold/warm setup and verifier time;
- run one representative model at `c=1`, then a matched `c=2` subset;
- inspect every apparent model failure that might instead be a missing contract
  or environment defect.

This bake-off is an infrastructure/validity study, not a new leaderboard.
Choose one source benchmark intact when external comparability matters. If
Cospa combines sources, name the result `cospa_repo`, publish the manifest and
weights, and do not imply equivalence to any source leaderboard.

### 4. Add feature and freshness campaigns only after the repo panel is stable

- Run FeatureBench Lite with the winning one or two scaffolds.
- Freeze a post-cutoff SWE-bench-Live MultiLang slice only when freshness is a
  deployment question.
- Continue Terminal-Bench and SWE Atlas as separate terminal/investigation
  signals rather than averaging them into one coding score.

## Reporting requirements

Every reported campaign must include:

- exact task manifest and source/image revisions;
- model checkpoint, provider endpoint, serving engine/configuration, GPU type,
  quantization, sampling, reasoning effort, context/output limits, and
  concurrency;
- adapter/scaffold version and enabled tools/extensions/skills;
- capability and safety budgets;
- resolved, incorrect, budget-exhausted, adapter/transport failed, setup failed,
  and verifier failed counts;
- uncached input, cache read/write, output, and reasoning tokens where exposed;
- provider/queue, model, tool, verifier, and total wall time;
- tool names/types/counts/errors, files inspected/edited, build/test calls, and
  final verification behavior;
- Wilson intervals for standalone proportions and paired task outcomes/tests
  for adapter comparisons;
- task-, language-, concept-, repository-, and task-type-weighted cuts where
  applicable;
- all independent trials and outcome flips. Never report best-of-`k` as
  Pass@1.

Results under different protocols, visible artifacts, retries, network access,
or task revisions remain separate even when they share a benchmark family
name.

## Primary references

### Cospa contract source

- [Aider Polyglot design and 225-task selection](https://aider.chat/2024/12/21/polyglot.html)
- [Aider benchmark harness and retry-aware reporting](https://github.com/Aider-AI/aider/tree/main/benchmark)
- [Aider Polyglot source corpus](https://github.com/Aider-AI/polyglot-benchmark)

### Repository and feature evaluations

- [Multi-SWE-bench paper](https://arxiv.org/abs/2504.02605), [harness](https://github.com/multi-swe-bench/multi-swe-bench), and [Flash dataset](https://huggingface.co/datasets/ByteDance-Seed/Multi-SWE-bench-flash)
- [SWE-bench Multilingual methodology](https://www.swebench.com/multilingual.html) and [SWE-bench harness](https://github.com/SWE-bench/SWE-bench)
- [SWE-PolyBench paper](https://arxiv.org/abs/2504.08703), [harness](https://github.com/amazon-science/SWE-PolyBench), and [dataset](https://huggingface.co/datasets/AmazonScience/SWE-PolyBench)
- [FeatureBench paper](https://arxiv.org/abs/2602.10975), [harness](https://github.com/LiberCoders/FeatureBench), and [inference CLI budgets](https://github.com/LiberCoders/FeatureBench/blob/main/docs/infer_cli_arg.md)
- [SWE-bench-Live](https://github.com/microsoft/SWE-bench-Live), [MultiLang dataset](https://huggingface.co/datasets/SWE-bench-Live/MultiLang), and [RepoLaunch paper](https://arxiv.org/abs/2603.05026)
- [SWE-rebench paper](https://arxiv.org/abs/2505.20411) and [public dataset](https://huggingface.co/datasets/nebius/SWE-rebench)
- [SWE-bench Pro paper/overview](https://labs.scale.com/papers/swe_bench_pro) and [public harness](https://github.com/scaleapi/SWE-bench_Pro-os)

### Terminal, code-generation, and existing portfolio references

- [Terminal-Bench 2.0 paper](https://arxiv.org/abs/2601.11868) and [dataset/harness](https://github.com/harbor-framework/terminal-bench-2)
- [SWE Atlas paper](https://arxiv.org/abs/2605.08366) and [harness](https://github.com/scaleapi/SWE-Atlas)
- [BigCodeBench paper](https://arxiv.org/abs/2406.15877) and [runtime documentation](https://github.com/bigcode-project/bigcodebench)
- [LiveCodeBench paper](https://arxiv.org/abs/2403.07974) and [versioned harness](https://github.com/LiveCodeBench/LiveCodeBench)
- [APEX-SWE](https://github.com/Mercor-Intelligence/apex-swe)
- [DeepSWE](https://deepswe.datacurve.ai/)
- [FreshBrew](https://github.com/mrcabbage972/freshbrew)
- [RACE-bench](https://arxiv.org/abs/2603.26337)
- [SWE-Cycle](https://github.com/tubehao/SWE-Cycle)
- [SWE-Explore](https://github.com/Qiushao-E/SWE-Explore-Bench)
- [SWT-Bench Verified](https://swtbench.com/)
