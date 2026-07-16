# Benchmark Protection and Network Audit

Audit date: 2026-07-16

## Summary

| Suite / workflow | Agent filesystem | Agent network | Verifier network | Current status |
|---|---|---|---|---|
| Aider Polyglot | Empty-root Bubblewrap allowlist; only task/scaffold/runtime/cache/session paths | Selected model endpoint through a Unix-socket relay | None | **Protected (real boundary + end-to-end evidence)** |
| Terminal-Bench Core | Harbor hides `/tests` and `/solution` during the direct agent call | Selected model relay hostname only; explicit `main` Compose networking now fails closed | Public baseline | **Partial: safe for ordinary direct agent access, not yet a clean full-80 protocol** |
| SWE Atlas Q&A | Harbor-hidden tests/solution; solver daemons killed before verifier upload | Selected model relay hostname only | Pinned judge hostname only | **Protected in code; end-to-end judge run still required** |
| SWE Atlas Test Writing | Same direct-agent boundary and daemon cleanup | Selected model relay hostname only | Pinned judge hostname only | **Partial: model-authored tests execute inside the privileged verifier** |

## What network is actually required

### Aider Polyglot

Public network is not required while the model is acting or while its code is
verified.

1. Before agent launch, JavaScript, Java, and Rust dependency caches may be
   warmed with public package access.
2. During agent execution, only the selected model endpoint is reachable.
3. During verification, no network (including the model endpoint) is reachable.

The relay currently restricts host and port but not HTTP path. The selected
model endpoint and credential therefore remain part of the trusted computing
base. `bwrap` and `socat` are fail-closed runtime requirements. The real
Bubblewrap boundary test passes on this host after installing `socat`.

### Harbor setup shared by Terminal-Bench and SWE Atlas

The following public access happens before model-controlled code runs:

- pull/build task and Harbor egress-control images;
- `apt` installation of the installed-agent prerequisites;
- NVM/Node and pi or little-coder installation;
- optional dependency/image preparation owned by the task environment.

This setup access is acceptable for benchmark leakage isolation because the
model has not been invoked yet. It is still a supply-chain/reproducibility
surface and should eventually use pinned images/package caches.

During the solving phase, Harbor now receives a task-level `[agent]`
`network_mode = "allowlist"` policy and the same `--allow-agent-host`. Cospa
requires a dedicated relay **hostname**; IP literals are rejected because
Harbor host allowlists are not port-scoped and would expose every service on
that address. The relay hostname must resolve to an endpoint that serves only
the selected model route; merely assigning a hostname to a general host gateway
is not sufficient isolation.

### Terminal-Bench Core 0.1.1

A full clean run cannot currently be both faithful and model-host-only.
Terminal-Bench contains tasks whose intended solution requires public runtime
access, while many others install dependencies during the solving phase.
Inspection of the pinned 80-task checkout found:

- **27 official solutions** with agent-time package/download commands (`apt`,
  `pip`, `git clone`, `curl`, or `wget`);
- at least these externally dependent prompts:
  `count-dataset-tokens`, `download-youtube`, `eval-mteb`,
  `eval-mteb.hard`, `extract-moves-from-video`, `get-bitcoin-nodes`,
  `hf-model-inference`, `oom`, `solana-data`, and
  `super-benchmark-upet`;
- one task, `simple-web-scraper`, whose migrated `main` service declares an
  explicit Compose network. Harbor 0.16 respects that declaration, bypassing
  its egress sidecar. Cospa now detects and refuses this topology rather than
  claiming it is allowlisted.

The verifier is also currently public-networked. Harbor's migrated verifier
bootstrap downloads `uv`/pytest, and several task verifiers install extra
packages. More importantly, model-written code and any agent-started daemon
share that container. A real adversarial Harbor probe confirmed that `/tests`
and `/solution` are hidden during the direct agent call, but a background
watcher survives and sees `/tests` when Harbor uploads it for verification.
Terminal-Bench also has tasks that legitimately require persistent services,
so globally killing all post-agent processes would change benchmark semantics.

**Consequence:** the current policy prevents casual web/solution lookup during
agent turns, but the full 80-task score is not yet a clean protected score.
Before scaling, partition tasks into:

1. offline tasks whose images include all dependencies and whose verifier can
   run with no network;
2. task-local multi-service tasks whose services are routed through the egress
   sidecar without losing internal service discovery;
3. genuinely public-runtime tasks backed by a recorded/task-specific proxy or
   excluded from the protected headline score.

Package registries and GitHub cannot simply be added to the model allowlist:
GitHub also hosts the benchmark and reference solutions, and domain-only
allowlists cannot distinguish a required dependency from an answer lookup.
Prefetching immutable dependencies before agent launch is the preferred design.

### SWE Atlas pilot12

The pinned SWE Atlas images contain the checked-out repository and most task
dependencies, so the solver should require only the selected model endpoint.
Cospa now:

- applies a model-host-only `[agent]` policy;
- applies a judge-host-only `[verifier]` policy;
- forwards only the selected provider credential to the custom agent (not the
  judge key or unrelated provider/AWS credentials);
- mounts the same sanitized devstack profile used by Terminal-Bench;
- snapshots pre-agent container processes and kills solver-created processes
  before Harbor uploads hidden verifier files.

A Docker integration probe confirmed that the cleanup preserves baseline
container processes while killing a post-snapshot daemon. All 12 real pinned
tasks materialize, and a real Q&A task receives the expected model/judge phase
policies. A fresh scored run was not possible during this audit because no
container-reachable pinned judge endpoint was configured.

Two verifier dependencies still need preparation before a clean campaign:

- Q&A's fallback path may try to install `openai` from PyPI;
- the selected Paperless test-writing verifier runs `apt-get` for `libzbar0`.

Those dependencies should be baked/prefetched before verifier launch. With the
judge-only policy, an unexpected package download fails closed instead of
silently restoring public access.

The Q&A workflow does not execute model-authored repository code as its judge,
so process cleanup plus judge-only egress provides a credible boundary. The
Test Writing workflow is different: its verifier deliberately executes the
model-authored tests in the same verifier container that holds hidden rubrics,
mutation assets, and judge credentials. A malicious test can inspect `/tests`,
read process environments, or call the allowed judge endpoint. Killing daemons
before verifier upload does not solve code that the verifier intentionally
executes.

**Consequence:** do not promote SWE Atlas Test Writing scores to
"cheating-protected" until candidate tests run in a separate, unprivileged
namespace/container with no judge credentials and no hidden-rubric mount. The
trusted outer evaluator should retain the judge connection and consume only
sanitized candidate-test outputs.

## Changes made by this audit

- Added model-only agent and judge-only verifier policies to SWE Atlas.
- Removed unrelated provider, cloud, and judge credentials from Harbor agents.
- Restored SWE Atlas devstack profile mounts.
- Added SWE Atlas post-agent process cleanup.
- Refused Harbor tasks whose explicit `main` Compose network bypasses egress
  control.
- Refused model/judge IP-literal allowlists; dedicated hostnames are required.

## Evidence

- RED/GREEN tests cover each new boundary and credential rule.
- Full pytest: `237 passed`.
- Shell harness: `47 passed`.
- Real Aider Bubblewrap boundary: shared repositories/sessions and an unrelated
  HTTP listener were inaccessible; the selected model relay and trial writes
  worked.
- Real Terminal-Bench `hello-world`: Harbor built the egress sidecar, the model
  completed through the restricted phase, and the verifier ran. The trial
  failed one content assertion (missing newline), not infrastructure.
- Real migrated `simple-web-scraper`: rejected before agent launch because its
  explicit `main` network bypasses Harbor's sidecar.
- Real adversarial Harbor probe: direct agent access reported
  `tests=hidden`/`solution=hidden`, while a background watcher later reported
  `seen`; this is the evidence for Terminal-Bench's remaining verifier gap.
- Real Docker cleanup probe: `background_before=1 background_after=0`.
- Real pinned SWE Atlas Q&A task: materialized policy was agent
  `allowlist=[model-relay]`, verifier `allowlist=[judge.example]`.

## Launch decisions

- **Aider Polyglot:** reruns may proceed under the post-cutover boundary.
- **Terminal-Bench:** do not launch/interpret a protected full-80 campaign yet;
  first implement the offline/task-local/public-runtime partition and verifier
  isolation.
- **SWE Atlas Q&A:** run one judge-backed end-to-end smoke after dependency
  preflight, then promote if the artifacts confirm the policy.
- **SWE Atlas Test Writing:** keep experimental until candidate-code isolation
  is implemented.
