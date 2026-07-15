# Coding-agent evaluation review

_Last reviewed: 2026-07-15_

## Decision

The next cospa suite should **not** be another short-answer coding or general
reasoning benchmark. Aider Polyglot already measures small, test-driven code
changes, and current strong configurations are near its ceiling. The missing
signal is whether an agent can investigate a real system, use tools, distinguish
assumptions from observed state, and complete production-shaped engineering
work.

Use a portfolio with distinct roles instead of asking one suite to do
everything:

| Role | Suite | Run policy |
| --- | --- | --- |
| Fast multilingual regression | Aider Polyglot | Small fixed slices during development; all 225 only for shortlisted configurations or releases |
| External leaderboard anchor | **Terminal-Bench Core 0.1.1 now**; Terminal-Bench 2.1 at milestones | Pin the official task revision and run sparingly, rather than sweeping every model x adapter cell |
| New harness/trace discriminator | **SWE Atlas Test Writing + Codebase Q&A** | Harbor-native, cost-gated 12-task pilot, then a fixed 24-task internal screen |
| Production tool-stack stress | **APEX-SWE Observability**, then Integration | Run after the cheaper Harbor-native pilot proves which adapters deserve the heavier environment |
| Cross-suite trajectory review | **Normalized cospa events + AgentLens-style paired review** | Re-score the same adapter runs; do not buy another set of agent trajectories just to study traces |

The much larger benchmark inventory reviewed below changes the _measurement
layer_ more than the suite order. AgentLens supplies a useful trace-review
pattern, SWE-Explore offers an isolated exploration diagnostic, and
FeatureBench/RACE-bench expose feature-development gaps. None is a cheaper,
cleaner replacement for the first SWE Atlas pilot once published token use,
integration burden, and scorer dependencies are included.

The immediate leaderboard fix is still to pin the existing Terminal-Bench
integration to **`terminal-bench-core==0.1.1`**. That is the 80-task dataset
behind the official Terminal-Bench 1.0 leaderboard; cospa's current 241-task
`@head` path is not comparable to that leaderboard or to Terminal-Bench 2.1.
Terminal-Bench 2.1 is the more current 89-task milestone anchor, but its official
submission protocol uses five attempts per task, or 445 trajectories.
Benchmark-name overlap alone is not direct comparability; dataset revision,
attempts, resources, model settings, and scaffold protocol must also match.

After comparing the actual harnesses and trace artifacts, **APEX-SWE is no
longer the unqualified first implementation**. It still has the richest
production-shaped traces: multi-service discovery and integration, logs,
dashboards, issue/chat context, code changes, and closed-loop verification. But
SWE Atlas is the better first fit for cospa's specific job of comparing agent
harnesses under a token/time budget:

- all 284 tasks and their Harbor-format environments are public, and the
  reference runs already compare minimal and native scaffolds;
- Test Writing and Q&A expose exploration, runtime analysis, test execution,
  verification, and stopping behavior in a more normalized shell trajectory;
- cospa already has Harbor agent adapters, whereas APEX uses separate custom
  ReAct and Inspect loops for its Integration and Observability halves;
- SWE Atlas publishes a cost/capability analysis ($0.35--$1.90 per task for
  selected Q&A + Test Writing systems), while APEX publishes no token or cost
  distribution and its Integration runs average 53.5 episodes with a one-hour
  ceiling.

SWE Atlas is not automatically cheap: its leaderboard runs `k=3`, permits up to
250 steps and six-hour sandboxes, and requires a pinned LLM rubric judge. The
cost figures are model-specific dollars, not token or wall-time guarantees.
That is why the recommendation is a measured 12-task pilot, not all 214 Q&A +
Test Writing tasks.

APEX-SWE remains the best _second_ suite when the deployment question is
"can this agent debug or integrate a production-like system?" Start with six
Observability cases, one per public source repository. The hidden benchmark
covers five languages, but the public Observability set is 15 Go and 10 Python
cases, so the previously proposed five-language public slice is impossible.
The public 50 is also a development set, not the hidden leaderboard: the paper
reports public scores averaging 12.8 points higher and middle-rank changes. Use
it for trace-rich stress testing, not cheap external comparison.

**SWE-bench Verified Mini** remains an optional second external anchor. It is a
fixed random 50-task subset with a paused HAL leaderboard, but is Python-only
and highly scaffold-dependent. **DeepSWE** remains a milestone/frontier suite:
its public rows report 46K--276K output tokens and 61--268 steps per task.

Custom SWE Atlas or APEX slices have no external leaderboard. The pilot measures
cost, integration, and large harness effects; external sanity comes from pinned
Terminal-Bench. Exact SWE Atlas leaderboard comparison requires the full
workflow, the published judge, and `k=3`, so reserve it for a winning
configuration rather than the adapter matrix.

There is now a stronger external comparison target than the previous review
credited: the **Artificial Analysis Coding Agent Index** combines DeepSWE (113
tasks), Terminal-Bench v2 (84 compatible tasks), and SWE-Atlas-QnA (124 tasks),
reports harness-specific scores plus tokens, cost, and wall time, and repeats
all tasks three times. This independently supports SWE Atlas as a relevant
harness discriminator. It does not make the index cheap: 321 tasks x `k=3` is
963 trajectories, and SWE-Atlas-QnA alone is 372. Use those protocols only for
a winning milestone configuration.

## Evidence labels

Candidate discovery started from the user-supplied
**[Agentic coding benchmark map — July 15, 2026](https://chatgpt.com/share/6a5786c0-00bc-83ee-816e-f61cf7bc4f7e)**.
That broad secondary inventory is valuable for coverage, but it is not treated
as primary evidence. Claims that affect the recommendation below were checked
against benchmark papers, datasets, harnesses, or first-party leaderboards.

Token and runtime figures are unusually easy to misread in agent benchmarks.
This document uses these labels:

- **Discovery inventory**: a secondary map used to find candidates, not to
  establish a numerical claim.
- **Measured here**: calculated from durable cospa results or the vendored
  dataset currently checked out.
- **Published**: stated by the benchmark or model authors.
- **Public-trace reanalysis**: independently calculated from benchmark-released
  trajectories; not a benchmark-author claim or a cospa measurement.
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
| **[SWE Atlas](https://github.com/scaleapi/SWE-Atlas)** | 284 public tasks: 124 Codebase Q&A, 90 Test Writing, 70 Refactoring across 18 repos. Q&A/TW use Go, Python, C, TypeScript; Refactoring adds C++ and JavaScript. | Runtime investigation, mutation-tested test authoring, and behavior-preserving multi-file refactors. Harbor-native; published mini-SWE-Agent baselines use one shell action per step. Deterministic checks are combined with expert rubrics graded by a pinned LLM judge. | `k=3`, 250-step agent configs and six-hour sandbox ceilings in published runs. Q&A + Test Writing cost about $0.35--$1.90/task for selected systems; actual tokens and wall time are **unknown**. Refactors span 35--2,073 gold lines. | **Best first cospa integration.** It directly measures scaffold-sensitive exploration and engineering rigor, reuses Harbor, and has better cost evidence than APEX. Pilot Q&A + Test Writing; reserve Refactoring and full `k=3` runs for milestones. |
| **[APEX-SWE](https://www.mercor.com/apex/apex-swe-leaderboard/)** | 200 hidden cases, 50 public dev cases; split evenly between Integration and Observability. Hidden Observability covers five languages, but the public 25 are 15 Go and 10 Python tasks across six repos. Integration spans PostgreSQL, LocalStack/AWS, Plane, CRM, e-commerce, mail, chat, and ticketing services but typically produces Python scripts. | Persistent shell, file tools, and MCP services. Integration builds end-to-end systems; Observability searches logs/chat/issues and patches repositories. Program tests determine pass/fail. The two workflows ship separate custom ReAct and Inspect harnesses with detailed logs. | One-hour paper timeout; Integration averages 53.5 episodes overall (44.9 on success). Tokens, cost, and wall-time distribution: **unknown**. Public-dev scores average 12.8 points above hidden results. | **Richest production trace, second implementation.** Strongest observability/cross-service content and deterministic headline grading, but the service stack, narrow public-language coverage, and two custom loops add cost, flakiness, and adapter-porting work. Start with six Observability tasks after SWE Atlas. |
| **[FreshBrew](https://github.com/mrcabbage972/freshbrew)** | 228 real Maven/Java repositories; migrate JDK 8 projects to JDK 17 or 21. | Agent reads/writes files, repeatedly runs Maven verification, and may search documentation. Success requires compile + all original tests + no more than a 5-point test-coverage drop, limiting test/code deletion reward hacks. | Up to 100 steps. On successful migrations, published median steps were roughly 5 (DeepSeek-V3), 13 (GPT-4.1), and 17 (Gemini 2.5 Flash). Tokens and wall time: **unknown**. The best JDK-17 result was 52.3%; JDK 21 was harder. | **Best deterministic fallback.** Real repo/build loops and likely shorter trajectories, but only Java/Maven and one task family. Use JDK 21 and stratify by project complexity. |
| **[DeepSWE](https://deepswe.datacurve.ai/)** | 113 original tasks over 91 repositories in TypeScript, Go, Python, JavaScript, and Rust. | Long-horizon repository changes in isolated Harbor/Pier environments with implementation-agnostic program verifiers. | Current leaderboard rows report 46K--276K output tokens, 61--268 steps, and about $2.36--$26.40 per task. Scores span 12--73%, so it separates current systems well. Input tokens and wall time are **unknown**. | **Best milestone frontier benchmark, not cheap.** Its own CLI supports a deterministic 10-task sample seed, useful after integration, but tiny samples are noisy. |

### Established issue-resolution options

| Benchmark | Tasks / languages | Signal and saturation | Token/runtime evidence | Verdict |
| --- | --- | --- | --- | --- |
| [SWE-bench Verified](https://www.swebench.com/) | 500 human-validated tasks, Python, 12 repositories | Real GitHub issue repair, but current systems commonly score 70--88%; OpenAI and Anthropic now discuss contamination/memorization screening. | SWE-Effi shows how scaffold-dependent cost is: on its 50-task sample, published averages ranged from 34K to 8.1M input and 1.7K to 41K output tokens per task. | Do not add as the primary new signal. Python-only and increasingly saturated. |
| [SWE-bench Verified Mini](https://hal.cs.princeton.edu/swebench_verified_mini) | Fixed random 50-task subset; HAL lists 33 evaluations across two scaffolds and 18 models | Inherits Verified's Python-only distribution and contamination risk; the paused leaderboard currently tops out at 72%. | HAL publishes traces and $4.72--$1,599.90 total run costs, demonstrating extreme scaffold/model variance, but not a stable token or wall-time summary. | **Optional second leaderboard anchor.** Useful when SWE compatibility matters, but redundant with pinned TB Core for the immediate portfolio and not proven cheap on cospa. |
| [SWE-bench Pro](https://labs.scale.com/leaderboard/swe_bench_pro_public) | 1,865 total; 731 public from 11 repos; Go, Python, JavaScript, TypeScript | Large, multi-file issue repair with current public scores up to roughly 62%. It has the strongest public trajectory-analysis ecosystem here: 1,460 SWE-Agent runs, a Docent collection, and third-party trace tooling. | **Public-trace reanalysis** of 616 paired trajectories finds 2.80M--3.13M cumulative input, 7.1K--17.7K output, 64--78 model calls, and a 250-turn cap per task. A 731-task run therefore implies an estimated 2.0B--2.3B cumulative input tokens. Wall time is not recorded. | **Best existing trace corpus; wrong run budget.** Analyze the downloadable traces without rerunning it. A 50-task slice still implies roughly 140M--157M input tokens at those observed rates and has no standard leaderboard. |
| [SWE-bench Multilingual](https://www.swebench.com/multilingual.html) | 300 tasks, 42 repos, C, C++, Go, Java, JS, TS, PHP, Ruby, Rust | Better language breadth; median gold patch is only 10 lines. Recent model cards report roughly 52--79%, so it is less saturated than Verified but still conventional issue repair. | Original baseline used a $2.50/task cap. Current input/output and runtime distributions are **unknown**. | Good release regression suite, but 300 tasks and small patches do not solve the short, production-engineering gap. |
| [SWE-Effi](https://arxiv.org/abs/2509.09853) | A metrics framework demonstrated on a stratified 50-task Verified sample, not a new task set | Adds effectiveness under token, cost, CPU, and inference-time budgets and exposes expensive failures. | Publishes per-scaffold/model token and time data. | Adopt its _metrics_ in cospa; do not count it as an additional eval. |

### Specialized and adjacent options

| Benchmark | Scope | Published scale / usage | Why it is not the default next suite |
| --- | --- | --- | --- |
| [HiL-Bench](https://labs.scale.com/leaderboard/hil) | Selective escalation on 150 SWE-bench Pro-derived and 150 SQL tasks; 100 public tasks per domain. Each has 3--5 progressively discovered blockers and an `ask_human()` tool. | Main results use three modes and `k=3`; reproducing just the public SWE matrix is 900 trajectories. It saves JSON trajectories and reports ASK-F1 plus pass@3; actual token/runtime tables are not text-published, and the human simulator is a frozen Llama-3.3-70B. | **High-value later harness ablation, not the base coding score.** Uniquely measures whether a scaffold asks instead of guessing, but adds an oracle service and deliberately floors ordinary task success. Pilot only after general coding is qualified. |
| [MCP-Atlas](https://github.com/scaleapi/mcp-atlas) | 1,000 tasks, 500 public, over 36 real MCP servers and 220 tools; about 22% use coding-category servers. | Usually 3--6 required calls with distractors; current harness allows 100 calls and 30 minutes. Raw conversations are logged, but tasks are read-only and final-answer claims are graded by an LLM judge. Tokens/runtime are **unknown**; current top score is about 88%. | **Tool-use sidecar, not coding.** Good for tool discovery, schemas, orchestration, and synthesis, but it does not leave a code patch or test an engineering artifact. |
| [MCPMark Verified](https://github.com/eval-sys/mcpmark) | 127 programmatically verified stateful tasks across GitHub, Notion, filesystem, PostgreSQL, and Playwright; also offers 10 easy tasks per service. | Objective per-task verifiers and public trajectory logs make it cleaner than MCP-Atlas for a small tool-use smoke, but the current leader is at 92.9% and most tasks are not code engineering. | **Best optional MCP smoke.** A no-account filesystem/Postgres or easy slice may cheaply test tool plumbing, but keep its score separate from coding capability. |
| [Toolathlon-Verified](https://github.com/hkust-nlp/Toolathlon) | 108 long-horizon tasks over 600+ tools with public trajectories. | Up to 90 minutes per task and substantial account/service setup; a public evaluation service reduces setup but not trajectory cost. | Excellent general-tool trace corpus, far too operationally heavy for the next cospa suite. |
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

### High-impact additions from the broader benchmark map

The full discovery map contains dozens of useful families. The following are
the missing candidates most likely to alter a cospa decision; mirroring the
entire catalog here would obscure rather than improve the run plan.

| Capability gap | Strong candidate and primary evidence | Cost/trace implication | Decision for cospa |
| --- | --- | --- | --- |
| Fresh multilingual issue repair | **[SWE-bench Live MultiLang](https://github.com/microsoft/SWE-bench-Live)** has 743 tasks across six languages and 381 repositories as of its May 2026 release, with executable sandboxes and a public submission path. | Actual token/runtime use is **unknown**. The rolling full split improves freshness but complicates longitudinal comparison unless a release is pinned. | Best future freshness anchor, not a short harness screen. Evaluate a frozen release only after the current suite can afford another large issue-repair family. |
| Complex feature implementation | **[FeatureBench](https://github.com/LiberCoders/FeatureBench)** has 200 Python tasks and an official 30-task Lite split with executable F2P/P2P grading and a public leaderboard. Its L1 gold solutions average 790 lines over 15.7 files. | Published Lite baselines average **2.6M--9.0M input tokens/task**, 13K--41K output, and permit up to 500 steps. One 30-task pass therefore implies an **estimated 78M--270M input tokens** before repetitions. | Best fixed feature-development milestone identified by the map, but “Lite” is not cheap enough for the routine adapter matrix. |
| Feature planning and intermediate reasoning | **[RACE-bench](https://arxiv.org/abs/2603.26337)** provides 528 Python feature tasks and a 100-task Lite set, executable patch checks, and structured targets for intent, files, implementation tasks, and steps. | On Lite, published medians span 145K--3.49M tokens and 156--1,121 seconds per task depending on agent/model. Trace normalization and several reasoning metrics require a summarizer or judge. | Valuable when planning quality is the deployment question; too large and judge-dependent to displace SWE Atlas as the first screen. |
| Full issue lifecycle | **[SWE-Cycle](https://github.com/tubehao/SWE-Cycle)** evaluates environment reconstruction, implementation, test generation, and a combined FullCycle over 489 filtered issues. It is implemented on Harbor. | FullCycle allows three hours per instance and uses an execution-capable LLM judge; the complete suite is intrinsically a milestone campaign. | Strong later autonomy benchmark. Do not confuse Harbor compatibility with low trajectory or verifier cost. |
| Direct trajectory quality | **[AgentLens](https://github.com/agent-lens/agent-lens-bench)** combines formal checks with cited LLM reviews of instruction compliance, tool use, recovery, verification, and interaction quality. Its current public fold is 16 Java scenarios x two personas, or 32 trajectories. | Compact task count, but collection requires a headless JetBrains IDE, an LLM user simulator, and an LLM judge. Published token/runtime distributions are **unknown**. | Borrow its _evaluation pattern_ for existing cospa traces first. Integrating its Java/IDE fold is optional and should not block benchmark-native scoring. |
| Repository exploration | **[SWE-Explore](https://github.com/Qiushao-E/SWE-Explore-Bench)** scores a top-five ranked list of code regions for 848 issues across ten languages, with line-level labels derived from successful trajectories. | The standard loop omits patch generation and is therefore structurally cheaper, but agent token/runtime distributions are **unknown**. It measures context selection, not coding completion. | Best candidate for a focused exploration A/B after trace normalization; keep its score separate from task success. |
| Safe action boundaries | **[UnderSpecBench](https://arxiv.org/abs/2607.02294)** expands 69 DevOps task families into 2,208 intent/target/blast-radius variants and uses deterministic side-effect oracles for acted runs. | The complete matrix is large, but paired explicit/underspecified variants can isolate scaffold effects. Non-action disposition still uses an LLM judge. | High-value safety sidecar if cospa will gate autonomous DevOps actions; not a general coding score. |
| Test generation compatibility | **[SWT-Bench Verified](https://swtbench.com/)** provides 433 human-verified Python issue-to-test tasks and an established leaderboard. | Current specialized systems are already near 87% and public aggregate token/runtime use is **unknown**. | Useful external test-generation anchor, but SWE Atlas Test Writing is less saturated, multilingual, and evaluates broader engineering rigor. |

## Trace-specific comparison

"Best agentic traces" has several meanings, and the benchmarks optimize
different ones:

| Need | Best choice | Reason |
| --- | --- | --- |
| Richest production-behavior trace | **APEX-SWE** | The agent must combine shell/file work with services, telemetry, tickets/chat, implementation, and verification. Failures expose environment understanding and epistemic discipline, not only patch correctness. |
| Cleanest next harness A/B in cospa | **SWE Atlas Q&A + Test Writing** | Harbor accepts interchangeable agents while keeping the task environment and grader fixed; a common single-shell action interface makes exploration, execution, and verification phases easier to compare. |
| Best already-published coding trace corpus | **SWE-bench Pro** | Public full trajectories, Docent browsing, and independent cost/token/intent tooling exist. Reuse those artifacts; do not pay to regenerate all 731 tasks. |
| Best direct trajectory evaluator to adapt | **AgentLens** | It pairs formal outcomes with evidence-citing reviews and side-by-side comparison. Its evaluator design is more portable to cospa than its current IDE-specific task fold. |
| Best exploration-only diagnostic | **SWE-Explore** | Ranked line regions separate context retrieval from patch synthesis and expose whether one harness finds useful evidence earlier or with less noise. |
| Best help-seeking trace | **HiL-Bench** | ASK-F1 directly scores whether the agent detects an unresolvable gap and asks a targeted question instead of silently assuming. |
| Best pure MCP trace | **MCPMark** for objective state changes; **MCP-Atlas** for broad read-only discovery | Both isolate tool behavior, but neither is a substitute for repository engineering. |

For cospa, trace quality also requires a common event schema. Normalize every
adapter into timestamped model turns, tool name/arguments/result size, file
diffs, test/build invocations, provider usage fields, compaction/cache events,
and final verifier subchecks. Benchmark-native traces are otherwise too
different to support fair claims such as "adapter A explores earlier" or
"adapter B verifies more."

Score mechanical trace facts first: time and tokens to first edit, files read
before editing, test/build calls, repeated tool errors, recovery after failure,
last-edit-to-final-verification distance, and whether the final verifier was
actually run. Then apply a pinned, blinded, side-order-randomized pairwise judge
to a small stratified sample for qualitative claims such as instruction
compliance or epistemic discipline. Judge reviews must cite trace events, report
judge cost and disagreement, and remain diagnostic; they must never override a
benchmark's programmatic outcome.

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

### Phase A: cost and reliability pilot (`swe_atlas_pilot12`)

Freeze 12 public SWE Atlas task IDs and the upstream commit in a checked-in
manifest. Select by metadata before looking at target-model outcomes:

- **Test Writing (8):** two each in Go, Python, C, and TypeScript, with the set
  covering unit, integration, and acceptance tests;
- **Codebase Q&A (4):** one per language, collectively covering architecture,
  root-cause analysis, onboarding, and security;
- preserve the original prompts, images, test/mutation patches, rubrics, and
  timeout semantics;
- pin the rubric judge and judge prompt. Report the programmatic mutation
  check separately from the LLM-graded manifest and rubric checks so a
  deterministic submetric survives judge changes;
- run one representative model with `pi_vanilla`, `k=1`, then repeat all 12
  with the exact same configuration if the first pass qualifies.

Promotion gates:

| Gate | Requirement |
| --- | --- |
| Runtime | First-pass summed agent wall time <= 2 h and total setup + agent + verifier/judge time <= 4 h for 12 tasks; report median and p90 |
| Tokens | Default first-pass ceiling <= 12M normalized agent tokens over 12 tasks and p90 <= 2M/task; record judge usage separately rather than charging it to the agent |
| Telemetry | >= 95% of trials have non-overlapping input/cache/output/reasoning, wall-time, tool-call, file-diff, and verifier-subcheck fields |
| Infrastructure | <= 5% fail before a valid task environment reaches the agent, with no repeated unexplained pristine-verifier failure |
| Grading | Pin the judge; verify the deterministic checks and one real rubric-scoring path end to end |
| Difficulty | Require nontrivial binary or subcheck variation; bracket a 0% or >= 90% result with one stronger or weaker configuration |
| Reliability | Complete `k=2` on all 12 matched tasks and publish outcome flips rather than pruning them |

The 12M ceiling is a campaign gate, not a claim about SWE Atlas usage. The
paper's $0.35--$1.90 per-task range does not expose tokens or wall time and does
not include every model cospa will run. Twelve binary tasks have a worst-case
95% margin around ±28 points; this phase qualifies infrastructure, cost, and
large scaffold effects rather than ranking close systems.

### Cross-cutting: paired trace review (no extra agent trajectories)

Reuse every matched Phase A/B trajectory for a second, diagnostic report:

- compute the mechanical event metrics above directly from normalized logs;
- compare adapters only on identical task/model/provider blocks;
- blind adapter names and randomize left/right order for a pinned pairwise judge
  on a predeclared sample of passes, failures, and discordant outcomes;
- retain cited reviews as artifacts and record judge model, prompt, tokens,
  cost, and repeat agreement separately from agent usage;
- keep benchmark pass/fail or rubric scores primary. A persuasive trace cannot
  turn a failing artifact into a pass.

This imports the useful part of AgentLens without paying for its separate
headless-IDE/user-simulator collection loop. SWE-Explore can later add
line-level exploration labels on its own tasks, but generic trace metrics should
ship first because they apply to Aider, Terminal-Bench, SWE Atlas, and APEX.

### Phase B: routine screen (`swe_atlas_screen24`)

If Phase A passes, freeze 24 tasks: 16 Test Writing and eight Q&A, balanced by
language and stratified by task category. Report:

- overall and per-workflow pass rate with Wilson intervals;
- Test Writing LLM-graded manifest, programmatic mutation, mandatory-rubric,
  and end-to-end pass rates;
- Q&A rubric coverage as well as strict all-rubrics pass;
- cumulative agent and judge usage, tool calls, wall time, file/test activity,
  and infrastructure failures;
- paired task deltas and an exact paired test/interval for adapter comparisons;
- pass per million normalized agent tokens and pass per agent-hour.

At 24 tasks the worst-case 95% margin remains about ±20 points. Use one model to
select the winning one or two adapters, then compare models only on those
adapters. A custom 24-task score is directional. A directly comparable SWE
Atlas Test Writing leaderboard run requires all 90 tasks, the published judge,
and `k=3` (270 trajectories); do that only for a winning milestone
configuration.

### Phase C: production stress (`apex_observability_6`)

After the Harbor-native screen is stable, add one public Observability task from
each of APEX-SWE's six public source repositories: bor, gossamer,
podman-compose, op-geth, git-bug, and paperless-ngx. The public set contains 15
Go and 10 Python tasks; TypeScript, Java, and C++ exist only in the hidden set,
so reports must not imply five-language public coverage. Inspect whether the
winning adapter triangulates telemetry and verifies its hypotheses. Apply the
same gates at half the Phase A campaign budget.

Only then consider a mixed `apex_swe_pilot10` by adding four Integration tasks
across distinct service combinations. Do not merge its score with SWE Atlas:
Integration uses a different custom loop, usually writes Python scripts, and
stresses service orchestration more than repository engineering. The public dev
set also does not reproduce the hidden APEX leaderboard.

### Deterministic fallback: `freshbrew_jdk21_32`

If SWE Atlas judge dependence or trajectory cost is unacceptable, choose 32
FreshBrew projects, eight from each repository-complexity quartile, and preserve
the JDK-21 compile, full-test, and coverage-drop gates. Track compile-only,
test-pass, and full coverage-guard success under the same four-hour target. The
suite name and reports must retain its limitation: this measures Java
modernization, not general software engineering.

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

## Sources

- Discovery inventory (secondary): [Agentic coding benchmark map — July 15, 2026](https://chatgpt.com/share/6a5786c0-00bc-83ee-816e-f61cf7bc4f7e)
- [Artificial Analysis Coding Agent Index](https://artificialanalysis.ai/agents/coding-agents) and [methodology](https://artificialanalysis.ai/methodology/coding-agents-benchmarking)
- [AgentLens paper](https://arxiv.org/abs/2607.06624) and [harness](https://github.com/agent-lens/agent-lens-bench)
- [SWE-Explore paper](https://arxiv.org/abs/2606.07297) and [harness](https://github.com/Qiushao-E/SWE-Explore-Bench)
- [FeatureBench paper](https://arxiv.org/abs/2602.10975), [harness](https://github.com/LiberCoders/FeatureBench), and [public results](https://libercoders.github.io/FeatureBench/)
- [RACE-bench](https://arxiv.org/abs/2603.26337)
- [SWE-Cycle paper](https://arxiv.org/abs/2605.13139) and [Harbor-based harness](https://github.com/tubehao/SWE-Cycle)
- [SWE-bench Live](https://github.com/microsoft/SWE-bench-Live)
- [UnderSpecBench](https://arxiv.org/abs/2607.02294)
- [SWT-Bench](https://swtbench.com/)
- [APEX-SWE paper](https://arxiv.org/abs/2601.08806), [public data](https://huggingface.co/datasets/mercor/APEX-SWE), [launch](https://www.mercor.com/blog/introducing-apex-swe/), [harness](https://github.com/Mercor-Intelligence/apex-swe)
- [FreshBrew paper](https://arxiv.org/abs/2510.04852), [harness and dataset](https://github.com/mrcabbage972/freshbrew)
- [SWE Atlas paper](https://arxiv.org/abs/2605.08366), [harness](https://github.com/scaleapi/SWE-Atlas), [Q&A](https://labs.scale.com/leaderboard/sweatlas-qna), [Test Writing](https://labs.scale.com/leaderboard/sweatlas-tw), [Refactoring](https://labs.scale.com/leaderboard/sweatlas-refactoring)
- [DeepSWE leaderboard](https://deepswe.datacurve.ai/) and [harness](https://github.com/datacurve-ai/deep-swe)
- [SWE-bench Multilingual](https://www.swebench.com/multilingual.html), [Verified Mini](https://hal.cs.princeton.edu/swebench_verified_mini), [SWE-bench Pro public leaderboard](https://labs.scale.com/leaderboard/swe_bench_pro_public), and [public trace reanalysis](https://nilenso.github.io/swe-bench-pro-cost-token-time-analysis/)
- [HiL-Bench paper and leaderboard](https://labs.scale.com/leaderboard/hil), [harness](https://github.com/hilbenchauthors/hil-bench)
- [MCP-Atlas paper and leaderboard](https://labs.scale.com/leaderboard/mcp_atlas), [harness](https://github.com/scaleapi/mcp-atlas)
- [MCPMark Verified](https://github.com/eval-sys/mcpmark)
- [Toolathlon-Verified](https://github.com/hkust-nlp/Toolathlon)
- [SWE-Effi](https://arxiv.org/abs/2509.09853)
- [NL2Repo-Bench](https://arxiv.org/abs/2512.12730)
- [LiveSQLBench](https://livesqlbench.ai/)
- [SkillsBench](https://www.skillsbench.ai/)
- [ProgramBench](https://programbench.com/)
- [KernelBench](https://github.com/ScalingIntelligence/KernelBench)
- [CyberGym](https://www.cybergym.io/cybergym/)
- [Terminal-Bench Core 0.1.1 leaderboard](https://www.tbench.ai/leaderboard/terminal-bench/1.0) and [Terminal-Bench 2.1](https://www.tbench.ai/news/terminal-bench-2-1)
- [SWE-bench Verified Mini leaderboard](https://hal.cs.princeton.edu/swebench_verified_mini)
