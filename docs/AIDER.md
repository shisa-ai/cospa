# Aider Polyglot Protocol and Score Interpretation

> **Decision:** cospa's current Aider Polyglot suite is a **full coding-agent,
> visible-public-tests protocol**. That is realistic for repository work, but it
> is not the protocol used by Aider's leaderboard, and the visible tests are
> also effectively the entire public grading contract. Results must therefore
> be labeled as cospa results, not Aider leaderboard scores. For strong current
> models the suite is a qualification/smoke test, not a primary scaffold
> discriminator.

This note records why the distinction matters, what the July 2026 ThinkingCap
result demonstrated, how tests should be exposed in an agent benchmark, and
what cospa should use next.

## Short answer: should an agent see tests?

**Yes, an agent should normally see the repository's existing tests. It should
not see the evaluator's entire grading oracle.**

In ordinary software development, a coding agent can:

- inspect existing tests to learn conventions and intended behavior;
- run focused tests while debugging;
- add or improve tests for the behavior it changes; and
- use compiler, linter, and test failures as feedback.

Those activities are central to the scaffold behavior cospa wants to measure.
Removing every test and every execution tool would turn the task into a
specification-to-code benchmark rather than a realistic repository-agent
benchmark.

The realistic design has two test layers:

1. **Visible development tests** already present in the repository. The agent
   may inspect and run these and may add its own tests.
2. **Evaluator holdout tests** that are never mounted into the agent phase.
   They are applied or run only after the agent exits, in an isolated verifier.

The agent's own tests are useful evidence of engineering behavior, but they
must not determine the headline pass/fail verdict. A model can write incomplete
or self-confirming tests. The benchmark author or a trusted test generator must
own the independent evaluator oracle.

## Three different protocols that must not be conflated

### 1. Official Aider Polyglot leaderboard protocol

Aider's upstream benchmark is a constrained code-editing evaluation:

- only solution files declared by Exercism metadata are supplied to Aider;
- test, example, documentation metadata, and selected build files are ignored;
- the model has no general shell or repository-inspection tool loop;
- the harness runs tests outside the model interaction;
- after a failure, the model receives cleaned test output; and
- the default and published score use at most two attempts (`pass_rate_2`).

This measures whether a model can understand the written assignment, produce a
well-formed edit, and repair it once from test output. It does **not** measure a
full autonomous agent exploring and testing a repository.

### 2. Current cospa Aider Polyglot protocol

Cospa deliberately runs the same tasks as full coding-agent jobs:

- the workdir includes starter source, repository tests, and build metadata;
- `.meta/` examples and `.approaches/` solution guides are excluded;
- the prompt explicitly tells the agent to use the provided tests/build files;
- the adapter has normal file, search, edit, and shell tools;
- one agent run may make many model/tool turns within its time budget;
- public network is unavailable except for the selected model endpoint; and
- final grading uses a pre-agent canonical task snapshot overlaid with only the
  solution files declared by `.meta/config.json`.

The canonical verifier prevents an agent from earning a pass by deleting or
weakening tests, editing package scripts, or changing test selection. It does
**not** make those tests hidden: the agent saw their original contents during
its work.

This is a valid **visible-test agent benchmark**. It is not a reproduction of
the Aider leaderboard.

### 3. Recommended primary agent protocol

For scaffold comparison, cospa should ultimately use repository tasks with:

- visible pre-existing repository tests;
- permission for the agent to add its own tests;
- a hidden PR test patch or independent holdout suite;
- a verifier mounted only after all solver processes are dead;
- a clean base commit and immutable environment;
- tasks newer than the evaluated model's documented training cutoff where
  possible; and
- enough task and repository diversity to avoid memorization of a small fixed
  set dominating the result.

That protocol measures realistic test-driven agent behavior while retaining an
independent correctness check.

## Why the current cospa task contract is too easy at the top

Visible tests are not inherently a flaw. The problem is that Aider Polyglot's
visible public tests are nearly the complete grading contract for small,
standalone exercises.

That creates several ceiling pressures:

- tests can provide details that the natural-language assignment omits;
- the agent can iterate until the same tests used for final scoring pass;
- each task has a small search surface and little repository navigation;
- the 225 task directories have been public since December 2024;
- the underlying Exercism problems, tests, and solution patterns were already
  public; and
- current models may have encountered the tasks or close variants during
  pretraining, post-training, benchmark tuning, or trajectory training.

A clean sandbox and canonical verifier establish that the saved implementation
passes the intended tests. They cannot establish that the model had never seen
the public problem before.

## ThinkingCap saturation evidence

The clean canonical ThinkingCap run
`local-vllm-thinkingcap-canonical-full-20260719` produced:

| Adapter | Passed | Rate |
| --- | ---: | ---: |
| `pi_vanilla` | 223/225 | 99.1% |
| `pi_devstack` | 223/225 | 99.1% |
| `pi_devstack_superpowers` | 223/225 | 99.1% |
| `little_coder` | 222/225 | 98.7% |
| `little_coder_superpowers` | 222/225 | 98.7% |

`go/counter` is a special test-writing exercise rather than an ordinary
implementation task. Excluding it, the first three arms passed 223/224
ordinary tasks (99.6%). The one-task spread across all five adapters is not
useful evidence of scaffold superiority.

A trace audit of the 225 `pi_vanilla` trials found:

- 225/225 explicitly read at least one test file;
- 153/225 invoked an identifiable test command during the agent phase;
- median 8 model responses per task;
- median 9 tool calls per task; and
- 18.4 million accumulated tokens across the cell (mean about 82,000 per
  task, including repeated conversation context).

This is expected full-agent behavior, but it explains why the 99.1% figure
cannot be placed beside Aider's two-attempt scores.

The near-identical result across five scaffolds is the operational definition
of saturation for cospa's purpose: the suite still checks basic multilingual
competence, but it no longer measures the scaffold differences the matrix was
created to study.

## Comparison with the published Aider leaderboard

As checked in July 2026:

- the public dataset repository's current commit is
  `7e0611e77b54e2dea774cdc0aa00cf9f7ed6144f`, dated 2024-12-22;
- the latest new published result is from October 2025;
- the leading published score is GPT-5 high at 198/225 (88.0%), dated
  2025-08-23; and
- those percentages are the upstream harness's second-attempt score.

The original December 2024 benchmark article said Polyglot was constructed
because the prior 133-task Python benchmark had saturated above 80%. By August
2025, Polyglot itself had reached 88% under the stricter upstream protocol.
That indicates declining headroom, but cospa's 99% result alone does not prove
that a current model would score 99% under Aider's protocol.

An apples-to-apples claim requires a separate run through the upstream Aider
harness with its solution-files-only and two-attempt constraints.

## Result-labeling policy

Use an explicit protocol label in reports. A suitable name is:

> **cospa Aider Polyglot — full agent, visible public tests, canonical
> solution-only grading**

Do not describe that number as:

- an "Aider leaderboard score";
- directly better or worse than a number at `aider.chat`;
- independent evidence that the model had never seen the task; or
- a strong scaffold ranking when arms differ by only one or two tasks near the
  ceiling.

Every retained result should continue to record:

- dataset repository, commit, tree, and clean status;
- isolation profile;
- canonical-verifier policy;
- adapter exit policy;
- model, sampling/thinking setting, and endpoint identity; and
- token, time, and cost evidence.

Historical results from before the isolation, clean-dataset, canonical-overlay,
and full-test-activation cutovers must remain separate from protected scores.

## What should write the tests?

### Existing tests

The benchmark repository should provide visible pre-existing tests, just as a
real repository does. They are part of the development environment, not the
whole evaluator.

### Agent-authored tests

The agent should be allowed to add tests. Whether it does so, whether those
tests fail before the fix, and whether they cover the reported bug are valuable
secondary metrics. They should not replace independent grading.

A dedicated test-writing workflow can score the quality of model-authored tests
against mutation testing or a hidden rubric. That is a different capability
from issue resolution and should remain a separately named benchmark arm.

### Evaluator tests

The evaluator must own a test patch or oracle unavailable during solving. It
may come from:

- the resolving pull request's test patch;
- manually authored holdout cases;
- property/metamorphic tests generated outside the solver sandbox; or
- fresh private tasks released only after evaluation.

A static "hidden" file committed to this public repository is hidden only from
the runtime filesystem, not from future model training. Temporal freshness and
rolling task replacement are therefore as important as sandbox secrecy.

## Better multilingual agent benchmarks

No single public benchmark perfectly satisfies all of these at once:

1. broadly recognized;
2. genuinely agentic and repository-level;
3. multilingual;
4. quick to run; and
5. resistant to training exposure.

The best current compromise for cospa is **SWE-bench-Live/MultiLang**, run as a
small pinned, stratified slice.

### Recommended: SWE-bench-Live/MultiLang

As of May 2026, the public corpus contains 743 real issue-resolution tasks from
381 repositories across eight language splits:

| Split | Tasks |
| --- | ---: |
| C | 37 |
| C++ | 74 |
| C# | 87 |
| Go | 138 |
| Java | 109 |
| JavaScript | 93 |
| Rust | 94 |
| TypeScript | 111 |

It is a Microsoft/SWE-bench project with a public leaderboard and prebuilt
RepoLaunch Docker environments. Tasks include a pre-solution repository and
visible existing tests; final evaluation applies the resolving PR's test patch
and checks fail-to-pass plus pass-to-pass tests. Task dates currently range
from May 2025 through April 2026, materially fresher and more diverse than the
fixed Exercism corpus.

It is not yet as widely used as the original SWE-bench family, and a full
743-task run is not cheap. Cospa should therefore define two immutable slices:

- **canary:** 24 tasks, three per language, for setup and cost qualification;
- **core:** 48 tasks, six per language, for matched adapter comparisons.

Selection should be made without using the candidate models' success results:

- newest eligible task dates first, subject to a declared cutoff policy;
- one task per repository where possible;
- balanced by language and coarse gold-patch size;
- exclude tasks whose clean baseline is flaky across repeated verifier runs;
- exclude tasks requiring solver-phase public network;
- pin dataset revision, instance IDs, Docker image digests, and test commands;
- use the same task list, timeout, and sampling settings for every adapter; and
- pre-pull images before measuring wall time.

Cospa now implements that canary as
`swe_bench_live_multilang_canary24`. The immutable selection has 24 distinct
repositories, three patch-size buckets per language, pinned complete dataset
rows and image digests, and a 6 GiB compressed-image cap per task. The protected
Harbor grader has repeated C gold/baseline evidence, but the other seven
language strata and a model trial remain unqualified. Exact pins, isolation,
scoring differences, resource totals, and launch commands are in
[`docs/SWE-BENCH-LIVE.md`](SWE-BENCH-LIVE.md).

Twenty-four tasks are only a canary and have wide statistical uncertainty. The
48-task core is still a pilot; expand it if adapter differences are small.

### Widely recognized fallback: SWE-bench Multilingual

SWE-bench Multilingual is the safest conventional anchor:

- 300 manually curated tasks;
- 42 repositories;
- nine languages (C, C++, Go, Java, JavaScript, TypeScript, PHP, Ruby, Rust);
- official SWE-bench evaluation compatibility; and
- hidden PR test patches with fail-to-pass/pass-to-pass scoring.

It was explicitly designed to be small enough to run more easily than larger
multilingual suites and is much more established than SWE-bench-Live. Its
weakness for cospa is freshness: issue dates extend through March 2025, the
entire set is public, and later training/trajectory datasets can include it.
Use it as a reproducible external anchor, not as proof of decontaminated model
capability.

### Other candidates

| Benchmark | Strength | Why it is not the first choice |
| --- | --- | --- |
| Multi-SWE-bench flash | 300 real issue tasks across seven languages; designed for rapid rollouts | Public since 2025; related trajectories and RL data are published; less exposure-resistant |
| Multi-SWE-bench mini | Balanced 400-task, eight-language subset | Larger than flash and still a fixed public 2025 set |
| SWE-rebench V2 | 32,079 tasks across 20 languages, collected in 2026; large rolling source | Very new, automated curation, and not yet a small established leaderboard split |
| SWE-rebench monthly leaderboard | Rolling tasks, prebuilt images, explicit contamination windows | Current established leaderboard lineage is not the clearest balanced multilingual slice; per-task token/runtime cost is high |
| CrossCodeEval / RepoBench-style suites | Fast and multilingual | Code completion rather than autonomous issue resolution; weak scaffold/tool-loop signal |
| Terminal-Bench | Strong agent/tool-use signal | Not specifically a multilingual coding benchmark and often much slower; cospa's current protection audit is still partial |

## Recommended cospa suite roles

Use different suites for different claims rather than forcing one benchmark to
do everything:

| Role | Suite | Claim |
| --- | --- | --- |
| Cheap qualification | Current Aider Polyglot | Can this model/scaffold reliably use tools and implement small tasks in six languages? |
| Conventional external anchor | SWE-bench Multilingual | How does the agent resolve established multilingual repository issues under a standard protocol? |
| Primary freshness/scaffold pilot | 48-task SWE-bench-Live/MultiLang core | Do scaffold differences survive on newer repositories with evaluator-only PR tests? |
| Deep agent robustness | Terminal-Bench / later protected suite | Can the scaffold recover across long, heterogeneous terminal tasks? |

Do not launch a full matrix immediately. Finish the canary qualification in
[`docs/SWE-BENCH-LIVE.md`](SWE-BENCH-LIVE.md): gold/baseline checks across all
eight languages, then one protected adapter run with image, wall-time, token,
network, trace, patch, verifier-determinism, and failure-mode review. Only then
freeze the 48-task core and run matched adapters.

## Sources

Primary sources checked in July 2026:

- [Aider LLM leaderboard](https://aider.chat/docs/leaderboards/)
- [Aider benchmark harness README](https://github.com/Aider-AI/aider/blob/main/benchmark/README.md)
- [Aider benchmark implementation](https://github.com/Aider-AI/aider/blob/main/benchmark/benchmark.py)
- [Aider Polyglot design article](https://aider.chat/2024/12/21/polyglot.html)
- [Aider Polyglot dataset](https://github.com/Aider-AI/polyglot-benchmark)
- [Aider Polyglot result data](https://github.com/Aider-AI/aider/blob/main/aider/website/_data/polyglot_leaderboard.yml)
- [ThinkingCap Qwen3.6 27B model card](https://huggingface.co/bottlecapai/ThinkingCap-Qwen3.6-27B)
- [SWE-bench Multilingual](https://www.swebench.com/multilingual.html)
- [SWE-bench-Live](https://github.com/microsoft/SWE-bench-Live)
- [SWE-bench-Live/MultiLang dataset](https://huggingface.co/datasets/SWE-bench-Live/MultiLang)
- [Multi-SWE-bench](https://github.com/multi-swe-bench/multi-swe-bench)
- [SWE-rebench leaderboard dataset](https://huggingface.co/datasets/nebius/SWE-rebench-leaderboard)
- [SWE-rebench V2](https://huggingface.co/datasets/nebius/SWE-rebench-V2)
