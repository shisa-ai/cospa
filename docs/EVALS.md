# Coding-agent evaluation review

_Last reviewed: 2026-07-15_

## Decision

The next cospa suite should **not** be another short-answer coding or general
reasoning benchmark. Aider Polyglot already measures small, test-driven code
changes, and current strong configurations are near its ceiling. The missing
signal is whether an agent can investigate a real system, use tools, distinguish
assumptions from observed state, and complete production-shaped engineering
work.

Use a portfolio with three distinct roles instead of asking one suite to do
everything:

| Role | Suite | Run policy |
| --- | --- | --- |
| Fast multilingual regression | Aider Polyglot | Small fixed slices during development; all 225 only for shortlisted configurations or releases |
| External leaderboard anchor | **Terminal-Bench Core 0.1.1 now**; Terminal-Bench 2.1 at milestones | Pin the official task revision and run sparingly, rather than sweeping every model x adapter cell |
| New production-engineering signal | **APEX-SWE public dev set** | Cost-gated 10-task pilot, then a fixed 20-task internal screen if it qualifies |

The immediate leaderboard fix is to pin the existing Terminal-Bench integration
to **`terminal-bench-core==0.1.1`**. That is the 80-task dataset behind the
official Terminal-Bench 1.0 leaderboard; cospa's current 241-task `@head` path
is not comparable to that leaderboard or to Terminal-Bench 2.1. Terminal-Bench
2.1 is the more current 89-task milestone anchor, but it is not a cheap test:
the official submission protocol uses five attempts per task, or 445
trajectories. Benchmark-name overlap alone is not direct comparability; dataset
revision, attempts, resources, model settings, and scaffold protocol must also
match.

The best _new_ content fit remains **APEX-SWE's 50-task public dev set**,
especially its mix of cross-service integration and observability/debugging.
Its main risk is cost: the authors publish a one-hour task timeout and episode
counts, but not input/output-token or wall-time distributions. Therefore:

1. Implement a fixed **10-task APEX-SWE pilot**: five Integration tasks spanning
   different services and five Observability tasks spanning Go, Python,
   TypeScript, Java, and C++.
2. Measure one model, one adapter, `k=1`, with the same manifest telemetry used
   by `./view`.
3. If the first pass clears the cost and infrastructure gates, rerun all ten
   once with the same model/adapter. This yields `k=2` over the complete pilot,
   not `k=3` on three hand-picked tasks.
4. Promote to a fixed **20-task screening suite** only if both passes qualify.
   Run the full public 50 only for milestones.
5. If APEX-SWE exceeds either cost gate or has recurrent service-startup or
   verifier failures, use a stratified **FreshBrew JDK-21** subset. Its
   deterministic Maven gates and much shorter published successful trajectories
   make it the safer paired-adapter fallback, although it covers only Java
   modernization.

**SWE-bench Verified Mini** is a legitimate optional second external anchor,
not merely a benchmark to dismiss. It is a fixed random 50-task subset with a
published HAL leaderboard. However, that leaderboard is paused, Python-only,
and highly scaffold-dependent; published run costs range from $4.72 to
$1,599.90 while its token and wall-time distributions remain unknown. Add it
only when SWE-bench compatibility is worth another suite integration; pinned
Terminal-Bench Core already fills the immediate anchor role.

Use **DeepSWE** as a milestone/frontier suite, not the routine short suite. It
is excellent and current, but its public leaderboard shows 46K--276K output
tokens and 61--268 steps per task for recent systems. That is the opposite of a
cheap screening run.

This recommendation is about benchmark _shape_. A custom 10- or 20-task APEX
slice has no external leaderboard and cannot supply one. The pilot measures
cost and integration; the 20-task result is directional. External sanity comes
from the pinned Terminal-Bench runs, while close model-ranking claims graduate
to full suites.

## Evidence labels

Token and runtime figures are unusually easy to misread in agent benchmarks.
This document uses these labels:

- **Measured here**: calculated from durable cospa results or the vendored
  dataset currently checked out.
- **Published**: stated by the benchmark or model authors.
- **Estimate**: an explicit extrapolation, never presented as observed data.
- **Unknown**: the source does not publish the quantity. A model's context
  limit or per-task cap is not its actual usage.

"Input tokens" means cumulative API input over every agent turn unless a source
explicitly says it means only the initial task prompt. Re-sending a growing
trajectory can make cumulative input much larger than the repository or prompt.

## Current cospa baseline

### Aider Polyglot

Aider Polyglot has 225 Exercism tasks in C++, Go, Java, JavaScript, Python, and
Rust. It is deterministic and useful for basic edit/test-loop regressions, but
it is no longer a strong frontier discriminator.

`./view json --pretty` on 2026-07-15 shows the following complete Qwen 3.6-27B
runs. Runtime is summed agent wall time, not elapsed matrix makespan.

| Provider / effort | Adapter | Score | 225-task wall | Mean/task | Non-cached input/task | Output/task |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| aiand, default | `little_coder` | 92.4% | 9.95 h | 2.65 min | 207K | 5.27K |
| aiand, default | `pi_devstack` | 93.8% | 14.39 h | 3.84 min | 260K | 4.57K |
| aiand, default | `pi_devstack_superpowers` | 94.2% | 13.81 h | 3.68 min | 231K | 4.46K |
| local, high | `little_coder_superpowers` | 93.8% | 4.63 h | 1.23 min | 204K | 5.44K |
| local, high | `pi_devstack` | 94.2% | 6.57 h | 1.75 min | 267K | 5.44K |
| local, high | `pi_devstack_superpowers` | 94.2% | 6.47 h | 1.72 min | 249K | 5.42K |

Each complete Qwen row in the table consumes **46.0M--60.0M prompt/input
tokens and 1.00M--1.22M output tokens** over 225 tasks. At that rate, a
four-adapter full-suite sweep is an estimated 188M--245M total tokens before
adding another model or `k>1`. Across all 23 complete Aider rows currently
visible, summed wall time ranges from 2.76 to 14.39 hours and the viewer's
reported non-cached prompt/input field ranges from 8K to 267K per task. Cached
and reasoning usage is recorded separately where providers expose it, so low
values are not automatically low total context traffic.

That variation is the central cost lesson: **benchmark name and task count do
not determine runtime or token usage; model, provider telemetry, and scaffold
do**. Aider is cheap per task, but a naive Cartesian matrix is not cheap.

The ceiling is real. Qwen configurations above cluster at 92--95%; complete
GPT-5.5 runs score 96--99%. Aider should remain the cheap correctness and
multi-language regression suite, but adding another function-level benchmark
would not fill the missing capability gap.

### Terminal-Bench

There are no complete Terminal-Bench rows in the current `./view` data, so
actual cospa token and runtime use is **unknown**.

There is also a versioning distinction that must be made explicit before a
large run:

- the stable vendored `terminal-bench-core` registry entry `0.1.1` lists 80
  tasks;
- cospa currently resolves `terminal-bench-core@head` by enumerating all 241
  directories in the vendored `original-tasks/` checkout at commit
  `1a6ffa9674b571da0ed040c470cb40c4d85f9b9b`;
- the newer official Terminal-Bench 2.1 is a separate 89-task benchmark.

**Measured here**, the 241 head tasks have a median configured agent timeout of
15 minutes. Their timeout ceilings sum to 125.9 serial hours; this is a ceiling,
not an expected runtime. **Published**, the official Core 0.1.1 leaderboard has
62 entries and currently tops out at 64.5%; the Terminal-Bench 2.1 leaderboard
has 17 entries and currently tops out at 83.8%. Core is therefore both the
cheaper immediate compatibility repair and less saturated, while 2.1 gives the
more current model-card comparison at milestone cost. Before another TB run,
pin the intended dataset version rather than treating "Core", head, and 2.1 as
interchangeable.

## What recent coding-model releases actually report

This is useful as a popularity map, not as proof that every benchmark is good
for cospa. Scores across different native scaffolds, task patches, reasoning
budgets, and context limits are not directly comparable.

| Release/source | Coding and agent evaluations named in accessible source text or HF evaluation metadata |
| --- | --- |
| [Tencent Hy3](https://huggingface.co/tencent/Hy3) | SWE-bench Verified/Pro, DeepSWE, SkillsBench, APEX-Agents, WildClawBench; also reports small variance across CodeBuddy/Cline/Kilo scaffolds |
| [MiniMax M3](https://huggingface.co/MiniMaxAI/MiniMax-M3) | SWE-bench Verified/Pro, SkillsBench, APEX-Agents, Claw-Eval in HF metadata; the launch page also presents a coding/agent chart but does not expose its protocol as text |
| [Ornith-1.0](https://deep-reinforce.com/ornith_1_0.html) | Terminal-Bench 2.1, SWE-bench Verified/Pro/Multilingual, NL2Repo, Claw-Eval, and all three SWE Atlas workflows |
| [MiMo-V2.5](https://huggingface.co/XiaomiMiMo/MiMo-V2.5) | Publishes a Coding & Agent benchmark chart; the card's accessible text does not enumerate the chart values, so this review does not reverse-engineer them |
| [DeepSeek V4](https://huggingface.co/deepseek-ai/DeepSeek-V4-Flash) | LiveCodeBench, Terminal-Bench 2.0, SWE Verified/Pro/Multilingual, MCPAtlas, Toolathlon |
| [Step 3.7 Flash](https://static.stepfun.com/blog/step-3.7-flash/) | SWE Verified/Pro/Multilingual, Terminal-Bench 2.1, ClawEval, Toolathlon; also reports a private multi-scaffold SWE set |
| [Cohere North Mini Code](https://cohere.com/blog/north-mini-code) | SWE Verified/Pro, Terminal-Bench v2 and Terminal-Bench Hard, using SWE-Agent/ReAct/Terminus-2 harnesses |
| [Poolside Laguna M.1/XS.2](https://poolside.ai/blog/introducing-laguna-xs2-m1) | SWE Verified/Pro/Multilingual and Terminal-Bench 2.0, run through Harbor |
| [Gemma 4](https://deepmind.google/models/gemma/gemma-4/) | LiveCodeBench and tau2 tool use in first-party text; SWE/TB numbers seen elsewhere are third-party reproductions |
| [Qwen3.6-35B-A3B](https://huggingface.co/Qwen/Qwen3.6-35B-A3B) | SWE Verified/Pro/Multilingual, Terminal-Bench 2.0, Claw-Eval, SkillsBench, NL2Repo, MCPMark/MCP-Atlas |
| [GLM-5.2](https://build.nvidia.com/z-ai/glm-5.2/modelcard) | SWE-bench Pro, NL2Repo, Terminal-Bench 2.1, MCP-Atlas, Tool-Decathlon |

The consensus suite remains SWE-bench + Terminal-Bench. The newer
_differentiating_ signals are DeepSWE, SWE Atlas, NL2Repo, APEX-SWE, and
real-environment/skills evaluations. That is where this review concentrates.

## Candidate comparison

### Best fit for the missing signal

| Benchmark | Tasks and coverage | Agent work and grading | Published usage / difficulty | Cospa fit |
| --- | --- | --- | --- | --- |
| **[APEX-SWE](https://www.mercor.com/apex/apex-swe-leaderboard/)** | 200 hidden cases, 50 public dev cases; split evenly between Integration and Observability. Observability covers Go, Python, TypeScript, Java, and C++; Integration spans PostgreSQL, LocalStack/AWS, Plane, CRM, e-commerce, mail, chat, and ticketing services. | Persistent shell, file tools, and MCP services. Integration builds end-to-end systems; Observability searches logs/chat/issues and patches real repositories. Program tests determine leaderboard pass/fail; rubrics provide secondary functional, robustness, and style scores. | One-hour task timeout. Published early systems average about 20--30 episodes on Integration, with a 76.8-episode GPT outlier. Actual tokens and wall-time distribution: **unknown**. Public-set scores were 10--40% in the paper and newer hidden-set leaders remain well below saturation. | **Best content match.** Exactly the production-shaped tool use missing from Aider. Public 50 is compact, but multi-service setup and unknown cost require a pilot. It is a public dev set, not a contamination-resistant held-out result; the paper shows rank shifts and score gaps up to 18 points versus the hidden set. |
| **[FreshBrew](https://github.com/mrcabbage972/freshbrew)** | 228 real Maven/Java repositories; migrate JDK 8 projects to JDK 17 or 21. | Agent reads/writes files, repeatedly runs Maven verification, and may search documentation. Success requires compile + all original tests + no more than a 5-point test-coverage drop, limiting test/code deletion reward hacks. | Up to 100 steps. On successful migrations, published median steps were roughly 5 (DeepSeek-V3), 13 (GPT-4.1), and 17 (Gemini 2.5 Flash). Tokens and wall time: **unknown**. The best JDK-17 result was 52.3%; JDK 21 was harder. | **Best cost-shaped fallback.** Real repo/build loops and deterministic grading, likely shorter trajectories, but only Java/Maven and one task family. Use JDK 21 and stratify by project complexity. |
| **[SWE Atlas](https://github.com/scaleapi/SWE-Atlas)** | 284 tasks: 124 Codebase Q&A, 90 Test Writing, 70 Refactoring across 18 repos. Q&A/TW use Go, Python, C, TypeScript; Refactoring adds C++ and JavaScript. | Runtime codebase investigation, mutation-tested test authoring, and behavior-preserving multi-file refactors. Combines deterministic checks with expert rubrics graded by an LLM judge. | Six-hour sandbox limit. Frontier scores remain about 40--55%. For Q&A + Test Writing, the paper reports roughly $0.35--$1.90 per task for selected frontier systems; input/output tokens and wall time are **unknown**. Refactors span 35--2,073 gold lines. | **Excellent engineering breadth, poor default cost fit.** Judge dependency and long trajectories make it a milestone suite or a carefully fixed 30-task sample, not the first cheap addition. |
| **[DeepSWE](https://deepswe.datacurve.ai/)** | 113 original tasks over 91 repositories in TypeScript, Go, Python, JavaScript, and Rust. | Long-horizon repository changes in isolated Harbor/Pier environments with implementation-agnostic program verifiers. | Current leaderboard rows report 46K--276K output tokens, 61--268 steps, and about $2.36--$26.40 per task. Scores span 12--73%, so it separates current systems well. Input tokens and wall time are **unknown**. | **Best milestone frontier benchmark, not cheap.** Its own CLI supports a deterministic 10-task sample seed, useful after integration, but tiny samples are noisy. |

### Established issue-resolution options

| Benchmark | Tasks / languages | Signal and saturation | Token/runtime evidence | Verdict |
| --- | --- | --- | --- | --- |
| [SWE-bench Verified](https://www.swebench.com/) | 500 human-validated tasks, Python, 12 repositories | Real GitHub issue repair, but current systems commonly score 70--88%; OpenAI and Anthropic now discuss contamination/memorization screening. | SWE-Effi shows how scaffold-dependent cost is: on its 50-task sample, published averages ranged from 34K to 8.1M input and 1.7K to 41K output tokens per task. | Do not add as the primary new signal. Python-only and increasingly saturated. |
| [SWE-bench Verified Mini](https://hal.cs.princeton.edu/swebench_verified_mini) | Fixed random 50-task subset; HAL lists 33 evaluations across two scaffolds and 18 models | Inherits Verified's Python-only distribution and contamination risk; the paused leaderboard currently tops out at 72%. | HAL publishes traces and $4.72--$1,599.90 total run costs, demonstrating extreme scaffold/model variance, but not a stable token or wall-time summary. | **Optional second leaderboard anchor.** Useful when SWE compatibility matters, but redundant with pinned TB Core for the immediate portfolio and not proven cheap on cospa. |
| [SWE-bench Pro](https://scaleapi.github.io/SWE-bench_Pro-os/) | 1,865 total; 731 public from 11 repos; Go, Python, JavaScript, TypeScript | Larger, multi-file, enterprise-shaped issue repair. Public leaderboard performance is lower than Verified, though current release claims have risen to roughly 50--62%. | Public trajectory data exists, but no current benchmark-wide input/output or wall-time distribution is published. Tasks may represent hours or days of human work. | High signal but far too large for a routine matrix. A small subset would compete with APEX-SWE while covering less novel work. |
| [SWE-bench Multilingual](https://www.swebench.com/multilingual.html) | 300 tasks, 42 repos, C, C++, Go, Java, JS, TS, PHP, Ruby, Rust | Better language breadth; median gold patch is only 10 lines. Recent model cards report roughly 52--79%, so it is less saturated than Verified but still conventional issue repair. | Original baseline used a $2.50/task cap. Current input/output and runtime distributions are **unknown**. | Good release regression suite, but 300 tasks and small patches do not solve the short, production-engineering gap. |
| [SWE-Effi](https://arxiv.org/abs/2509.09853) | A metrics framework demonstrated on a stratified 50-task Verified sample, not a new task set | Adds effectiveness under token, cost, CPU, and inference-time budgets and exposes expensive failures. | Publishes per-scaffold/model token and time data. | Adopt its _metrics_ in cospa; do not count it as an additional eval. |

### Specialized and adjacent options

| Benchmark | Scope | Published scale / usage | Why it is not the default next suite |
| --- | --- | --- | --- |
| [NL2Repo-Bench](https://github.com/multimodal-art-projection/NL2RepoBench) | Build complete Python libraries from an empty workspace and a requirements document; hidden upstream tests. | 104 tasks; initial specification averages 18.8K tokens; generated code is reported around 10K--50K tokens; strong agents average about 180 interaction turns and only a few repos fully pass. | Very high long-horizon signal, but clearly slower than the requested screen and Python-only. |
| [LiveSQLBench CLI](https://livesqlbench.ai/) | Explore real PostgreSQL/SQLite databases and produce/execute SQL for BI and CRUD tasks. | 270 Base-Lite, 600 Base-Full, 480 Large. Large prompts average 84K tokens; model-base SQL averages 360 tokens. A baseline agent is capped at 20 steps. Current CLI-agent token/runtime data are **unknown**. | Potentially cheap, contamination-resistant tool-use signal, but mostly database querying rather than general code engineering. Worth a later data-agent suite. |
| [SkillsBench](https://www.skillsbench.ai/) | Paired evaluation with/without procedural skill packages in containerized professional tasks. | 87 tasks across eight domains, only 16 software-engineering tasks; site plots range from roughly 4 to 60+ agent minutes/task depending on configuration. Tokens are **unknown**. | Designed to estimate skill lift, not raw coding capability. Valuable if cospa later evaluates its own skills as an axis. |
| [WildClawBench](https://internlm.github.io/WildClawBench/) | Real shell, browser, files, email, calendar, multimodal and coding workflows. | 60 tasks in six categories. Published harness comparisons average 5.8--10.3 min/task, or roughly 5.8--10.3 serial hours for all 60. Tokens are **unknown**. | Realistic and moderately sized, but broad personal-agent capability rather than a clean coding suite; external-service drift is an added confound. |
| [Claw-Eval](https://github.com/claw-eval/claw-eval) | General, multimodal, and multi-turn autonomous-agent work with completion/safety/robustness rubrics. | 300 tasks and a strict three-trial primary metric (900 trajectories). Uses model judges. | Too broad and too large; not primarily software engineering. |
| [ProgramBench](https://programbench.com/) | Clean-room reimplementation of an executable from docs and black-box queries, with no source or internet. | 200 programs, 248K behavioral tests. Best current full-resolution result is 0.5%; authors report some complete runs costing up to $5K. Tokens/runtime distribution: **unknown**. | Fascinating future frontier, but currently floor-saturated and much too expensive for screening. |
| [KernelBench](https://github.com/ScalingIntelligence/KernelBench) | Generate correct, faster CUDA/DSL kernels for PyTorch programs. | 100 level-1 operators + 100 fusions + 50 model architectures, plus an evolving Hugging Face level. One-shot and multi-turn modes exist; aggregate token/runtime is **unknown**. | Cheap, objective optimization signal, but GPU/hardware-specific and not repository engineering. Could be a separate specialist suite. |
| [FreshBrew](https://arxiv.org/abs/2510.04852) | Project-level Java migration. | See preferred-candidate table. | Strong fallback, but specialization prevents it from being the only new suite. |
| [CyberGym](https://www.cybergym.io/cybergym/) | Reproduce real OSS-Fuzz vulnerabilities with executable PoCs against pre/post-patch code. | 1,507 tasks from 188 projects; up to 100 agent steps in the reported setup. Tokens/runtime are **unknown**. | Excellent security-agent benchmark, but huge and domain-specific. A small security slice could be valuable later. |
| [APEX-Agents](https://www.mercor.com/apex/apex-agents-leaderboard/) | Long-horizon investment banking, consulting, and law work. | 480 tasks in 33 worlds. | Explains its presence on Hy3/M3 cards, but it is not a coding benchmark. APEX-**SWE** is the relevant sibling. |
| LiveCodeBench / BigCodeBench / HumanEval-style sets | Competitive programming or function generation without a persistent software environment. | Usually cheap, one-shot, and easy to score. | They do not exercise repository navigation, build/debug loops, or sustained tool use. Aider already supplies the more relevant version of this signal. |

## Harness-comparison and campaign policy

Do not multiply every model by every adapter by every task and repetition. The
campaign budget is approximately:

```text
tasks x models x adapters x k x mean tokens per trajectory
```

Use one representative model to compare adapters, then compare models with the
winning one or two adapters. Predeclare a campaign-level token ceiling as well
as a per-trajectory timeout. This matters even for Aider: one four-adapter Qwen
sweep can already approach a quarter-billion tokens.

For an adapter A/B block:

- hold the exact model checkpoint, provider/endpoint, server configuration,
  reasoning effort, sampling settings, context/output limits, task revision,
  and verifier resources fixed;
- run identical task IDs, preferably in randomized blocked order so provider or
  service drift does not line up with one adapter;
- report task-level discordant pairs and a paired interval or exact paired test;
  Wilson intervals describe each absolute score but do not measure the paired
  adapter delta;
- separate setup/verifier reproducibility from model stochasticity. A repeated
  service-startup or pristine-verifier failure is benchmark noise; a model that
  passes once and fails once is not by itself proof that the task is flaky;
- do not silently remove tasks merely because their model outcomes flip. Flag
  them, investigate the trajectory, and exclude only under a predeclared
  infrastructure/verifier rule. Outcome-based pruning would bias the screen.

A 20-task paired comparison has more power than two unrelated 20-task scores,
but it still resolves only large adapter effects. Keep the model/provider
fixed, publish the paired task table, and graduate close calls rather than
claiming a precise rank.

## Concrete short-suite design

### Phase A: cost and reliability pilot (`apex_swe_pilot10`)

Freeze ten public APEX-SWE task IDs in a checked-in manifest; do not randomly
sample on every run.

- **Integration (5):** one LocalStack/AWS task and four tasks chosen to cover
  distinct business-service combinations (for example Plane, Medusa, Zammad,
  mail/chat/CRM).
- **Observability (5):** one task each in Go, Python, TypeScript, Java, and C++.
- Preserve upstream prompts, environments, tests, and timeout semantics. A
  "short" suite should reduce task count, not silently make each task easier.
- Run one representative local model with `pi_vanilla`, `k=1` first. Do not
  multiply by models/adapters until infrastructure is known-good.
- If that pass qualifies, repeat all ten with the same model, provider, and
  adapter. Diagnose every disagreement and every non-model failure before
  freezing a screen.

Promotion gates:

| Gate | Requirement |
| --- | --- |
| Runtime | First-pass summed agent wall time <= 2 h for 10 tasks, and total setup + agent + verifier time <= 4 h; report median and p90 too |
| Tokens | Default first-pass ceiling <= 10M normalized total API tokens over 10 tasks and p90 <= 2M/task; count non-overlapping input/cache/output/reasoning fields and report each separately |
| Telemetry | >= 95% of trials have input, output, reasoning/cache, wall-time, and tool-call counts |
| Infrastructure | <= 5% fail before the agent receives a valid task environment, with no task showing the same unexplained startup/verifier failure on both passes |
| Difficulty | Pilot results show nontrivial task/subcheck variation; if binary score is 0% or >= 90%, run one deliberately stronger or smaller bracketing configuration before accepting or rejecting the suite |
| Validity | Program verifier runs on a pristine task artifact; no mock-only success claim |
| Reliability | Complete `k=2` over all ten tasks with the same matched configuration; report outcome flips rather than automatically deleting them |

The 10M gate is a campaign-design default, not a claim about published APEX
usage. At a 1M-token mean, 20 tasks x four adapters x `k=1` is already 80M
tokens; `k=2` doubles it. Tighten the gate if the intended matrix has more
cells. A ten-task score has a worst-case 95% binomial margin around ±31
percentage points. It is a systems/cost pilot, not a leaderboard.

### Phase B: routine screen (`apex_swe_screen20`)

If Phase A passes, freeze 20 public tasks, ten per workflow. Select them using
published task metadata before looking at target-model outcomes, and document
the selection seed/rule. Report:

- binary task pass rate and Wilson interval;
- mean deterministic correctness/subcheck score, when exposed by upstream;
- Integration and Observability separately;
- Observability by language, while clearly noting tiny cell sizes;
- cumulative uncached input, cached input, cache creation, output, reasoning,
  tool calls, and wall time;
- infrastructure failures separately from model failures;
- pass per million total tokens and pass per agent-hour, borrowing SWE-Effi's
  resource-effectiveness perspective.

At 20 binary tasks the worst-case 95% margin is still about ±22 points. This is
adequate for rejecting obvious weak configurations and finding large scaffold
failures, not for declaring a two-point model win. For adapter comparisons,
keep one model/provider fixed and report the paired discordant-task table plus a
paired interval/test. Use the winning one or two adapters for broader model
runs instead of expanding the full Cartesian product. Graduate close calls to
all 50 public tasks.

### Fallback: `freshbrew_jdk21_32`

If APEX-SWE fails the runtime or token gate, exceeds 5% infrastructure
failures, or repeats the same unexplained startup/verifier failure on both
passes:

- choose 32 FreshBrew projects, eight from each quartile of repository
  complexity, before testing target models;
- use the JDK-21 migration target;
- preserve the compile, full-test, and coverage-drop gates;
- track compile-only, test-pass, and full coverage-guard success as diagnostic
  submetrics;
- apply the same four-hour screening target and telemetry requirements.

This fallback gives a clean, deterministic, project-level build/debug loop with
much less environment breadth. Its limitation must remain in the suite name and
reports: it measures Java modernization, not general software engineering.

## What not to add

The intern's MMLU-Pro, GPQA, BBH, GSM8K, MATH, and tool-free HLE suggestions may
be useful model sanity checks, but they miss this project's objective. They do
not require the model to inspect an unfamiliar repository, manipulate files,
run builds/tests, recover from tool errors, or leave a working artifact. Adding
them would improve breadth of academic reasoning measurement while leaving the
agentic-engineering blind spot untouched.

Similarly, do not choose a benchmark only because a model card reports it.
Model cards optimize for industry comparability; cospa needs a complementary,
cost-aware signal that answers a concrete deployment question.

## Implementation requirements for any new suite

1. **Pin task IDs and upstream revision.** Never let a `head` alias silently
   change task count, as the current Terminal-Bench Core path can.
2. **Separate model and infrastructure failure.** Image pull, service startup,
   verifier, and missing-tool errors must not become ordinary zero scores.
3. **Capture actual usage.** Store per-turn provider usage when available;
   aggregate uncached input, cached input, cache creation, output, and reasoning
   independently. Never infer usage from context limits.
4. **Record active and total wall time.** Agent time, environment setup, and
   verifier time answer different capacity questions.
5. **Keep upstream verification intact.** A fixture-only unit test proves the
   adapter shape, not benchmark validity. Run at least one real task end to end
   before marking the suite verified.
6. **Preserve language and workflow strata.** A convenient Python-only slice
   would repeat the existing coverage failure documented in
   `docs/IMPROVEMENT.md`.
7. **Use cost gates.** Abort or quarantine trajectories that exceed a declared
   token/time budget, but report budget exhaustion separately from incorrect
   solutions.
8. **Match harness-comparison blocks.** Hold model, provider, server settings,
   reasoning effort, sampling parameters, task revision, and resources fixed;
   do not let a provider or effort change masquerade as an adapter effect.
9. **Report the right uncertainty.** Show task count and Wilson CI for an
   absolute score; use paired task deltas and paired uncertainty/tests for
   adapter comparisons. Use full suites for close ranking claims.

## Primary sources

- [Artificial Analysis Coding Agent Index methodology](https://artificialanalysis.ai/methodology/coding-agents-benchmarking)
- [APEX-SWE paper](https://arxiv.org/abs/2601.08806), [launch](https://www.mercor.com/blog/introducing-apex-swe/), [harness](https://github.com/Mercor-Intelligence/apex-swe)
- [FreshBrew paper](https://arxiv.org/abs/2510.04852), [harness and dataset](https://github.com/mrcabbage972/freshbrew)
- [SWE Atlas paper](https://arxiv.org/abs/2605.08366), [harness](https://github.com/scaleapi/SWE-Atlas), [Q&A](https://labs.scale.com/leaderboard/sweatlas-qna), [Test Writing](https://labs.scale.com/leaderboard/sweatlas-tw), [Refactoring](https://labs.scale.com/leaderboard/sweatlas-refactoring)
- [DeepSWE leaderboard](https://deepswe.datacurve.ai/) and [harness](https://github.com/datacurve-ai/deep-swe)
- [SWE-bench Multilingual](https://www.swebench.com/multilingual.html), [Verified Mini](https://hal.cs.princeton.edu/swebench_verified_mini), [SWE-bench Pro](https://scaleapi.github.io/SWE-bench_Pro-os/)
- [SWE-Effi](https://arxiv.org/abs/2509.09853)
- [NL2Repo-Bench](https://arxiv.org/abs/2512.12730)
- [LiveSQLBench](https://livesqlbench.ai/)
- [SkillsBench](https://www.skillsbench.ai/)
- [ProgramBench](https://programbench.com/)
- [KernelBench](https://github.com/ScalingIntelligence/KernelBench)
- [CyberGym](https://www.cybergym.io/cybergym/)
- [Terminal-Bench Core 0.1.1 leaderboard](https://www.tbench.ai/leaderboard/terminal-bench/1.0) and [Terminal-Bench 2.1](https://www.tbench.ai/news/terminal-bench-2-1)
- [SWE-bench Verified Mini leaderboard](https://hal.cs.princeton.edu/swebench_verified_mini)
