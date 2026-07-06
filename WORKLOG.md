# WORKLOG — coding-eval

Append-only development log for the `coding-eval` repository.

## Convention

- **Append-only.** Never edit, reorder, or delete prior entries. Add new
  entries at the end of the file only.
- **One entry per logical unit of work** (a completed, validated change:
  feature, fix, refactor, doc update, audit finding resolution, etc.).
  Do not log exploratory, broken, or in-progress states.
- **Entry format:**
  ```
  ## YYYY-MM-DD — short summary (imperative, ≤ 72 chars)

  - What changed and why (non-obvious context only)
  - Evidence: test name, verification command, or run reference
  - Decision / rationale when relevant
  - Next action(s), if any
  ```
- **Commit with the unit.** When a logical unit is complete and committed,
  the WORKLOG entry for it is committed in the same commit (or the same
  small atomic group). Do not leave WORKLOG edits uncommitted across
  sessions.
- **Conflict resolution.** If two agents append concurrently, resolve by
  keeping both entries, ordering by timestamp; never drop a prior entry.
- **Scope.** This log tracks development of `coding-eval` only (harness,
  adapters, suites, scripts, viewer, docs, audits). Do not log routine
  rebaselining of `results/` or vendoring churn in `vendor/`.

## Entries

<!-- New entries go below this line. Do not edit above. -->

## 2026-07-04 — establish append-only WORKLOG.md and AGENTS.md convention

- Created `WORKLOG.md` at repo root as the append-only development log
  for `coding-eval` (this repo only; no org-level shared log).
- Wired the convention into `AGENTS.md`: added it to Key Files, to the
  During Work flow (append when a unit is validated), to Git Discipline
  (commit the append in the same atomic unit), and to the high-conflict
  file list. Added a new "WORKLOG Discipline" section.
- Format: `YYYY-MM-DD — short summary` prose entries with context /
  evidence / decision / next-action bullets.
- Enforcement: convention-only (no git hook, no CI guard). Upheld by
  review and commit discipline per AGENTS.md.
- Scope: logs `coding-eval` dev only; excludes routine `results/`
  rebaselining and `vendor/` churn.
- Next: first real entry will be the next validated logical unit.

## 2026-07-04 — add resume-skip and configurable --thinking/effort to runner

- Context: full-20260704 eval (4 live models x pi_vanilla/pi_devstack x 225
  aider_polyglot) was killed mid-run by a tmux-pane death (OOM/SIGHUP);
  rerunning would have wasted ~340 already-completed trials. Also, models
  ran at pi's per-model default thinking level, making cross-model and
  cross-effort comparisons uncontrolled.
- Changes:
  - `harness/runner.py`: `run_trial` now skips execution and returns the
    prior `(manifest, verdict)` when the trial dir already contains
    `verdict.json` (corrupt-file safe: falls through to re-run).
  - `harness/runner.py`: new `--thinking {off,minimal,low,medium,high,xhigh}`
    CLI flag, threaded into `task_data["thinking"]` and recorded as
    `manifest["sampling"]["thinking"]` ("default" when unset).
  - `harness/adapters/pi_vanilla.py`: emits `pi --thinking <level>` when
    `task_data["thinking"]` is set; omits the flag when unset.
- Evidence (RED -> GREEN):
  - `tests/test_resume_and_thinking.py` (new): 4 tests, all passing.
    RED confirmed before impl on all 3 behavioral tests; GREEN after.
  - Full suite: `mamba run -n coding-eval python -m pytest -q` = 104 passed.
  - Updated `tests/test_cli_paths.py` fake_run_trial signature to match.
- Decision: resume check lives in `run_trial` (not just `main()`) so direct
  callers get the same idempotency. `getattr(args, "thinking", None)` used
  in `main()` so hand-built Namespaces in tests don't need every flag.
- Next: relaunch ornith aider_polyglot/pi_vanilla under `nohup` (tmux-safe)
  to get a clean, complete signal at a pinned effort level.

## 2026-07-05 — propagate pinned thinking across comparable adapters

- Context: `--thinking` was recorded in runner manifests, but only
  `pi_vanilla` forwarded it to the underlying command. That made any
  `pi_devstack` or `little_coder` run with `--thinking high` look comparable
  in artifacts while still using provider defaults.
- Changes:
  - `pi_devstack`, `pi_superpowers`, `little_coder`, and
    `little_coder_superpowers` now append `--thinking <level>` when
    `task_data["thinking"]` is set.
  - `scripts/run-matrix.sh` accepts `--thinking <level>` and forwards it to
    each runner cell; `./run --help` now shows the pinned-thinking pattern.
  - Tests assert every comparable adapter forwards pinned thinking and that
    the matrix wrapper does not drop it.
- Evidence (RED -> GREEN):
  - RED: `tests/test_resume_and_thinking.py` failed on `pi_devstack` missing
    `--thinking`; `tests/scripts/test_run_matrix.sh` failed because
    `--thinking` was unknown.
  - GREEN: `mamba run -n coding-eval python -m pytest -q` = 105 passed.
  - GREEN: `bash tests/scripts/run_all.sh` = all shell tests passed
    (`test_check_models`, `test_root_entrypoints`, `test_run_matrix`,
    `test_setup`).
- Decision: include the superpowers adapters in the propagation test as well,
  since the runner manifest would otherwise label them with a pinned effort
  they did not actually request.
- Next: relaunch comparable cells one at a time with the same `--thinking`
  value and resume-enabled run id.

## 2026-07-05 — add verbose viewer status, filters, tokens, and cost

- Context: live Ornith runs need a quick terminal summary of completion
  status, timing, remaining work, and resource usage without opening the web
  UI or manually filtering smoke/probe artifacts.
- Changes:
  - `./view -v/--verbose` now shows status, completed/expected tasks,
    runtime, average task time, input/output tokens, estimated USD cost, and
    ETA.
  - `./view` hides smoke/probe runs by default, with `--all` to include them.
  - `--filter` and `--exclude` pattern matching operate over run, model,
    adapter, suite, task, and trial path text for table, JSON, and server
    defaults.
  - Score rows aggregate `token_usage` from manifests and estimate cost from
    manifest `model.cost`/`model.pricing` per-million-token prices when
    available.
- Evidence (RED -> GREEN):
  - RED: token/cost focused viewer tests failed on missing `prompt_tokens`
    and missing `Tok In` verbose column.
  - GREEN: `mamba run -n coding-eval python -m pytest -q tests/test_view_scores.py`
    = 18 passed.
  - GREEN: `mamba run -n coding-eval python -m pytest -q` = 110 passed.
  - GREEN: `bash tests/scripts/run_all.sh` = all shell tests passed
    (`test_check_models`, `test_root_entrypoints`, `test_run_matrix`,
    `test_setup`).
- Decision: costs remain best-effort and render as unknown when manifests do
  not carry direct cost or pricing metadata; token counts still aggregate when
  present.
- Next: consider recording provider pricing in runner manifests if we want
  cost estimates for all adapters rather than only artifacts that already
  include pricing metadata.

## 2026-07-05 — propagate pinned thinking through Harbor agents

- Context: `--thinking` now reached the direct pi/little-coder adapters, but
  Terminal-Bench runs bypass those adapters and execute custom Harbor agents
  inside task containers. That meant Harbor-backed results could still run at
  provider defaults while manifests recorded a pinned effort.
- Changes:
  - `run_trial()` now passes the configured `thinking` value into
    `TerminalBenchSuite.run_harbor_job()`.
  - `TerminalBenchSuite` exports pinned effort as both
    `CODING_EVAL_THINKING` and `CODING_EVAL_REASONING_EFFORT` in the Harbor
    subprocess environment.
  - Custom Harbor agents append `--thinking <level>` to pi/little-coder
    commands when the environment carries a pinned effort, and omit it when
    unset/default.
- Evidence (RED -> GREEN):
  - RED: new Terminal-Bench tests failed because `run_harbor_job()` rejected
    `thinking=`, Harbor agent commands omitted `--thinking high`, and runner
    delegated `None`.
  - GREEN: focused Harbor thinking tests passed.
  - GREEN: `mamba run -n coding-eval python -m pytest -q tests/test_terminal_bench.py tests/test_resume_and_thinking.py`
    = 21 passed.
  - GREEN: `mamba run -n coding-eval python -m pytest -q` = 114 passed.
  - GREEN: `bash tests/scripts/run_all.sh` = all shell tests passed
    (`test_check_models`, `test_root_entrypoints`, `test_run_matrix`,
    `test_setup`).
- Decision: keep the suite-to-agent contract environment-based because Harbor
  imports and instantiates the custom agent in a separate process/container
  boundary; the runner still records the comparable value in manifests.
- Next: Terminal-Bench estimates and runs can now use the same pinned effort
  as Aider Polyglot.

## 2026-07-05 — warn on malformed score artifacts

- Context: legacy malformed result paths with unencoded model/task segments
  were being interpreted as started tasks, which could make viewer rows look
  running or incomplete instead of surfacing a parsing problem.
- Changes:
  - The score viewer now validates parsed adapter and suite names before
    counting a started task, warns on malformed result paths, and exposes
    warnings in terminal, JSON stderr, `/api/warnings`, and the HTML view.
  - Started-task discovery now only treats `trial-N` leaf directories as
    runner trials, avoiding false warnings from trial-like cache directories
    inside workdirs.
  - Empty legacy malformed Ornith result trees were moved into
    `results-malformed-quarantine/` and that quarantine root is ignored by
    git; no result data was deleted.
  - Verified the token/cost columns are blank because existing manifests have
    empty `token_usage` and no pricing metadata, not because the viewer drops
    captured usage.
- Evidence (RED -> GREEN):
  - RED: malformed-result viewer tests failed on missing warning plumbing.
  - GREEN: focused malformed-result tests passed.
  - GREEN: `mamba run -n coding-eval python -m pytest -q` = 118 passed.
  - GREEN: `bash tests/scripts/run_all.sh` = all shell tests passed
    (`test_check_models`, `test_root_entrypoints`, `test_run_matrix`,
    `test_setup`).
- Decision: preserve malformed result artifacts in quarantine rather than
  deleting or counting them; a parsing warning is a harness-data issue, not a
  wrong model answer.
- Next: record structured token usage/pricing in runner manifests if pi or
  little-coder expose it through a machine-readable interface.

## 2026-07-05 — add devstack Superpowers adapter

- Context: the existing `pi_superpowers` arm is pi vanilla plus the
  Superpowers bench skill subset. For a clean `pi_devstack` comparison we need
  a distinct `pi_devstack_superpowers` arm rather than relabeling vanilla.
- Changes:
  - Added `pi_devstack_superpowers`, which preserves normal devstack extension
    discovery, disables default skill discovery, and loads only the
    non-interactive Superpowers bench skills.
  - Registered a distinct Terminal-Bench Harbor agent for the new adapter so
    Terminal-Bench does not collapse it to Harbor's built-in `pi` arm.
  - Updated runner help and architecture/result docs to name the new adapter.
- Evidence (RED -> GREEN):
  - RED: new superpowers and Terminal-Bench invariant tests failed because
    `pi_devstack_superpowers` was unknown and mapped to built-in `pi`.
  - GREEN: focused adapter, thinking, and Terminal-Bench mapping tests passed.
  - GREEN: `mamba run -n coding-eval python -m pytest -q` = 120 passed.
  - GREEN: `bash tests/scripts/run_all.sh` = all shell tests passed
    (`test_check_models`, `test_root_entrypoints`, `test_run_matrix`,
    `test_setup`).
- Decision: keep `pi_superpowers` as the existing vanilla+Superpowers arm and
  add a new explicit devstack+Superpowers arm to avoid changing historical
  semantics mid-run.
- Next: launch Ornith high `pi_devstack_superpowers` and
  `little_coder_superpowers` Aider Polyglot runs under the existing
  resume-enabled run id.

## 2026-07-05 — capture usage and model metadata

- Context: verbose score rows exposed token/cost columns, but existing
  manifests carried empty `token_usage` and no model pricing/limits, so
  cost/intelligence comparisons could not be computed.
- Changes:
  - Added telemetry helpers that resolve safe model metadata from pi
    `models.json` without copying provider secrets into manifests.
  - Runner manifests now record model limits/pricing, pinned thinking-token
    budget, and pi JSONL-derived input/output/cache/reasoning token usage,
    response metadata, and direct provider-reported cost when available.
  - pi-backed trials now copy the raw response trace to
    `out/pi_session.jsonl` so usage can be audited or backfilled.
  - Added `scripts/backfill-usage.py` to update existing result manifests
    from pi's session store without rerunning model trials.
  - Viewer verbose rows now aggregate cached/reasoning tokens, direct cost,
    cost per completed task, and passed tasks per dollar.
  - Updated README and result/plan docs with the telemetry contract.
- Evidence (RED -> GREEN):
  - RED: usage capture/backfill/viewer tests failed on missing telemetry
    modules or dropped cached/reasoning/cost fields.
  - GREEN: `mamba run -n coding-eval python -m pytest -q` = 127 passed.
  - GREEN: `bash tests/scripts/run_all.sh` = all shell tests passed
    (`test_check_models`, `test_root_entrypoints`, `test_run_matrix`,
    `test_setup`).
- Decision: use pi's per-workdir JSONL session trace as the durable source
  of truth for pi/little-coder usage, and store a manifest summary plus the
  raw trace copy rather than relying on an uncorrelated proxy analytics DB.
- Next: backfill the completed Ornith high Aider Polyglot runs and inspect
  the resulting verbose cost columns.

## 2026-07-05 — normalize backfill result paths

- Context: running `scripts/backfill-usage.py` with a relative
  `--results-dir` scanned manifests correctly but missed pi sessions because
  pi records absolute session `cwd` values.
- Changes:
  - `backfill_results()` now resolves the scan root before walking
    manifests, so trial workdir paths match pi's session metadata.
  - Added a regression test that invokes backfill from a relative
    `results/` path against an absolute pi session trace.
- Evidence (RED -> GREEN):
  - RED: relative-results backfill test failed with `observed == 0`.
  - GREEN: `mamba run -n coding-eval python -m pytest -q` = 128 passed.
- Decision: keep the fix in backfill rather than telemetry lookup so runner
  behavior for intentionally relative workdirs remains unchanged.
- Next: rerun backfill on the Ornith high result wrapper to replace
  unavailable placeholders with observed usage.

## 2026-07-05 — surface cost efficiency in default views

- Context: token/cost data was present after usage backfill, but the default
  terminal/browser score views still hid cost efficiency behind `-v` or JSON.
- Changes:
  - Default terminal and browser tables now show total cost, cost per
    completed task, and passed tasks per dollar.
  - Verbose terminal rows now keep input/output token counts and add input
    and output dollars-per-million pricing columns.
  - Score aggregation now exposes input/output/cache pricing fields from
    manifest model metadata.
  - Updated README and result docs to describe the new default/verbose table
    shapes.
- Evidence (RED -> GREEN):
  - RED: viewer tests failed on missing default cost columns, missing browser
    cost columns, and missing `$/M` verbose pricing fields.
  - GREEN: `mamba run -n coding-eval python -m pytest -q` = 130 passed.
  - GREEN: `bash tests/scripts/run_all.sh` = all shell tests passed
    (`test_check_models`, `test_root_entrypoints`, `test_run_matrix`,
    `test_setup`).
- Decision: keep default rows focused on cost efficiency only; detailed token
  and pricing columns stay behind `./view -v`.
- Next: rerun superpowers usage backfill after the live sequential run
  finishes so those rows get the same default cost columns.

## 2026-07-05 — guard partial cost ratios

- Context: the live `pi_devstack_superpowers` runner was started before
  telemetry capture landed, so new verdicts appeared faster than usage
  backfill. The viewer summed cost from observed manifests but divided by all
  completed tasks, temporarily making `$ /Task` and `Pass/$` look too good.
- Changes:
  - Score aggregation now tracks completed trials and costed trials per row.
  - `$ /Task` and `Pass/$` are shown only when every completed trial in the
    row has cost coverage.
  - Verbose score rows now show `Costed` coverage so partial/pre-patch rows
    are obvious.
- Evidence (RED -> GREEN):
  - RED: viewer tests reproduced a row with 1 costed trial out of 2 completed
    trials and still-computed ratios.
  - GREEN: `mamba run -n coding-eval python -m pytest -q` = 131 passed.
  - GREEN: `bash tests/scripts/run_all.sh` = all shell tests passed
    (`test_check_models`, `test_root_entrypoints`, `test_run_matrix`,
    `test_setup`).
- Decision: keep total `Cost` visible even when partial, but suppress derived
  efficiency ratios until cost coverage is complete.
- Next: continue using `scripts/backfill-usage.py --filter superpowers` to
  catch up the pre-patch live run, or wait and run it once after completion.

## 2026-07-05 — make all-results usage backfill safe

- Context: a full `scripts/backfill-usage.py --results-dir results` scan
  crashed on a nested Harbor artifact named `manifest.json` that was not a
  runner trial manifest.
- Changes:
  - Backfill discovery now only scans runner trial manifests at
    `trial-N/manifest.json`.
  - `backfill_manifest()` now reports non-object runner manifests as errors
    instead of raising an `AttributeError`.
  - Added regression coverage for nested non-trial manifests under
    `trial-N/jobs/.../manifest.json`.
- Evidence (RED -> GREEN):
  - RED: full-scan regression test crashed on a list-shaped nested manifest.
  - GREEN: `mamba run -n coding-eval python -m pytest -q` = 132 passed.
  - GREEN: `bash tests/scripts/run_all.sh` = all shell tests passed
    (`test_check_models`, `test_root_entrypoints`, `test_run_matrix`,
    `test_setup`).
- Decision: scope backfill to durable runner artifacts, not arbitrary
  benchmark/container manifests that may exist inside trial job directories.
- Next: run the unfiltered backfill over `results/` to catch every available
  pi-backed trial.

## 2026-07-05 — record official GLM-5.2 pricing

- Context: the local `zai/glm-5.2` pi provider entry carried zero token
  prices, which would make cost/intelligence rows wrong even when usage
  capture was complete.
- Changes:
  - `configs/models.yaml` now records the official Z.ai GLM-5.2 limits and
    per-million-token prices: input 1.4, cached input 0.26, cache storage 0,
    and output 4.4 USD.
  - `load_model_metadata()` now merges optional repo model metadata over local
    pi provider metadata, so manifests/backfill can correct incomplete local
    accounting stubs without exposing provider secrets.
  - README and PLAN docs now describe repo-backed model accounting metadata.
- Evidence (RED -> GREEN):
  - RED: metadata test failed because `load_model_metadata()` could not read
    repo model pricing and returned the zero-priced provider stub.
  - GREEN: `mamba run -n coding-eval python -m pytest -q` = 133 passed.
  - GREEN: `bash tests/scripts/run_all.sh` = all shell tests passed
    (`test_check_models`, `test_root_entrypoints`, `test_run_matrix`,
    `test_setup`).
- Decision: keep provider routing/auth in `~/.pi/agent/models.json`, but keep
  benchmark accounting metadata in the repo so results are reproducible.
- Next: add Harbor artifact export for Terminal-Bench pi session traces so
  Terminal-Bench rows can receive the same token/cost coverage.

## 2026-07-05 — capture Terminal-Bench usage traces

- Context: Terminal-Bench executes agents inside Harbor/container
  environments, so host-side `~/.pi/agent/sessions` lookup cannot recover
  token/cost usage for real Terminal-Bench runs by itself.
- Changes:
  - Custom Harbor agents now wrap pi/little-coder execution and copy
    `$HOME/.pi/agent/sessions/**/*.jsonl` into
    `/logs/artifacts/pi-sessions` after each trial.
  - Telemetry can summarize Harbor-exported pi JSONL artifacts, preserve the
    raw trace under `out/`, and combine multiple exported traces if present.
  - Runner and usage backfill now try Harbor job artifacts for
    `terminal_bench` trials before falling back to host workdir sessions.
  - README and PLAN docs now describe the Terminal-Bench trace export path.
- Evidence (RED -> GREEN):
  - RED: new tests failed because Harbor agent commands did not export
    sessions, runner manifests stayed empty after fake Harbor traces, and
    backfill reported Harbor artifact traces as unavailable.
  - GREEN: `mamba run -n coding-eval python -m pytest -q` = 137 passed.
  - GREEN: `bash tests/scripts/run_all.sh` = all shell tests passed
    (`test_check_models`, `test_root_entrypoints`, `test_run_matrix`,
    `test_setup`).
- Decision: keep `out/pi_session.jsonl` as the normalized durable trace path
  while treating Harbor `jobs/**/artifacts/pi-sessions/*.jsonl` as the
  container export source.
- Next: run a real Terminal-Bench probe before scaling the full suite and
  confirm its verbose score row has complete `Costed` coverage.

## 2026-07-05 — fix zero-cost usage estimates

- Context: GLM-5.2 traces carried observed tokens but direct provider cost
  values of zero, so the viewer treated the row as free instead of estimating
  cost from repo pricing. Rows with pricing metadata but no usage also showed
  as fully costed.
- Changes:
  - Viewer cost estimation now falls back to token pricing when direct usage
    cost is zero and token counts are present.
  - Pricing metadata alone no longer marks a trial as costed when no usage
    tokens or positive direct cost were observed.
  - Added regression coverage for both GLM-style zero direct cost and
    Terminal-Bench-style pricing-only smoke rows.
- Evidence (RED -> GREEN):
  - RED: new viewer tests reproduced `$0` GLM costs and `Costed 1/1` for a
    pricing-only row with no tokens.
  - GREEN: `mamba run -n coding-eval python -m pytest -q` = 139 passed.
  - GREEN: `bash tests/scripts/run_all.sh` = all shell tests passed
    (`test_check_models`, `test_root_entrypoints`, `test_run_matrix`,
    `test_setup`).
- Decision: zero-cost pricing remains valid for genuinely free models with
  observed tokens; missing usage remains unknown, not zero.
- Next: add first-class run grouping or run-id display so historical probes
  and reruns do not contaminate model/adapter/suite cost comparisons.

## 2026-07-05 — cache score view aggregation

- Context: `./view --verbose` spent most of its time recursively walking the
  full `results/` tree, including trial `workdir/`, `out/`, and Harbor `jobs/`
  subtrees. A cProfile run showed ~13 seconds in `Path.rglob("trial-*")`.
- Changes:
  - Score scanning now uses a pruned `os.walk()` that yields `trial-N`
    directories and does not descend into their child artifacts.
  - `get_scores()` now persists score rows and warnings in
    `.cache/view-scores.json`, keyed by result directory, filter options, and
    manifest/verdict mtime+size signatures.
  - Added `./view --no-cache` for debugging cold scans.
  - `.cache/` is ignored by git.
- Evidence (RED -> GREEN):
  - RED: cache-reuse and scanner-pruning tests failed because cache hits still
    reparsed trial JSON and nested `workdir/.../trial-*` paths were scanned.
  - GREEN: focused cache/scanner tests passed.
  - GREEN: `mamba run -n coding-eval python -m pytest -q` = 142 passed.
  - GREEN: `bash tests/scripts/run_all.sh` = all shell tests passed
    (`test_check_models`, `test_root_entrypoints`, `test_run_matrix`,
    `test_setup`).
  - Local timing after the fix: cold no-cache view ~0.40s, cache build ~0.28s,
    cache hit ~0.18s.
- Decision: cache the aggregated score rows, not formatted terminal output, so
  table/json/browser views can share the same invalidation behavior.
- Next: add first-class run grouping or run-id display so historical probes
  and reruns do not contaminate model/adapter/suite cost comparisons.

## 2026-07-05 — persist verifier crash verdicts

- Context: two `pi_devstack_superpowers` trials had workdir/log output but no
  `manifest.json` or `verdict.json`, leaving the row at `223/225`. The agent
  had moved/renamed the workdir, causing verification to escape before durable
  artifacts were written.
- Changes:
  - `run_trial()` now catches suite verifier exceptions and records a failed
    verdict with `verifier_failed: true` plus a manifest error instead of
    leaving an incomplete trial directory.
  - Added regression coverage for verifier exceptions after adapter success.
  - Re-ran the two incomplete `cpp/grade-school` and `cpp/sublist`
    `pi_devstack_superpowers` trials under `ornith-high-20260704`, then
    backfilled usage.
- Evidence (RED -> GREEN):
  - RED: the verifier-exception test raised `FileNotFoundError` and wrote no
    artifacts.
  - GREEN: `mamba run -n coding-eval python -m pytest tests/test_runner_failure.py -q`
    = 3 passed.
  - Operational check: `./view -v --filter ornith-high-20260704 --no-cache`
    now shows `pi_devstack_superpowers` as complete with `91/225` and
    `Costed 225/225`.
- Decision: verifier crashes are scored as failed trials, not pending trials,
  because the adapter already returned control to the harness.
- Next: expose a small `./view` diagnostic for incomplete trial dirs if this
  comes up again during long live runs.

## 2026-07-05 — skip generated polyglot artifacts

- Context: a `codex/gpt-5.5` high-thinking smoke exposed a false C++ failure:
  the vendored `bank-account/build/CMakeCache.txt` was copied into the trial
  workdir and still pointed at the vendor source directory.
- Changes:
  - `AiderPolyglotSuite.materialize_task()` now skips top-level generated
    artifact directories such as `build`, `target`, `node_modules`, and common
    cache dirs when copying a problem into a fresh workdir.
  - Added regression coverage that fails when a stale vendored `build/`
    directory reaches the workdir.
- Evidence (RED -> GREEN):
  - RED: `test_materialize_task_skips_generated_build_artifacts` copied
    `build/` into the workdir.
  - GREEN: `mamba run -n coding-eval python -m pytest tests/test_aider_polyglot.py -q`
    = 14 passed.
  - GREEN: `mamba run -n coding-eval python -m pytest -q` = 144 passed.
  - GREEN: `bash tests/scripts/run_all.sh` = all shell tests passed.
- Decision: keep the vendor tree intact and make materialization robust to
  dirty external datasets.
- Next: rerun the `codex/gpt-5.5` high smoke after the fix so the score is not
  polluted by stale CMake state.

## 2026-07-05 — require complete artifacts for resume

- Context: a killed GLM/little_coder run left a partial trial with
  `verdict.json` but no `manifest.json`. The resume check skipped on verdict
  alone, so such a trial could stay unrepairable and break timing/cost views.
- Changes:
  - `run_trial()` now resumes only when both `verdict.json` and
    `manifest.json` are present and readable.
  - Partial or corrupt artifact sets are reported and rerun.
  - Added regression coverage for the verdict-without-manifest case.
- Evidence (RED -> GREEN):
  - RED: `test_run_trial_reruns_when_manifest_missing` skipped a
    verdict-only trial and left `run_count=1`.
  - GREEN: `mamba run -n coding-eval python -m pytest tests/test_resume_and_thinking.py -q`
    = 6 passed.
- Decision: treat missing manifest as incomplete work, even when a verdict
  exists, because the manifest carries timing, model, sampling, and usage data
  required for aggregation.
- Next: resume affected GLM jobs after confirming no live process owns the same
  run directory.

## 2026-07-05 — price GPT-5.5 at API-equivalent rates

- Context: the local `codex/gpt-5.5` provider reports zero-cost subscription
  usage, but benchmark cost/intelligence comparisons should use direct API
  equivalent pricing.
- Changes:
  - Added `codex/gpt-5.5` model metadata with OpenAI Standard API rates:
    short-context `$5/$0.50/$30` per 1M input/cached/output tokens and
    long-context `$10/$1/$45` above `272K` input tokens.
  - Preserved long-context pricing fields in safe model metadata.
  - Updated score estimation to choose long-context rates per trial and bill
    reasoning tokens as output tokens.
  - Backfilled existing GPT-5.5 smoke manifests so `./view` reports cost.
- Evidence (RED -> GREEN):
  - RED: long-context pricing fields were dropped from metadata and
    long-context trials were charged at short-context rates.
  - RED: reasoning-token cost test charged only visible output tokens.
  - GREEN: pricing-focused tests passed.
  - GREEN: `mamba run -n coding-eval python -m pytest -q` = 148 passed.
  - GREEN: `bash tests/scripts/run_all.sh` = all shell tests passed.
  - Operational check: clean GPT-5.5 smoke now shows `$1.32` total cost,
    `$0.2648/task`, and `3.78 pass/$`.
- Decision: leave `~/.pi/agent/models.json` unchanged because it contains
  provider credentials and subscription-local stubs; repo config is the
  benchmark pricing source of truth.
- Next: use the same tier-aware path for any future model with context-based
  API pricing.

## 2026-07-06 — price Qwen 3.6 27B

- Context: cost/intelligence comparisons need API-equivalent pricing for
  `aiand/qwen/qwen3.6-27b`.
- Changes:
  - Added Qwen 3.6 27B pricing to `configs/models.yaml`: `$0.30/M` input,
    `$0.15/M` cached input, and `$2.40/M` output.
  - Added a metadata regression test that ensures repo pricing overrides a
    zero-cost provider stub.
- Evidence (RED -> GREEN):
  - RED: `test_load_model_metadata_has_qwen_36_repo_pricing` loaded zero-cost
    provider pricing because the repo config had no Qwen cost metadata.
  - GREEN: `mamba run -n coding-eval python -m pytest tests/test_usage_capture.py -q`
    = 8 passed.
  - GREEN: `mamba run -n coding-eval python -m pytest -q` = 149 passed.
  - GREEN: `bash tests/scripts/run_all.sh` = all shell tests passed.
- Decision: keep pricing in repo config as the benchmark source of truth.
- Next: backfill existing Qwen manifests if/when Qwen eval runs produce
  observed token usage.

## 2026-07-06 — track runner liveness and clean child groups

- Context: stale result rows were shown as `running` because the viewer inferred
  liveness from incomplete trial directories. Separately, adapter/verifier
  subprocesses could leave orphaned `pi`, `npm`, `cargo`, or browser children
  after timeout or runner termination.
- Changes:
  - Added cell-level `.runner-heartbeat.json` files with pid, host, state,
    current task/trial, and progress counters.
  - Updated `./view -v` aggregation to use fresh heartbeats or live runner
    process fallback, and to report stale incomplete rows as `stalled`.
  - Added bounded infrastructure retries via `run_trial_with_retries()` while
    preserving wrong answers as single-attempt benchmark signal.
  - Added `run_command()` process-group cleanup and routed adapters plus suite
    verifier/Harbor subprocesses through it.
- Evidence (RED -> GREEN):
  - RED: stale incomplete trials were reported as `running`; retry and
    process-group cleanup entrypoints were missing.
  - GREEN: targeted liveness/retry/cleanup tests passed.
  - GREEN: `mamba run -n coding-eval python -m pytest -q` = 155 passed.
  - GREEN: `bash tests/scripts/run_all.sh` = all shell tests passed.
  - Operational check: cached-disabled `./view -v --all --filter
    'glm-5.2|qwen3.6' --no-cache` shows live Qwen rows as `running` and dead
    GLM rows as `stalled`.
- Decision: use explicit heartbeats as the primary liveness signal and `/proc`
  scanning only as a compatibility fallback for pre-heartbeat runners.
- Next: resume stalled GLM runs under the new runner and clean orphaned
  subprocesses that no live runner owns.

## 2026-07-06 — price results from repo rates at read time

- Context: score costs depended on pi/little-coder session pricing from
  `~/.pi/agent/models.json`, so the same token counts could get different
  costs depending on the harness or local provider config.
- Changes:
  - `./view` now prices from repo `configs/models.yaml` rates first and uses
    pi-reported `token_usage.cost_usd` only as a fallback when no rates exist.
  - Added `--pricing-profile` support for named `cost_profiles` so old/new
    price views can be selected without rewriting result manifests.
  - Added repo cost entries for Ornith, Nemotron, and Stepfun.
  - Preserved pi-computed session cost as `token_usage.cost_usd_pi` for audit.
  - Included pricing config signature and selected profile in the viewer cache
    key, so YAML price edits invalidate cached score rows.
- Evidence (RED -> GREEN):
  - RED: repo pricing did not override positive pi `cost_usd`, named pricing
    profiles were unsupported, and pi cost was not preserved as
    `cost_usd_pi`.
  - GREEN: pricing/telemetry-focused tests passed.
  - GREEN: `mamba run -n coding-eval python -m pytest -q` = 159 passed.
  - GREEN: `bash tests/scripts/run_all.sh` = all shell tests passed.
  - Operational check: cached-disabled `./view -v --all --filter
    'ornith|qwen3.6|glm-5.2|nemotron|stepfun' --no-cache` reprices existing
    manifests from repo rates without backfill.
- Decision: keep `configs/models.yaml` as the single canonical rate table.
  Manifests store raw usage and audit costs; score views compute opportunity
  cost at read time.
- Next: add named `cost_profiles` to `configs/models.yaml` when we need to
  compare historical/current price schedules.

## 2026-07-06 — preserve OpenAI reasoning effort as symbolic

- Context: `codex/gpt-5.5` manifests recorded `thinking_token_budget: 8192`
  for `--thinking high`, which implied a benchmark-local token cap instead of
  OpenAI's symbolic reasoning-effort setting.
- Changes:
  - Added `reasoning_effort_source: openai` to the GPT-5.5 model metadata.
  - Centralized thinking/effort sampling metadata in `harness.telemetry`.
  - Runtime manifests now record Codex/OpenAI thinking as
    `reasoning_effort` plus `reasoning_effort_source: openai`.
  - Usage backfill removes stale local `thinking_token_budget` fields for
    Codex/OpenAI manifests instead of re-adding them.
- Evidence (RED -> GREEN):
  - RED: Codex runtime/backfill tests failed because `reasoning_effort` was
    absent and local numeric budgets were retained.
  - GREEN: focused Codex runtime/backfill tests passed.
  - GREEN: `mamba run -n coding-eval python -m pytest -q` = 161 passed.
  - GREEN: `bash tests/scripts/run_all.sh` = all shell tests passed.
- Decision: keep numeric `thinking_token_budget` only for non-OpenAI models
  where cospa owns the local effort-to-budget mapping.
- Next: run usage backfill on GPT-5.5 smoke manifests if we want the old
  smoke artifacts normalized in place.
