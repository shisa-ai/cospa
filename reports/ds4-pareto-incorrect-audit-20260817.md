# DS4 Pareto baseline + stability32 — incorrect-verdict audit

Generated 2026-08-17. Goal: confirm every "incorrect" verdict in the
`ds4-pareto-baseline-k1-and-stability32` report is a *genuine* wrong answer,
and classify how/why each failed. All verdicts were read from `verdict.json`
(grader output) plus `manifest.json` (exit code / error / budget) at the
canonical DS4 baseline roots; Harbor suites additionally cross-checked against
`jobs/*/verifier/*` artifacts.

## Bottom line

- **247 of 249** reported failures are genuine incorrect answers (real test /
  build / patch / graded-check failures).
- **2 are mislabeled**: both are featurebench trials that are NOT wrong
  answers — one agent timeout (3600 s) and one agent-launcher command failure.
  **Both were backfilled on 2026-08-17** (`scripts/backfill-harbor-verdicts.py`)
  from Harbor job evidence: `pytorch-lightning…lv1` → `budget_exhausted`
  (exit 124), `sympy…lv1` → `connection_error`.
- **5 more** failures are correctly-labeled `budget_exhausted` (agent timeout),
  which the report's pass-rate denominator includes but are not "incorrect".
- The report's **pareto60 22/60 row is stale**: it reflects the pre-sweep
  "original hermetic143-subset high sample". The current canonical high
  baseline is **19/60** (effort-high, `abe74d8`).
- No provider/verifier infrastructure failure is hidden inside any "incorrect"
  verdict: BCB verifiers ran clean (exit 0, upstream `fail` = pass@1 0);
  multiswe/polybench verifiers ran or rejected the patch deterministically;
  terminal verifiers scored reward 0.0 with no exception.

## Per-cell classification

### bigcodebench_hard_agentic_pareto60 — 19/60 (41 failed)
- 41 × **HIDDEN-TEST-FAIL (pass@1=0.000)** — genuine. Every failed trial has a
  substantive `solution.py` (no empty/stub/refusal); upstream verifier ran with
  exit 0 and scored 0. The scorer does not expose per-test detail, so the why is
  "generated code fails the hidden BigCodeBench-Hard tests".

### bigcodebench_hard_instruct_hermetic143 — 17/143 (126 failed)
- 126 × **HIDDEN-TEST-FAIL (pass@1=0.000)** — genuine. All 126 have substantive
  raw completions (none empty/refusal); sanitizer+scorer ran cleanly.

### multi_swe_bench_flash_hermetic25 — 9/25 (16 failed)
- 9 × **PATCH-FAILED-TO-APPLY** — genuine. Agent produced a patch (3525 B – 1.19 MB)
  that does not apply to the base commit: `catchorg/Catch2-2187`,
  `clap-rs/clap-5298`, `cli/cli-1642`, `cli/cli-2263`, `cli/cli-352`,
  `iamkun/dayjs-1953`, `jqlang/jq-1793`, `mui/material-ui-23778`,
  `simdjson/simdjson-545`. (Some patches are pathologically large — Catch2
  1.19 MB — indicating appended junk.)
- 6 × **TEST-FAILURES** — genuine failed transitions: `anuraghazra-2228` (5),
  `anuraghazra-99` (2), `cli-696` (4), `darkreader-6747` (5), `dayjs-668` (10),
  `jq-2821` (1).
- 1 × **budget_exhausted** — `nlohmann/json-609` (1800 s agent timeout,
  correctly labeled).

### terminal_bench_core_pareto20 — 11/20 (9 failed)
- 7 × **VERIFIER-REWARD=0.0** — genuine graded-check failures (verifier ran, no
  exception): `build-tcc-qemu` (expect-script produced no expected output →
  verifier IndexError on missing `echo $?`), `cron-broken-network` (curl content
  match 2/46 lines), `csv-to-parquet` (produced parquet unreadable:
  "Couldn't deserialize thrift"), `crack-7z-hash.easy`, `extract-moves-from-video`,
  `modernize-fortran-build`, `sqlite-with-gcov`.
- 2 × **budget_exhausted** — `raman-fitting` (360 s), `train-fasttext` (600 s),
  correctly labeled.

### swe_polybench_verified_balanced64 — 15/64 (49 failed)
- 18 × **PATCH-FAILED-TO-APPLY** — genuine (incl. `rocketmq-7655`, `code-server-4923/-6278`,
  `gson-2158/-2337`, `guava-5696`, `transformers-*`, `langchain-19331`, `mui-14882`, …).
- 5 × **BUILD/COMPILE-ERROR** — patch applied but build fails
  (`MojoFailureException`/Maven reactor error): `rocketmq-7563`, `apollo-4207`,
  `apollo-4464`, `gson-2167`, `guava-3971`.
- 24 × **TEST-FAILURES** (1–657 tests) — genuine, incl. `vscode-189223` (16),
  `mui-17301` (11), `svelte-4454` (7), `svelte-630` (657, essentially total
  failure).
- 2 × **budget_exhausted** — `apollo-4568`, `prettier-9850` (1800 s), correctly labeled.

### featurebench_lite_pareto12 — 2/12 (10 failed)
- 8 × **TEST-FAILURES** — genuine pytest failures (1–35 failing tests):
  astropy/test_table (33), sphinx/test_domain_c (35), seaborn/test_regression (25),
  pandas/test_concat (10), transformers/test_serve (8), xarray/test_backends_chunks (2),
  seaborn/test_algorithms (1), pydantic/test_deprecated_fields (1).
- 1 × **AGENT-TIMEOUT → budget_exhausted (backfilled 2026-08-17)** —
  `pytorch-lightning...lv1`: `AgentTimeoutError` after 3600 s (wall 3641 s).
  This is a Harbor agent capability-budget outcome, **not a wrong answer**.
  Pre-`531d457` runs recorded it as a generic adapter failure; the backfill
  derived `budget_exhausted` / exit 124 from the job evidence.
- 1 × **ADAPTER-ERROR → connection_error (backfilled 2026-08-17)** —
  `sympy...test_nullspace...lv1`: `NonZeroAgentExitCodeError: Command failed (exit 1)`
  with `stdout: Connection error.`. The pi session **did** run (three 340–556 KB
  session files) but could not reach the model endpoint from inside the task
  container — a provider connectivity failure, not a wrong answer and not an
  agent-launcher bug. (A separate sympy-repair run then reached real tests.)

### featurebench_lite_pareto12 (sympy-repair) — 0/1
- 1 × **TEST-FAILURES(16)** — genuine: sympy `test_nullspace` suite, 16 failing
  assertions. The repair run got past the launcher error to actual grading.

### swe_explore_verified12 — 10/12 resolved (9.7% weighted-core)
- 2 × **INVALID-OUTPUT** — genuine agent output-format failures: regions
  out of bounds (`seaborn/_core/plot.py` end 1666 > 1649; `sphinx/ext/napoleon`
  end > 463). Not "wrong code" but invalid diagnostic output.

## Stability32 (k=3, pass@2/3 majority) — report rows reconciled

| Cell | Report | Majority | Notes |
|---|---|---|---|
| pareto60 | 2/8 | 2/8 | BigCodeBench/162, 999 pass; /637 mixed P-F-P |
| featurebench | 0/4 | 0/4 | all fail; pytorch-lightning timeout in 2/3 trials |
| multiswe | 1/7 | 1/7 | gson-1555 pass; tokio-547 was baseline-pass → stab-fail (noise) |
| polybench | 0/8 | 0/8 | langchain-4646 baseline-pass → stab-fail; serverless-6827 1/3 |
| terminal | 2/5 | 2/5 | blind-maze, tmux pass; grid-pattern baseline-pass → stab-fail |

Three baseline-pass → stab-fail flips (tokio-547, grid-pattern, langchain-4646)
are within the k=1 repeat-noise band already bounded by the 22-vs-19 agreement
(53/60); none is a verifier or infra artifact.

## HTTP / provider health

DS4 baseline `pi_session.jsonl` traces contain no provider status field; the
embedded 429/500/503 strings are agent text/tool output, not responses. No
manifest carries a provider error, and all failures are explained by verifier
output. No evidence of provider-side contamination of any "incorrect" verdict.

## Related finding (audit-failures classifier) — fixed 2026-08-17

The single `auth_forbidden` hit (spark `cli__cli-2263`) was a **classifier false
positive**: the grader output contains gh-cli's literal test name
`Test_detectDeviceFlow/403_forbidden` and the `internal/authflow` package path.
The real failure is a Go build/vet error (genuine incorrect); the substring
rule `403`/`forbidden` in `classify_failure` tripped on task output.

**Resolution**: classification moved to `harness/failure_classify.py`.
Provider/adapter substring rules now read only the *manifest* error surface
(cleaned to the `stdout:` tail); task/test output and the embedded agent
command never feed them. This also fixed the sympy trial, whose manifest
`error` embeds the task prompt (the "forbidden" black_links prose) and would
otherwise have misclassified as `auth_forbidden` instead of `connection_error`.
The audit now reports the featurebench cell as
`{incorrect: 8, connection_error: 1, budget_exhausted: 1}`.

Note: DS4 fails the same task as a plain `incorrect` with no such surface; no
score change was warranted for any trial.
