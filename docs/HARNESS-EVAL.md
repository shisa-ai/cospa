# Evaluating harness and scaffold utility

_Last reviewed: 2026-08-16_

This document defines how Cospa should interpret `pi_vanilla` versus
`pi_devstack`, what the current BigCodeBench (BCB) and SWE-PolyBench (PB)
campaigns actually expose, and how to measure capabilities that matter in
real development but have no useful opportunity in those suites.

Evidence labels follow `docs/EVALS.md`:

- **Measured here** — calculated from durable Cospa artifacts or inspected
  local configuration/source.
- **Observed trace** — directly present in an exported Pi session.
- **Design recommendation** — proposed methodology, not an implemented suite.

## Decision

The current BCB/PB `pi_vanilla` versus `pi_devstack` comparison is useful for
runtime qualification, gross regressions, and some offline workflow behavior.
It is **not** a valid estimate of the utility of the complete day-to-day
`~/devstack` workstation profile.

The central mismatch is opportunity:

1. BCB and PB deliberately deny public network access, so web research cannot
   help and can only consume budget when attempted.
2. BCB's short function-level tasks rarely benefit from planning, background
   execution, compaction, scheduling, or autonomous optimization loops.
3. PB gives task management and background execution some opportunity, but it
   removes the web/browser stack and does not reproduce every workstation
   configuration file.
4. UX, account, provider, and interactive-session packages do not improve a
   one-prompt headless patch score even when they are highly valuable to a
   human developer.
5. A mutable bundle of many packages cannot identify which capability helped,
   which distracted the model, or which was merely inert.

Keep BCB as a coding/protocol anchor and PB as an offline repository-patching
benchmark. Measure broader harness utility with versioned capability profiles,
deterministic capability-specific suites, and replay of real development
sessions.

## What vanilla and devstack mean today

### Vanilla baseline

`harness/adapters/pi_vanilla.py` launches Pi with `--no-extensions`. Current Pi
0.84.2 provides these seven built-in coding tools:

- `read`
- `bash`
- `edit`
- `write`
- `grep`
- `find`
- `ls`

Older Cospa documentation that calls this a four-tool baseline describes a
prior Pi surface. The benchmark identity should record the actual active tool
set rather than infer it from the adapter name.

### Canonical workstation stack

`~/devstack/pi-packages.json` declares 16 packages. The stack combines several
distinct product categories:

- web retrieval and browser automation;
- task, goal, background-job, scheduling, and autonomous-loop workflows;
- context compaction and continuation;
- providers, account rotation, and quota visibility;
- interactive TUI, autocomplete, and code-preview UX.

These are not interchangeable forms of coding assistance. Some modify the
model-visible tool schema, some react to session lifecycle events, and some are
human-facing or provider-facing only.

### The installed and evaluated stack is not the canonical manifest

**Measured here:** the canonical manifest and current
`~/.pi/agent/settings.json` each contain 16 package entries, but their contents
differ:

- canonical-only: `npm:@lhl/pi-vertex`;
- installed-only: retired `npm:pi-context-prune`.

Cospa's generic devstack adapter copies the current user settings and mounts the
current package directories into a private bubblewrap namespace. Harbor mounts
`npm/`, `git/`, and a sanitized settings snapshot. The treatment is therefore
derived from mutable host state, not directly from the checked-in canonical
manifest.

The private profiles also do not copy every workstation-side configuration
file. For example, `pi-setup.sh` enables VCC's default-compaction override in
`~/.pi/agent/pi-vcc-config.json`, but the current generic and Harbor profile
builders copy settings/model/package resources rather than that file. Loading
`pi-vcc` in a benchmark does not by itself prove that the day-to-day compaction
policy was active.

This matters experimentally: two rows labeled `pi_devstack` may have different
package versions, settings, active schemas, and lifecycle behavior unless the
complete profile is frozen and fingerprinted.

## Capability inventory and current-suite applicability

| Component | Addition over vanilla | Generic BCB arm | PB/Harbor arm | Utility in current BCB/PB |
| --- | --- | --- | --- | --- |
| `pi-smart-fetch` | `web_fetch`, batch retrieval, browser-like TLS, readable extraction | Package/tool surface loaded; bubblewrap has no public route | Removed before Pi starts | None; failed attempts are overhead |
| Camoufox | Rendered/stealth fetch and web search | Loaded, but no public route | Removed before Pi starts | None |
| `pi-tasks` | Structured tasks, dependencies, updates, and queued execution | Available | Available | Low BCB opportunity; plausible PB workflow value |
| Background tasks | Non-blocking commands, durable logs, completion/output wakeups | Available | Available | Potentially useful for long builds and tests |
| `pi-goal` | Budgeted goals and punchlist completion | Available | Available | Little opportunity in one-prompt tasks |
| `pi-multiloop` | Measured optimize/research/dev loops plus setup skill | Available | Available | No current BCB/PB task asks for this workflow |
| `pi-vcc` | Deterministic compaction and history recall | Recall surface available; workstation override config not copied | Same | Potential only near context limits; incomplete reproduction of canonical policy |
| Continue-after-compaction | Resume after threshold compaction when the core does not | Loaded | Loaded | Narrow long-context resilience opportunity |
| `pi-schedule-prompt` | Cron/interval/one-shot prompts and heartbeat workflows | Available | Available | No useful lifecycle in a one-shot process |
| `pi-boomerang` | Autonomous passes with context collapse | Installed but tool disabled until a user command enables it | Same | Not tested |
| Code previews | Better rendering of tool/code output | Print mode | Print mode | Human UX only |
| Skill-dollar | Interactive skill autocomplete | No interactive UI | No interactive UI | None |
| Zentui | Statusline and TUI behavior | Loaded but running in print mode | Removed | None |
| Codex status | Account/quota visibility | Loaded | Loaded | Operational, not task-solving |
| Multicodex | Conditional account/provider rotation | Private profile lacks managed account state | Same | No task-solving value |
| Vertex provider | Additional model-provider support | Canonical manifest only; selected benchmark model is explicit | Same | Provider coverage, not scaffold quality |
| `pi-context-prune` | Pruning/query tools | Present only because installed settings drifted | Present | Noncanonical confound; retired by devstack |

The `outline-edit` and `realitycheck` tools described in the devstack README are
not entries in `pi-packages.json`, and no global Pi/Agent Skills directory was
present during this review. They were not part of the evaluated treatment.

### Effective benchmark surfaces

**Measured here:** the current installed session exposes roughly 28 active
extension tool schemas in addition to Pi's seven built-ins. The exact count is
configuration-dependent. PB removes the four smart-fetch/Camoufox web tools,
but retains many workflow schemas that have little task opportunity.

A larger tool surface is itself a treatment. It can provide capability, but it
can also increase prompt/schema tokens, weaken tool selection, invalidate cache
prefixes, or encourage bookkeeping that does not improve the artifact. A full
bundle versus vanilla comparison cannot separate those effects.

## Network and profile boundaries

### Generic BCB and other local adapters

`harness/subprocess_utils.py` runs the agent under bubblewrap with
`--unshare-net`. A host relay exposes only the selected model endpoint. Package
directories may be mounted read-only, but smart-fetch and Camoufox cannot reach
public sites. Every adapter prompt also states that network access, hidden
tests, and reference solutions are unavailable.

Therefore, a web tool call in BCB is evidence of tool selection under an
inapplicable capability, not evidence that web access helped.

### PB and Harbor-backed suites

PB declares `network_mode = "no-network"` for both agent and verifier. The
Harbor devstack installer removes:

- `pi-smart-fetch`;
- Camoufox;
- Zentui.

This removal is required for hermeticity and cross-image portability: the web
packages include browser/runtime assumptions or native Node addons that cannot
be safely bind-mounted across arbitrary benchmark images. It also means PB is
not testing full devstack web capability.

### Existing PB must remain offline

The public PB issues and repositories may have searchable issue discussions,
commits, or reference patches. Giving the agent unrestricted web access could
turn issue resolution into answer retrieval. Web-enabled capability testing
must use fresh/private tasks or a controlled corpus that contains relevant
documentation but no hidden solution.

## Observed tool uptake

**Measured here** across the scored devstack BCB/PB roots present on
2026-08-16:

| Capability family | Tool calls | Trials with at least one call | Interpretation |
| --- | ---: | ---: | --- |
| Task management | 822 | 92 | Dominant devstack-specific behavior |
| Background execution | 63 | 7 | Real capability, highly concentrated |
| Web retrieval/search | 96 | 28 | Attempts under a no-public-network policy |
| Context recall/pruning | 13 | 10 | Very limited uptake |
| Goal management | 31 | 31 | Mostly bookkeeping in this protocol |
| Multiloop | 0 | 0 | No measured opportunity or uptake |
| Scheduling | 0 | 0 | No measured opportunity or uptake |
| Boomerang | 0 | 0 | Disabled/not tested |

Tool use is not causal evidence of utility. Models choose tools based on task
difficulty, so pass rates among tool-using trials are selection-biased.

### Historical web-call contamination

The Luna PB devstack campaign ran before the final headless sanitizer removed
smart-fetch. Its traces contain approximately 85 web/batch calls. Sampled
sessions show explicit failures such as:

```text
Error: Connection failed to github.com. The server may be unreachable or
blocking requests.
```

Later Sol, Terra, and Qwen Harbor profiles excluded those packages. Those rows
share an adapter label but not an identical effective tool surface. This is an
additional reason not to interpret the historical score delta as a stable
full-devstack effect.

### Task-management uptake did not establish score lift

Task tools were heavily used, but paired outcomes did not show a consistent
benefit. Illustrative PB aggregates were:

| Model / reasoning | Vanilla | Devstack |
| --- | ---: | ---: |
| Luna / max | 11/28 | 7/28 |
| Terra / max | 8/28 | 6/28 |
| Sol / max | 10/28 | 10/28 |
| Qwen / xhigh | 8/28 | 7/28 |
| Qwen / medium | 11/28 | 10/28 |
| Qwen / low | 9/28 | 10/28 |

Across those six matched comparisons, vanilla uniquely solved 21 task/model
pairs and devstack uniquely solved 14. The conditions are heterogeneous and
not independent, so this is descriptive rather than a pooled significance
test. It does show that the current campaign has not demonstrated a reliable
positive scaffold effect.

The task tools also add process work. For example, Luna PB averaged 45.7 turns
under vanilla and 56.2 under devstack while the resolved count fell from 11 to
7; Sol averaged 41.0 versus 50.6 turns while both arms resolved 10. This does
not prove task tracking is unhelpful in real work. It shows that bookkeeping
cost and benefit must be measured separately on tasks with genuine planning
opportunity.

## Why BCB/PB provide weak discrimination

### BCB

The 15-task agentic panel is a fast coding/protocol smoke test. One task changes
the score by 6.7 percentage points. Near a 20% solve rate, the ordinary
binomial standard error is about 10 percentage points, before accounting for
model stochasticity. Most paired adapter comparisons differ by zero or one
task.

Function-level tasks also finish too quickly to exercise long builds, context
compaction, task dependencies, scheduling, human interaction, or iterative
optimization. BCB can detect a broken agent and a broad coding floor; it is a
poor general harness-utility benchmark.

The larger BCB Pareto60 panel is statistically and compositionally preferable,
but it still primarily measures coding with tools rather than the complete
workstation workflow.

### PB

PB has more realistic repository exploration, edits, and tests, but the
28-task panel remains small. One task changes the score by 3.6 points. Around a
35% solve rate, ordinary binomial uncertainty is roughly 9 percentage points
per arm (about 18 points for a simple 95% interval).

PB provides legitimate opportunity for planning and asynchronous tests, and
long runs may exercise context resilience. It still cannot measure web, UX,
provider/account management, recurring automation, or human session
workflows. Budget expirations and missing telemetry must also remain separate
from ordinary incorrect outcomes and efficiency calculations.

### Model-quality interpretation

BCB/PB can identify broad floors, catastrophic regressions, and large model
separations. They do not support confident ordering of nearby cells at `k=1`.
Cross-model rows are further confounded when they use different reasoning
levels, protocol generations, package profiles, or repeated-root aggregation.

For example, a viewer row with 15 unique BCB tasks but `Done 45/45` aggregates
multiple attempts and is not directly comparable to a single-run 15/15 row.
Independent repetitions should be reported as stability evidence, not silently
collapsed into a stronger-looking Pass@1.

## Capability-oriented evaluation design

### Principle: evaluate opportunity, not mere availability

For each capability, report a funnel rather than only final pass rate:

1. **Availability** — did the intended package/version/tool/config load?
2. **Opportunity** — did the task contain a situation where the capability
   could help?
3. **Uptake** — did the model invoke it naturally?
4. **Execution** — did the call succeed and return relevant information?
5. **Instrumental use** — did later reasoning or edits use that information?
6. **Outcome lift** — did the enabled arm improve paired task outcomes?
7. **Overhead/harm** — what extra schemas, turns, tokens, failures, and wall
   time did it introduce?

Do not assign a zero-utility conclusion to a capability when the suite has zero
eligible opportunities. Report it as not measured.

### Versioned modular profiles

**Design recommendation:** replace one mutable monolithic comparison with
small, frozen profiles:

| Proposed profile | Treatment |
| --- | --- |
| `pi_vanilla` | Current Pi built-ins only |
| `pi_workflow_planning` | `pi-tasks` + `pi-goal` |
| `pi_async_execution` | Background-task tools and wakeups |
| `pi_long_context` | VCC policy + continuation, with complete config |
| `pi_optimization_loop` | Multiloop extension + skill |
| `superpowers-bench-v1` | Pinned systematic debugging, TDD, and verification methodology |
| `pi_web_research` | Smart-fetch + Camoufox with controlled network |
| `pi_devstack_full` | Frozen canonical workstation profile |

Human-facing/provider packages may remain in `pi_devstack_full`, but they
should not be expected to change a headless coding score. Qualify them with
integration or human-workflow evidence instead.

Every profile should pin and record:

- package source, version, and git commit;
- active extension, tool, skill, prompt, and theme resources;
- tool-schema hash and system-prompt hash;
- non-package configuration files;
- Pi/Node versions;
- network policy and allowlisted hosts;
- model, thinking level, sampling, and capability/wall budgets.

`superpowers-bench-v1` is now an implemented example of this policy. It pins
upstream Superpowers v6.3.0 at
`b36e0829c6d0140e93cfef2ca599b1b07d4a7797` and selects the complete
headless-safe workflow closure for `systematic-debugging`,
`test-driven-development`, and `verification-before-completion`. Generic and
Harbor adapters materialize the same checksum-verified files. Trial manifests
record the source revision and per-skill snapshot hashes, and qualification
loads the files through Pi's real resource loader and asserts that all three
names reach the actual session system prompt. This is a controlled methodology
treatment, not the complete interactive Superpowers product.

### Four-arm causal pattern

Use the same model, task, budget, and repetition policy in four paired arms:

1. **Disabled** — capability absent.
2. **Sham** — model sees the same tool schema but execution is unavailable or a
   deterministic no-op. This estimates schema/selection overhead.
3. **Enabled** — capability works normally.
4. **Enabled + cue** — the task states that a relevant resource/workflow is
   available without prescribing the answer. This estimates the upper bound
   when discoverability is solved.

The difference between disabled and sham measures distraction; sham to enabled
measures executable capability value; enabled to cued measures tool-selection
or discoverability loss.

Use `k >= 3` on a compact diagnostic subset and task-level paired analysis.
Report discordant outcomes, confidence intervals, budget exhaustion, and
infrastructure failure separately. Do not use best-of-k as Pass@1.

## Proposed deterministic capability tracks

### Frozen-web engineering

Serve a versioned, allowlisted corpus containing unindexed fictional APIs,
release notes, migration guides, error documentation, and rendered pages. The
corpus must contain useful evidence but no hidden reference patch.

Candidate tasks:

- implement against API version N when model priors resemble N-1;
- diagnose an error whose identifier exists only in the frozen corpus;
- migrate a dependency using release notes outside the repository;
- reconcile conflicting documentation and cite the source used;
- retrieve content from static HTML for smart-fetch qualification;
- retrieve equivalent content from controlled JavaScript-rendered pages for
  Camoufox qualification.

Two variants answer different questions:

- **Capability-specific:** shell networking remains blocked and the extension
  receives controlled broker access. This isolates the tool.
- **End-to-end harness:** both arms receive equivalent network access; vanilla
  may discover and use `curl`, while devstack offers specialized search/fetch.
  This measures ergonomic harness value.

Live public-web trials should be a separate timestamped field evaluation with
allowlists and archived responses. They should not share a longitudinal
leaderboard with deterministic offline/frozen-web scores.

### Asynchronous build/test track

Use repository tasks with multiple independent slow commands under a fixed
wall-clock budget. Measure:

- time to a correct patch;
- useful work completed while tests run;
- stale/lost process rate;
- response to completion wakeups;
- final test coverage and verifier result.

Vanilla may attempt ordinary shell backgrounding. That is desirable: the test
should measure whether the extension is a more reliable end-to-end workflow,
not grant it an artificial exclusive capability.

### Long-context continuity track

Construct multi-stage tasks that reliably cross a compaction threshold and
include requirements introduced before compaction. Measure:

- retained requirements after compaction;
- duplicated or lost work;
- automatic continuation without human intervention;
- final correctness;
- context, summary, and retry token costs.

Run core compaction, VCC, VCC + continuation, and sham-schema arms separately.

### Planning and goal track

Use changes with 8-12 independently graded acceptance criteria and explicit
dependencies. Introduce an interruption or requirement change partway through.
Measure omissions, dependency-order violations, regression rate, unnecessary
bookkeeping, and completion. Tool-call counts are diagnostics, not success.

### Optimization-loop track

Use benchmark-driven tasks with a numeric objective and mechanical correctness
guard, such as parser/query latency, compression, bundle size, test latency,
or a local kernel benchmark. Give every arm the same wall-clock and iteration
budget. Score best guarded improvement, valid iterations, regressions, and
recovery from failed hypotheses.

### Long-lived and interactive workflow track

Scheduling, boomerang, quota/status UI, skill autocomplete, and TUI packages
need a different protocol. Suitable outcomes include:

- successful response to a delayed CI/incident event;
- resumed work after a session switch or compaction;
- human interventions and clarification burden;
- time to accepted change;
- quota/account failure recovery;
- user-rated observability and control.

A one-shot hidden-test score is not a meaningful oracle for these features.

## Counterfactual replay from real work

The strongest external-validity design is replay of actual development
opportunities:

1. Identify real sessions where web retrieval, background execution, task
   management, compaction, or loop tooling was used.
2. Snapshot repository, prompt, session context, and external resources
   immediately before the opportunity.
3. Exclude all later solution and outcome information.
4. Replay the same checkpoint with enabled, disabled, sham, and optionally cued
   profiles.
5. Grade the accepted artifact, elapsed time, tokens, interventions, retained
   requirements, and relevant tool evidence.

This samples the user's real workload rather than guessing its composition.
Anonymized replay tasks can become a private frozen panel. Their category
frequency can also supply workload weights if a single portfolio utility
summary is needed. Keep the underlying capability metrics visible rather than
hiding tradeoffs behind one weighted number.

## Reporting policy

Cospa reports should distinguish:

- **coding outcome:** native task resolution;
- **capability outcome:** opportunity, uptake, execution, instrumental use;
- **workflow efficiency:** wall time, turns, tokens, human interventions;
- **failure taxonomy:** incorrect, budget exhausted, infrastructure, verifier;
- **profile identity:** complete frozen package/config/tool fingerprint.

A capability with no opportunities is `not measured`, not `0% useful`. A tool
that is called but cannot execute is exposed but unavailable. A tool that
executes but does not affect the solution is uptake without demonstrated
utility. Only paired outcome/efficiency lift establishes causal value.

## Near-term actions

1. Stop describing the current PB arm as the complete day-to-day devstack; call
   it a sanitized headless workflow profile in analysis.
2. Freeze the exact profile and add package/config/tool/prompt fingerprints to
   trial manifests before the next scaffold campaign.
3. Remove canonical-versus-installed drift from benchmark inputs.
4. Keep web disabled on public historical issue benchmarks.
5. Build one small deterministic diagnostic for each of planning, async tests,
   long context, optimization loops, and frozen web.
6. Add enabled/disabled/sham/cued arms and `k >= 3` on the diagnostic subset.
7. Seed a private counterfactual-replay panel from real devstack sessions.
8. Continue using BCB/PB for the narrower coding and offline-patching questions
   they can answer.

## Evidence locations

- Canonical devstack inventory: `~/devstack/pi-packages.json`
- Devstack setup/config policy: `~/devstack/pi-setup.sh`
- Headless portability policy: `~/devstack/docs/PI-HEADLESS-CONTAINERS.md`
- Current installed profile: `~/.pi/agent/settings.json`
- Vanilla adapter: `harness/adapters/pi_vanilla.py`
- Generic devstack adapter: `harness/adapters/pi_devstack.py`
- Generic sandbox/network boundary: `harness/subprocess_utils.py`
- Harbor custom agents/profile sanitizer: `harness/harbor_agents.py`
- Harbor profile mounting/network policy: `harness/suites/terminal_bench.py`
- PB no-network task specification: `harness/suites/swe_polybench.py`
- Exported task-level behavior: scored `manifest.json` and Pi JSONL files under
  `results/runs/`
- Portfolio methodology: `docs/EVALS.md`
- Current campaign gates and paired evidence: `docs/PARETO-CAMPAIGN.md`
