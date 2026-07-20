# SWE-bench-Live/MultiLang canary24

> **Status:** implemented and partially qualified. The pinned dataset,
> materializer, Harbor task, protected test channel, and strict scorer are wired.
> One C task has passed the gold verifier repeatedly and failed the clean
> baseline as expected. The other seven language strata and a real model run
> are still outstanding; do not freeze or run the proposed core48 matrix yet.

Cospa suite ID: `swe_bench_live_multilang_canary24`.

## Purpose

Aider Polyglot is now a useful multilingual competence gate but a poor primary
scaffold discriminator for strong models. This canary tests the replacement
protocol on newer, real repository issues while keeping normal repository tests
available during development and applying the resolving PR's evaluator tests
only after the agent exits.

This is a **cospa canary**, not the full 743-task SWE-bench-Live leaderboard
corpus. Twenty-four tasks have wide statistical uncertainty. Its immediate job
is to establish cost, reliability, isolation, and runtime before selecting a
48-task comparison core.

## Immutable inputs

| Input | Pin |
| --- | --- |
| Dataset | `SWE-bench-Live/MultiLang` |
| Dataset revision | `608f7ae9ab8ea1f9f0d030fe04562cf6bd1a0c8b` |
| Upstream evaluator reference | `microsoft/SWE-bench-Live` at `70ec57e852e3f2d195790fe71f553e272c691833` |
| Cospa manifest | `configs/swe_bench_live_multilang_canary24.json` |
| Cospa verifier policy | `hidden-pr-tests-strict-f2p-p2p-v1` |

`bash scripts/setup.sh` downloads the eight parquet splits from the immutable
Hugging Face revision, verifies each parquet SHA-256, extracts only the 24
selected rows, and validates a canonical SHA-256 for every complete row. The
runtime reads standard JSONL and therefore does not add a parquet dependency to
the harness environment. The extracted dataset remains under `vendor/` and is
not committed.

Every Docker image is recorded as both its source name and registry manifest
digest. Harbor receives `name@sha256:...`, never a mutable tag.

## Predeclared selection

The canary contains three tasks in each of C, C++, C#, Go, Java, JavaScript,
Rust, and TypeScript. Within every language it has one small (1–25 gold-patch
lines), one medium (26–100), and one large (101–500) task.

Selection used no candidate-model success data. Starting from tasks dated
March 2026 or later, it chose the newest eligible task in each language/size
bucket subject to:

- 24 distinct repositories;
- at most 50 declared fail-to-pass tests;
- at most 8,000 declared pass-to-pass tests;
- an accessible public Docker manifest; and
- at most 6 GiB of compressed image layers per task.

The 24 pinned images total **44.34 GiB compressed** before layer sharing. Image
pull time must therefore be treated as setup, not model wall time; pre-pull the
images before a measured run.

## Agent and verifier boundary

The generated Harbor task uses the pinned prebuilt repository image with
`/testbed` as its working directory.

1. Environment start and trusted agent installation may use public network.
2. During `agent.run()`, Harbor switches to an allowlist containing only the
   selected, container-reachable model relay hostname.
3. After the agent returns, the custom Harbor agent exports pi traces, Git
   status, and a `git diff HEAD --text` patch (including intent-to-add files) as
   durable artifacts.
4. Solver-created processes are killed before Harbor uploads `tests/`.
5. Harbor uploads the hidden PR test patch, command/parser metadata, and grader.
6. The verifier runs with `network_mode = "no-network"`, isolated Python mode,
   no user Python path, no shell startup files, and ignored system/global Git
   configuration.
7. The gold patch is stored only in Harbor's `solution/` channel and is exposed
   only to the Oracle agent.

The agent sees the issue statement, repository, and existing repository tests.
It does **not** see the PR test patch, expected test identities, parser, or gold
patch during its solving phase. An agent may write development tests, but those
tests are not independent grading evidence.

The network policy requires `CODING_EVAL_HARBOR_MODEL_BASE_URL` to use a
dedicated container-resolvable hostname. Loopback and IP-literal endpoints fail
closed for the same reason as Terminal-Bench: a hostname allowlist is not a
port- or HTTP-path allowlist.

## Scoring

The hidden grader applies the pinned PR test patch, executes the upstream
rebuild/test/print commands, and runs the pinned task-specific log parser. A
task passes only when:

- the fail-to-pass list is non-empty;
- every declared fail-to-pass test is observed and passing; and
- every declared pass-to-pass test is observed and passing.

Missing expected tests fail. This is deliberately stricter than the current
upstream implementation, which can overlook an absent pass-to-pass name. Cospa
results must therefore carry the cospa verifier-policy label rather than being
presented as byte-for-byte upstream leaderboard scores.

A parser/patch/runtime failure is marked `verifier_failed` so the runner treats
it as infrastructure rather than ordinary model quality. Manifests record the
dataset revision and row hash, evaluator commit/policy, language/patch bucket,
repository/base commit/date, and Docker name/digest/compressed size.

## Running the canary

First configure the same dedicated model relay used by other Harbor suites:

```bash
export CODING_EVAL_HARBOR_MODEL_BASE_URL=http://model-relay.internal:8000/v1
```

Then run one task, not the full matrix:

```bash
mamba run -n coding-eval python harness/runner.py \
  --suite swe_bench_live_multilang_canary24 \
  --adapter pi_vanilla \
  --model local/your-model \
  --problems 1 \
  --k 1 \
  --thinking high
```

The manifest order is language-stratified, beginning with the small C
`fluent/fluent-bit` task. Use a checked-in or reviewed `--tasks-file` when a
specific qualification task is required; do not interpret `--problems 1` as a
balanced result.

## Qualification evidence and remaining gate

Evidence collected on 2026-07-21:

- all 24 pinned rows passed revision, metadata, and complete-row hash checks;
- all 24 image manifests resolved and were pinned by digest;
- all 24 tasks materialized with hidden tests and gold solution in separate
  Harbor channels;
- `libarchive__libarchive-2968` passed three consecutive gold evaluations with
  1,740 parsed statuses and all 1 F2P plus 761 P2P identities present/passing;
- its no-op clean baseline scored zero because the F2P identity was absent;
- the hardened offline verifier then passed another gold run in 73 seconds.

This establishes `unit + real pinned artifact + one-language gold/baseline
end-to-end`, not full multilingual qualification. Before core48 selection:

1. run gold three times and a clean baseline for at least one task in each of
   the other seven languages;
2. complete one protected `pi_vanilla` model trial and audit the exported trace,
   patch, process cleanup, network boundary, and native evaluation;
3. measure cold image pull separately from warm agent/verifier wall time;
4. replace any flaky, network-dependent, resource-invalid, or parser-invalid
   task without consulting candidate-model success; and
5. only then freeze a predeclared core48 and run matched adapters.

See `docs/AIDER.md` for why this protocol replaces Aider Polyglot as the leading
scaffold-discrimination candidate and for comparison with other multilingual
benchmarks.
