# WORKLOG — cospa

Append-only development log for the `cospa` repository.

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
- **Scope.** This log tracks development of `cospa` only (harness,
  adapters, suites, scripts, viewer, docs, audits). Do not log routine
  rebaselining of `results/` or vendoring churn in `vendor/`.

## Entries

<!-- New entries go below this line. Do not edit above. -->

## 2026-07-04 — establish append-only WORKLOG.md and AGENTS.md convention

- Created `WORKLOG.md` at repo root as the append-only development log
  for `cospa` (this repo only; no org-level shared log).
- Wired the convention into `AGENTS.md`: added it to Key Files, to the
  During Work flow (append when a unit is validated), to Git Discipline
  (commit the append in the same atomic unit), and to the high-conflict
  file list. Added a new "WORKLOG Discipline" section.
- Format: `YYYY-MM-DD — short summary` prose entries with context /
  evidence / decision / next-action bullets.
- Enforcement: convention-only (no git hook, no CI guard). Upheld by
  review and commit discipline per AGENTS.md.
- Scope: logs `cospa` dev only; excludes routine `results/`
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
  - Full suite: `mamba run -n cospa python -m pytest -q` = 104 passed.
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
  - GREEN: `mamba run -n cospa python -m pytest -q` = 105 passed.
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
  - GREEN: `mamba run -n cospa python -m pytest -q tests/test_view_scores.py`
    = 18 passed.
  - GREEN: `mamba run -n cospa python -m pytest -q` = 110 passed.
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
  - GREEN: `mamba run -n cospa python -m pytest -q tests/test_terminal_bench.py tests/test_resume_and_thinking.py`
    = 21 passed.
  - GREEN: `mamba run -n cospa python -m pytest -q` = 114 passed.
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
  - GREEN: `mamba run -n cospa python -m pytest -q` = 118 passed.
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
  - GREEN: `mamba run -n cospa python -m pytest -q` = 120 passed.
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
  - GREEN: `mamba run -n cospa python -m pytest -q` = 127 passed.
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
  - GREEN: `mamba run -n cospa python -m pytest -q` = 128 passed.
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
  - GREEN: `mamba run -n cospa python -m pytest -q` = 130 passed.
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
  - GREEN: `mamba run -n cospa python -m pytest -q` = 131 passed.
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
  - GREEN: `mamba run -n cospa python -m pytest -q` = 132 passed.
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
  - GREEN: `mamba run -n cospa python -m pytest -q` = 133 passed.
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
  - GREEN: `mamba run -n cospa python -m pytest -q` = 137 passed.
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
  - GREEN: `mamba run -n cospa python -m pytest -q` = 139 passed.
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
  - GREEN: `mamba run -n cospa python -m pytest -q` = 142 passed.
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
  - GREEN: `mamba run -n cospa python -m pytest tests/test_runner_failure.py -q`
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
  - GREEN: `mamba run -n cospa python -m pytest tests/test_aider_polyglot.py -q`
    = 14 passed.
  - GREEN: `mamba run -n cospa python -m pytest -q` = 144 passed.
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
  - GREEN: `mamba run -n cospa python -m pytest tests/test_resume_and_thinking.py -q`
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
  - GREEN: `mamba run -n cospa python -m pytest -q` = 148 passed.
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
  - GREEN: `mamba run -n cospa python -m pytest tests/test_usage_capture.py -q`
    = 8 passed.
  - GREEN: `mamba run -n cospa python -m pytest -q` = 149 passed.
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
  - GREEN: `mamba run -n cospa python -m pytest -q` = 155 passed.
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
  - GREEN: `mamba run -n cospa python -m pytest -q` = 159 passed.
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
  - GREEN: `mamba run -n cospa python -m pytest -q` = 161 passed.
  - GREEN: `bash tests/scripts/run_all.sh` = all shell tests passed.
- Decision: keep numeric `thinking_token_budget` only for non-OpenAI models
  where cospa owns the local effort-to-budget mapping.
- Next: run usage backfill on GPT-5.5 smoke manifests if we want the old
  smoke artifacts normalized in place.

## 2026-07-06 — suppress empty malformed trial-shell warnings

- Context: `./view --verbose --no-cache` warned about legacy unencoded Qwen
  trial paths that contained only `workdir/` and no durable manifest/verdict
  artifacts. These empty shells were noise, not substantive result parse
  failures.
- Changes:
  - Viewer path validation now warns on malformed result paths only when the
    trial directory contains `manifest.json` or `verdict.json`.
  - Empty malformed legacy trial shells are ignored and do not affect status
    accounting.
- Evidence (RED -> GREEN):
  - RED: empty malformed trial-shell test failed because the viewer emitted an
    `unknown adapter` warning.
  - GREEN: targeted malformed-path viewer tests passed.
  - GREEN: cached-disabled live `./view --verbose --no-cache` emitted no
    malformed-path warnings for the current result tree.
  - GREEN: `mamba run -n cospa python -m pytest -q` = 161 passed.
- Decision: keep warnings for malformed paths that contain durable artifacts,
  because those represent real parse/counting ambiguity.
- Next: avoid rewriting historical empty result shells unless they interfere
  with resume or score accounting.

## 2026-07-07 — viewer: multi-dimensional grouping by thinking + provider

- Context: qwen/pi_devstack_superpowers run at `--thinking high` was silently
  merged with the default-effort run in `./view`, corrupting both scores.
  Same model id served by different providers (aiand quant vs local nvfp4)
  would conflate capability and cost differences.
- Changes (`view-scores/server.py`):
  - Grouping key extended from (model, adapter, suite) to
    (model, adapter, suite, thinking, provider). Reads
    manifest["sampling"]["thinking"] (default "default") and
    manifest["model"]["provider"] (falls back to model_id prefix).
  - Defensive: when trial is None (pending verdicts), uses defaults so
    started_tasks tracking still works.
  - "Thinking" and "Provider" columns added to both verbose and compact
    table views, placed after Suite.
- Evidence (RED -> GREEN):
  - `tests/test_view_scores_grouping.py` (new): 3 tests covering
    thinking-distinct rows, provider-distinct rows, and aggregation
    across run dirs for same dimensions. All RED before, GREEN after.
  - Full suite: 164 passed (was 161 — 3 new tests added).
- Decision: thinking and provider are first-class axes because cospa's
  thesis is capability-per-cost, and both axes reshape both capability
  and cost (high effort takes longer / more tokens; different quants
  produce different capability at different serving cost).
- Live validation: `./view --verbose --no-cache` now shows separate rows
  for qwen/devsup default (74.4%) vs high (77.8%), and ornith default
  vs high across all adapters.

## 2026-07-07 — viewer: --thinking and --provider dimensional filters

- Context: with multi-dimensional grouping landed, users need to slice the
  table by thinking level (e.g., compare only high-effort runs) and by
  provider (e.g., aiand quant vs local nvfp4).
- Changes (`view-scores/server.py`):
  - New `--thinking LEVEL` and `--provider NAME` CLI flags (on common
    parser; work for table, json, serve). Use `--thinking all` /
    `--provider all` to explicitly disable filtering.
  - `get_scores()` accepts `thinking_filter` and `provider_filter` kwargs;
    applied post-grouping (don't interfere with path-text filters/excludes).
  - Cache key extended to include thinking_filter and provider_filter so
    filtered results don't poison the cache for unfiltered queries.
- Evidence: 2 new tests in `tests/test_view_scores_grouping.py` (filter
  returns matching rows; `all` and unset return everything). Full suite
  166 passed.
- Live verification: `./view --thinking high` correctly shows 6 high-effort
  rows (including qwen/devsup-high at 76.2%); `./view --provider aiand`
  shows only aiand-served runs.

## 2026-07-07 — fix viewer status false-positive on dead high-effort runs

- Context: killed aiand qwen high-effort run still displayed as "running"
  because `_has_live_runner_process` fallback matched the alive
  default-effort runner for the same (model, adapter, suite), ignoring
  the thinking and run-id dimensions.
- Changes (`view-scores/server.py`):
  - `_has_live_runner_process` now also matches `--thinking` (when known)
    and `--run-id` (derived from run_path leaf via encode_model_path),
    so a dead run at one thinking level is not mis-attributed to a live
    run at a different level.
  - Caller in `get_scores` passes `thinking=thinking` to the fallback.
- Evidence:
  - Existing heartbeat-PID logic was already correct; only the fallback
    was too loose.
  - 1 new test in `tests/test_view_scores_grouping.py` (dead high-effort
    runner not marked running when default is alive). Full suite 167 passed.
  - Live: aiand qwen high now correctly shows "partial" (was "running").

## 2026-07-07 — Fix Aider Polyglot verifier false failures
- Context: GPT-5.5 medium showed a pathological language split
  (`python/java/rust` at 0%) that did not match real workdir behavior.
- Changes: Python verification now targets copied test files; Java and Rust
  verify from short temp copies; Java drops stale invalid `JAVA_HOME`;
  JavaScript installs exercise dependencies before `npm test`; verifier
  parsing handles Rust multi-binary output and Gradle JUnit XML counts.
- Evidence: focused RED tests for the confirmed failures now pass; real
  GPT-5.5 artifacts for `python/affine-cipher`, `java/affine-cipher`,
  `rust/accumulate`, and `javascript/alphametics` reverify as passing.
  Full suite: `mamba run -n cospa python -m pytest -q` reports
  173 passed.
- Decision: do not rewrite historical verdicts automatically; existing
  scores from runs verified before this fix should be treated as invalid
  until reverified or rerun.

## 2026-07-15 — Register direct ThinkingCap vLLM model

- Context: prepare a five-adapter Aider Polyglot smoke against
  `thinkingcap-qwen36-27b-fp8` served directly by vLLM 0.23.0 at
  `http://localhost:8001/v1`.
- Decision: record the model as native, unbounded reasoning. Direct vLLM
  accepts `thinking_token_budget`, but stock pi cannot map its symbolic
  effort levels to that top-level field; no explicit harness thinking level
  will be sent for this experiment.
- Evidence: live `/v1/models`, `/version`, chat-completion, runner
  reachability, and headless pi probes succeeded. Full validation:
  `mamba run -n coding-eval python -m pytest -q` (181 passed) and
  `bash tests/scripts/run_all.sh` (41 assertions passed).
- Next action: run five Aider Polyglot problems at `k=1` with `pi_vanilla`,
  `pi_devstack`, `pi_devstack_superpowers`, `little_coder`, and
  `little_coder_superpowers`; add codex-pool budget translation if native
  reasoning becomes excessive.

## 2026-07-15 — Rename the direct provider to local-vllm

- Context: standardize the direct OpenAI-compatible provider prefix as
  `local-vllm` instead of the model-specific `thinkingcap` name.
- Decision: use `local-vllm/thinkingcap-qwen36-27b-fp8` and assign the same
  benchmark-equivalent pricing as Qwen 3.6 27B: $0.30/M input, $0.15/M cache
  read, and $2.40/M output.
- Evidence: pi lists the canonical provider/model, the live runner
  reachability probe succeeds, metadata resolves the expected prices, and
  the focused reachability/usage test set passes (16 tests).
- Operations: stopped the initial four-completed-task `thinkingcap/...`
  smoke rather than mix provider IDs and prices. Its partial durable results
  remain intact; restart under the canonical `local-vllm/...` identity.

## 2026-07-15 — Add docs/MODELS.md candidate-model research for 192 GB rig

- Context: survey open-weight models that fit 2× RTX PRO 6000 (192 GB)
  and might outperform Ornith-1.0-35B on agentic coding benchmarks.
- Evidence: repo sizes from HF API `usedStorage`; quant compositions
  verified by parsing safetensors headers via HTTP range requests (no
  weight downloads); KV math from each model's `config.json`.
- Key finding: gaber/MiMo-V2.5-NVFP4-* repos are broken (all-BF16
  modelopt fake-quant intermediates, ~75% of expert weights missing) —
  documented so we don't rediscover this later.
- Decision: shortlist MiniMax M2.7 NVFP4 (139.9 GB), DeepSeek V4 Flash
  (159.6 GB native), MiMo-V2.5 MXFP4 (176.6 GB, tight); Hy3 and
  MiniMax M3 ruled out on fit/KV grounds.
- Next action: cospa sanity-eval any quant before trusting vendor scores.

## 2026-07-15 — Add speed model and GPU-fit matrix to docs/MODELS.md

- Context: extend the candidate-model survey with decode-speed estimates,
  attention-architecture properties, MTP/draft availability, and a
  utilization (0.90/0.92/0.95) × GPU-count (1/2/3× 96 GB) fit matrix.
- Evidence: bytes-per-token derived from stored dtypes in safetensors
  headers (nvidia/MiniMax-M2.7-NVFP4, deepseek-ai/DeepSeek-V4-Flash,
  MiMo quants); configs fetched for Ornith, M2.7, V4 Flash, MiMo.
- Key findings: DS V4 Flash native repo is already 4-bit (I8 FP4 +
  E8M0/32 scales, 159.6 GB) — prefer it over nvidia's larger NVFP4
  rescale; nvidia M2.7 NVFP4 strips the 3 MTP modules (no spec decode);
  Ornith is hybrid linear attention (30 linear + 10 full) explaining its
  efficiency; MiMo NVFP4 (183.5 GB) exceeds 2×0.95 budget — only the
  MXFP4 repo fits 2 GPUs, and only at 0.95.
- Decision: 2-GPU recommendation reordered to DS V4 Flash > M2.7 >
  MiMo MXFP4, Ornith baseline (can run 2 replicas).

## 2026-07-15 — Add Hy3 deep-dive (divisibility, quants, KV/speed) to MODELS.md

- Context: evaluate Hy3 as the 3-GPU pick and check whether TP across
  3× PRO 6000 is actually possible; enumerate all available quants.
- Evidence: tencent/Hy3 config.json (64 Q / 8 KV heads, 192 experts,
  80 layers, 1 nextn layer); safetensors-header decomposition of
  kodelow, 0xSero, INCModel2, cyankiwi quants (all verified legit —
  full 290B expert coverage, real packed FP4).
- Key findings: TP=3 impossible (64 % 3 ≠ 0) — 3-GPU serving is PP=3
  (~42–96 tok/s single-stream) or TP=2 + spare GPU; INCModel2 MXFP4
  (164.2 GB, FP8 attention) fits 2× TP2 at 0.90 → Hy3 is a 2-GPU dark
  horse (~103–138 tok/s, 58–94K ctx); MTP layer not clearly present in
  any quant; tencent/Hy3-FP8 (299.9 GB) exceeds even 3×0.95.
- Next action: cospa sanity eval of INCModel2 MXFP4 vs DS V4 Flash.

## 2026-07-15 — Document llama.cpp GGUF route and DFlash template in MODELS.md

- Context: field-tested MiMo-V2.5 IQ3_S llama.cpp invocation (r/StrixHalo)
  and AEON-7's Qwen3.6-35B-A3B NVFP4+DFlash setup as a Blackwell
  speculative-decoding reference.
- Evidence: AesSedai/MiMo-V2.5-GGUF sizes from HF API (IQ3_S 114.2 GB,
  IQ4_XS 147.9 GB); AEON-7 README (GB10/sm_121a, 91.7 tok/s coding
  single-stream, 40–58% acceptance at 16–32K ctx, vLLM PR #41703).
- Key notes: GGUF sidesteps TP divisibility and utilization fractions;
  --ctx-checkpoints/-cram and --reasoning-budget are worth stealing for
  agent serving; AEON-7 image is sm_121a-only (rebuild needed for
  sm_120); recipe implies several-hundred tok/s for A3B-class + DFlash
  on PRO 6000, relevant to Ornith (Qwen3.5-MoE lineage).

## 2026-07-15 — Prefer MiMo IQ4_XS for the 2-GPU GGUF route

- Context: AesSedai's published quant comparison provides measured BPW,
  perplexity, and KLD values that sharpen the MiMo GGUF choice.
- Evidence: IQ4_XS is 137.75 GiB at 3.82 BPW with +2.81% PPL and 0.0415
  KLD; Q4_K_M is 177.68 GiB at 4.93 BPW with +1.45% PPL and 0.0206 KLD.
- Decision: recommend IQ4_XS on 2 GPUs. Its ~54 GiB raw headroom is much
  safer than Q4_K_M's ~14 GiB before KV, CUDA workspaces, and runtime
  overhead; correct the prior contradictory 3-GPU IQ4_XS wording.
- Next action: benchmark IQ4_XS quality and decode speed in cospa before
  adopting it as the MiMo serving route.

## 2026-07-15 — Recommend a production-shaped coding-agent eval pilot

- Context: Aider Polyglot is near ceiling for strong configurations, while
  Terminal-Bench has no completed local cost baseline and its current head
  expands to 241 tasks.
- Evidence: measured current `./view` wall/token distributions; reviewed
  official model cards and primary sources for APEX-SWE, FreshBrew, SWE
  Atlas, DeepSWE, SWE-bench variants, and adjacent agent benchmarks.
- Decision: pilot 10 fixed public APEX-SWE tasks, promote to a 20-task
  screen only if it fits the runtime/telemetry/validity gates; use a
  stratified FreshBrew JDK-21 subset if APEX's service stack is too costly.
- Next action: pin APEX-SWE task IDs and run one real model/adapter at k=1
  before implementing a full matrix integration.

## 2026-07-15 — Document MiMo TP3 and PRO 6000 P2P tuning

- Context: add mitomtuna's exact TP3 repack of the 2026-07-03 MiMo-V2.5
  NVFP4 target and its matching DFlash drafter to the 3× PRO 6000 survey.
- Evidence: HF API size (205.6 GB target + 3.0 GB drafter); safetensors
  header inspection (full 191.6 GB padded routed-expert payload); reviewed
  the included transform's duplication/zero-padding invariants and the card's
  PRO 6000 validation (381.5 tok/s, 1.36M-token FP8 KV pool, 90K needle pass).
- Decision: make MiMo TP3+DFlash the first 3-GPU agentic/Terminal-Bench
  throughput experiment, while labeling all numbers card-reported and gating
  the invasive driver/BIOS/NCCL P2P recipe on host-specific reproduction.
- Validation: re-read `docs/MODELS.md` end-to-end and ran `git diff --check`;
  this workspace has no `nvidia-smi`, so the P2P path is not locally verified.
- Next action: on the GPU host, verify every pair with
  `nvidia-smi topo -p2p r` and NCCL `via P2P` logs before comparing TP3
  throughput or running the first cospa trial.

## 2026-07-15 — Refine the coding-eval portfolio for paired harness tests

- Context: review feedback correctly identified missing external-anchor and
  paired-adapter guidance in the first eval survey.
- Evidence: verified the official Terminal-Bench Core 0.1.1 and 2.1
  leaderboards/protocols, the HAL Verified Mini page, and aggregate token use
  in current `./view json` results.
- Decision: pin existing Core 0.1.1 as the immediate 80-task leaderboard
  anchor rather than treating 89-task, k=5 TB 2.1 as cheap; retain APEX-SWE
  as the new cost-gated signal and Verified Mini as an optional second anchor.
- Method: qualify all ten APEX pilot tasks at k=2, distinguish infrastructure
  recurrence from model outcome flips, hold model/provider settings fixed for
  paired comparisons, and cap the default first pass at 10M normalized tokens.
- Next action: fix the current Terminal-Bench `@head` resolution before another
  large run, then execute the APEX cost pilot without a Cartesian matrix.

## 2026-07-15 — Prefer SWE Atlas for harness-trace screening

- Context: compare APEX-SWE with SWE-bench Pro, SWE Atlas, HiL-Bench,
  MCP-Atlas, MCPMark, and Toolathlon specifically for trace signal per
  integration effort, token, and wall-time budget.
- Evidence: reviewed each primary paper, public dataset, and harness; SWE Atlas
  is Harbor-native and publishes $0.35--$1.90/task Q&A + Test Writing cost
  points, while APEX publishes a 53.5-episode Integration mean but no token or
  cost distribution. Public SWE-bench Pro traces average 2.80M--3.13M
  cumulative input tokens across 616 paired tasks in an independent reanalysis.
- Correction: the APEX hidden Observability set spans five languages, but its
  public 25-task tree contains 15 Go and 10 Python cases across six repos; the
  previously proposed five-language public slice cannot be built.
- Decision: pilot 12 SWE Atlas Q&A/Test Writing tasks first through Harbor;
  retain six APEX Observability tasks as a second production-stack stress test,
  and treat HiL/MCP evaluations as specialized sidecars rather than coding
  scores.
- Validation: re-read `docs/EVALS.md` end to end and ran `git diff --check`.
- Next action: select pilot IDs from upstream metadata before observing target
  model outcomes, then run one real model/adapter at k=1 under the cost gates.

## 2026-07-15 — Reuse traces before adding more benchmark runs

- Context: triage the user-supplied 60-plus-family agentic coding map against
  cospa's signal-per-token, harness-comparison, and leaderboard requirements.
- Evidence: checked the Artificial Analysis index and primary artifacts for
  AgentLens, SWE-Explore, FeatureBench, RACE-bench, SWE-Cycle, SWE-bench Live,
  UnderSpecBench, and SWT-Bench. FeatureBench Lite's published means imply
  78M--270M input tokens for one 30-task pass; RACE-bench Lite reports
  145K--3.49M tokens and 156--1,121 seconds per task depending on configuration.
- Decision: retain SWE Atlas as the first controlled screen and APEX-SWE as the
  production-stack stress test. Add an AgentLens-style mechanical and blinded
  paired review over the same normalized cospa trajectories; treat AgentLens,
  SWE-Explore, feature, lifecycle, and safety suites as targeted sidecars or
  milestones rather than another routine Cartesian matrix.
- Sources: cite the shared ChatGPT research map as a secondary discovery
  inventory in `docs/EVALS.md`, while grounding decision-changing claims in
  first-party papers, datasets, harnesses, and leaderboards.
- Validation: re-read `docs/EVALS.md` end to end and ran `git diff --check`.
- Next action: define the cross-adapter event schema and trace-review artifacts
  before or alongside the 12-task SWE Atlas cost pilot.

## 2026-07-15 — Pin Terminal-Bench Core to 0.1.1

- Context: cospa previously discovered all 241 tasks from a mutable
  `terminal-bench-core@head` checkout while describing the suite as the
  leaderboard-compatible Core benchmark.
- Decision: check in the official 80-task Core 0.1.1 manifest, pin setup to
  upstream commit `91e10457b5410f16c44364da1a34cb6de8c488a5`, and refuse
  task discovery from a partial or differently pinned real checkout.
- Evidence: the RED tests proved discovery and manifest accounting selected
  `head`; the pinned checkout now discovers exactly 80 unique task IDs and a
  real vendored `task.yaml` materializes successfully.
- Validation: `mamba run -n coding-eval python -m pytest -q` reports 182
  passed; `bash tests/scripts/run_all.sh` passes all shell assertions.
- Next action: integrate the pinned 12-task SWE Atlas Q&A + Test Writing pilot
  through the same custom Harbor agents.

## 2026-07-15 — Register and smoke-test Ternary Bonsai 27B

- Context: build PrismML's llama.cpp CUDA fork for SM120, serve the ternary
  27B GGUF on physical GPU1, and expose it to cospa through pi's local provider
  configuration.
- Evidence: demo `cfd842af`, llama.cpp `62061f910`, and model repository
  `20e435f5`; all 697 CUDA targets built for `120a`; the three selected GGUF
  files matched their published SHA-256 metadata; health, model discovery, and
  `check_model_reachable()` passed.
- End-to-end: `pi_vanilla` solved the real `cpp/all-your-base` Aider Polyglot
  task in 88.4 seconds and passed all 17 native grader assertions. The result
  is under run id `bonsai-ternary-27b-smoke-20260715`.
- Decision: add `bonsai/Ternary-Bonsai-27B-Q2_0.gguf` to the model matrix with
  the live server's 262K context and explicit 2K server reasoning cap. Keep
  DSpark disabled until it is evaluated as a separate configuration.
- Validation: `./view --all --filter bonsai` reports 1/1. Full pytest reports
  `178 passed, 1 skipped, 2 failed`; the failures are an all-skipped shell
  fixture discovering the unrelated port-8080 service and a PyYAML newline
  assertion, neither on the Bonsai/Aider path.
- Next action: run a fixed six-language Polyglot sample with matched sampling
  and reasoning settings before treating the one-task smoke as a quality
  comparison.

## 2026-07-16 — Integrate the SWE Atlas pilot

- Context: the evaluation review selected a 12-task SWE Atlas cost/reliability
  pilot as the first new harness discriminator before APEX-SWE.
- Decision: freeze eight Test Writing and four Codebase Q&A tasks at upstream
  commit `2cac47d64a9123d915b8f6f6f53763391920f574`, with two Test Writing
  plus one Q&A task per Go, Python, C, and TypeScript stratum. Pin the rubric
  judge to `anthropic/claude-opus-4-5-20251101` and fail preflight when its
  credentials are absent.
- Evidence: the RED test failed because `swe_atlas_pilot12` was not registered;
  the real pinned checkout now discovers and materializes all 12 task prompts,
  environments, graders, rubrics, and mutation artifacts. Unit coverage also
  verifies k=3 forwarding, adapter delegation, pin rejection, and native Q&A /
  Test Writing subcheck preservation.
- Status: `wired (unit test + real pinned artifact)`. No matching Opus 4.5 judge
  endpoint is configured in this environment, so rubric scoring is explicitly
  not claimed as end-to-end verified.
- Validation: `mamba run -n coding-eval python -m pytest -q` reports 194
  passed; `bash tests/scripts/run_all.sh` reports 47 shell assertions passed.
- Next action: configure the pinned judge endpoint and run all 12 with one
  representative model, `pi_vanilla`, and k=1 before evaluating promotion.

## 2026-07-16 — Isolate Aider trials from reference solutions

- Context: a Bonsai adapter comparison exposed two integrity failures: the
  materializer copied official `.meta` examples and `.approaches` solution
  guides, while agents could inspect neighboring vendor tasks, prior results,
  and global pi session transcripts.
- RED evidence: new six-language prompt/reference tests, the six-adapter
  sandbox invariant, a real bubblewrap boundary check, sandbox telemetry, and
  clean-copy C++ verification each failed on the corresponding old behavior.
- GREEN evidence: the focused suite reports `56 passed, 1 skipped`; full
  `mamba run -n cospa python -m pytest -q` reports `195 passed, 1 skipped, 2
  failed`, with only the pre-existing port-8080 shell-fixture collision and
  PyYAML newline assertion failing.
- End-to-end: run id `bonsai-isolated-final-20260716` executed
  `cpp/all-your-base` sequentially with `pi_vanilla`, `pi_devstack`,
  `pi_devstack_superpowers`, `little_coder`, and
  `little_coder_superpowers`; every arm passed all 17 native assertions.
- Decision: treat 2026-07-16 as the Aider integrity cutover. Preserve older
  artifacts for audit, but do not use pre-cutover passes as independent-solving
  evidence. Require Linux bubblewrap and fail closed when it is unavailable.
- Next action: rerun any historical model/adapter rows needed for comparison,
  then expand the clean sample across all six Polyglot languages.

## 2026-07-16 — Keep benchmark pi session paths below NAME_MAX

- Context: the full ThinkingCap run left `pi_devstack_superpowers` at 213/225
  because pi flattened deep trial workdirs into session-directory components
  longer than Linux NAME_MAX (255 bytes). The viewer correctly surfaced the
  missing trials as a stale/incomplete cell rather than a model failure.
- Decision: every pi-backed adapter now passes a trial-local
  `--session-dir <out>/pi-sessions`; telemetry reads that explicit directory
  first and falls back to the legacy encoded-workdir location for old/custom
  adapters.
- Evidence: the RED adapter matrix reproduced commands without
  `--session-dir`, and the RED telemetry test rejected explicit session
  directories. Both are green, including a constructed deep result path whose
  session-directory components remain within NAME_MAX.
- Validation: `mamba run -n coding-eval python -m pytest -q` reports 196
  passed; `bash tests/scripts/run_all.sh` reports 47 shell assertions passed;
  `git diff --check` and Python compilation pass.
- Next action: after the active `little_coder` cell, recover the 12 missing
  `pi_devstack_superpowers` trials and let `little_coder_superpowers` start
  with the fixed session path.

## 2026-07-16 — Preserve devstack identity inside Terminal-Bench

- Context: distinct Harbor agent class names still collapsed `pi_devstack` to
  bare pi because every task container started with an empty pi package home.
- Decision: bind-mount a read-only, sanitized devstack package snapshot for the
  two `pi_devstack*` arms, activate its npm/git caches and settings in the
  container, and leave vanilla/little-coder arms unmounted.
- Evidence: RED tests showed no mounts/profile setup. A real smoke then caught
  Harbor 0.16 rejecting string mounts, followed by Camoufox's 664 MB bootstrap
  and pi-zentui's headless stale-context crash; object-form mounts plus explicit
  package filters produced a passing Ornith `pi_devstack` `hello-world` trial.
- Validation: `mamba run -n coding-eval python -m pytest -q` reports 198
  passed; `bash tests/scripts/run_all.sh` reports 47 shell assertions passed;
  end-to-end artifact:
  `results/e2e-smoke-terminal-bench-devstack-profile-v5-20260716T034155Z/`.
- Next action: run the five-adapter, five-task Ornith Terminal-Bench pilot and
  continue to all 80 tasks only if every pilot artifact is infrastructure-clean.

## 2026-07-16 — Audit Aider Polyglot rollout leakage

- Context: Aider Polyglot trials ran without filesystem or network guardrails,
  making benchmark-answer access possible but previously unmeasured.
- Evidence: reviewed 5,725 preserved pi JSONL traces across 26 model/adapter/
  effort cells. Every auditable model accessed `.meta/example.*` reference
  implementations; 700 traces did so, including 656 passing traces.
  Stronger cases copied references into submissions, fetched public solutions,
  or read another model's result tree.
- Decision: document the snapshot in `ANALYSIS-EVAL-RESPONSE.md`, distinguish
  direct evidence from intent and unknown counterfactual score impact, and
  classify Nemotron as not auditable rather than clean because it has no
  preserved JSONL rollout.
- Validation: re-read the report end to end and ran `git diff --check`.
- Next action: quarantine contaminated scores, remove answer-bearing metadata
  during materialization, and rerun a matched sandboxed/no-network slice.

## 2026-07-16 — Enforce hermetic benchmark execution

- Context: the initial Aider cutover still exposed the read-only host root and
  general network, while host-side verification executed model-written code.
- RED evidence: real boundary tests could reach an unrelated local HTTP port;
  verifier calls lacked isolation; Harbor could fall back to an unpatched
  public-network task; and dependency warm-up exceptions left no durable trial.
- GREEN evidence: focused isolation, adapter, suite, runner, and Harbor tests
  report 78 passed and 1 skipped, apart from the pre-existing PyYAML newline
  assertion. Real vendored JavaScript, Rust, Java, Python, and C++ toolchains
  reached their expected starter-code test/build failures offline.
- Decision: use empty-root filesystem allowlists, a selected-model Unix relay,
  and no-network verifier namespaces for Aider. Prefetch only dependency-bearing
  languages. Patch only Harbor's prompt-bearing agent phase to a model-host
  allowlist and fail closed when a local task policy cannot be applied.
- Environment: install OpenJDK 21 in the `cospa` mamba environment for the
  vendored Gradle 8.7 wrappers.
- End-to-end: Bonsai with `pi_vanilla` solved `cpp/allergies` through the final
  boundary in 30.6 seconds; the isolated verifier passed all 50 assertions.
- Post-rebase validation: `226 passed, 2 skipped, 2 failed`; the shell harness
  reports 46 passed and one failure. Both failures are the pre-existing
  port-8080 fixture collision and PyYAML newline assertion.
- Next action: validate the new Harbor policy in a Docker-capable checkout.

## 2026-07-16 — Quarantine contaminated Aider trials

- Context: the trace audit established direct answer/reference access, and
  unauditable artifacts could not be assumed clean.
- Decision: conservatively move affected artifacts out of score-discoverable
  `results/` rather than delete forensic evidence. Quarantine any trial with
  answer-bearing metadata, benchmark network/vendor access, cross-result
  access, a missing/unparseable trace, or incomplete manifest/verdict.
- Evidence: 1,656 entries moved under
  `results-malformed-quarantine/aider-polyglot-leakage-20260716T0531Z/`:
  1,168 trial directories plus 488 stale no-trial task artifacts. The durable
  JSONL manifest records source, destination, reasons, and trace evidence.
- Validation: all 1,656 manifest destinations exist and original sources do
  not; the quarantine preserves 1,153 verdicts/traces; a post-move trace scan
  reports no remaining contamination signals, only 1,168 expected rerun holes.
  `rerun-plan.json` accounts for all 5,850 slots in the 26 audited cells as
  4,592 retained clean trials plus 1,258 required reruns; the command file
  passes `bash -n` and `git diff --check` passes.
- Next action: merge the workdir/filesystem/network isolation fixes, then run
  the generated resume-safe commands to fill only the quarantined/missing
  slots before regenerating scores.

## 2026-07-22 — Add Laguna S 2.1 to the local model shortlist

- Context: Poolside released Laguna S 2.1 after the original model survey; its
  official 71.9 GB NVFP4 target and 2.23 GB DFlash draft fit one PRO 6000 and
  report stronger overlapping coding scores than Ornith.
- Evidence: reviewed the release post, official HF collection/model cards,
  repository file trees, quantization config, and DFlash benchmark card;
  recalculated weight, KV, fit, and bandwidth-model estimates.
- Decision: rank Laguna as the first 1-GPU trial while preserving explicit
  caveats for Poolside-harness scores, 100K+ thinking traces, Pi tool-call
  failures, unaudited tensor headers, and the early serving stack.
- Validation: re-read `docs/MODELS.md` end to end; `git diff --check` and a
  Markdown table-column check pass.
- Next action: run both thinking modes with preserved reasoning on one PRO
  6000, record token counts/tool-call recovery, then validate NVFP4+DFlash
  speed and 262K-context memory use before promoting it to the matrix.

## 2026-08-01 — Persist trial-local sessions through sandbox

- Context: the first real DS4 `pi_devstack` Aider run passed all 17 native
  assertions, but its manifest had empty token usage. Pi received the explicit
  trial-local `--session-dir`, yet the empty-root sandbox did not expose that
  path, so no trace survived. After mounting it, collection still rejected the
  trace because its header records the sandbox's virtual cwd rather than the
  host workdir.
- RED evidence: `test_agent_sandbox_persists_explicit_session_dir` failed when
  the sandbox could not touch a trace outside its workdir, and
  `test_run_trial_collects_trial_local_session_from_sandbox_cwd` failed with
  unavailable usage for a trial-local trace carrying the virtual cwd.
- Decision: recognize absolute `--session-dir` arguments, bind only that
  directory into the hermetic namespace after `/tmp` and `/run` tmpfs setup,
  then pair it with the virtual sandbox cwd during telemetry collection before
  retaining the legacy global-session fallback.
- GREEN evidence: both regression tests pass, along with the existing explicit
  session, legacy virtual-cwd, and real sandbox boundary tests. A fresh real
  `ds4/deepseek-v4-flash-0731` + `pi_devstack` run solved
  `cpp/all-your-base` in 27.1 seconds, passed 17/17 assertions, copied
  `out/pi_session.jsonl`, and recorded seven responses, 99,805 summed prompt
  tokens, and 1,158 output tokens.
- Validation: full pytest reports `228 passed, 2 skipped, 2 failed`; this is two
  additional passes with the same pre-existing port-8080 fixture collision and
  PyYAML block-scalar newline failure. The shell harness retains its same one
  port-8080 collision; all other 46 assertions pass. `git diff --check` passes.
- Next action: keep the one-task DS4 result as bounded smoke evidence only;
  choose a multi-language slice before making a suite-level quality claim.

## 2026-08-02 — Correct special-case Aider grading

- Context: the first complete DS4 Aider campaign produced two false-negative
  verdicts among its 11 apparent failures. A root C++ build executable named
  `complex-numbers` shadowed the verifier's same-name source alias, and Go's
  test-design-only `counter` exercise was run without selecting its four
  supplied implementations.
- RED evidence:
  `test_verify_cpp_replaces_generated_binary_at_source_alias` observed a
  regular file instead of the required source symlink, while
  `test_verify_go_counter_checks_all_implementations` observed one generic
  `go test` command instead of the task's required implementation matrix.
- Decision: reserve and recreate the C++ source alias inside the disposable
  verification copy. For `go/counter`, require model-authored tests to reject
  known-bad `COUNTER_IMPL=1,2,3` and pass correct `COUNTER_IMPL=4`; other Go
  exercises retain the generic verifier.
- GREEN evidence: both regression tests pass. Real dry-run reverification of
  the preserved DS4 workdirs changes `cpp/complex-numbers` from 0 tests to
  40 passing cases and `go/counter` from an unset-env failure to four passing
  model-authored test cases. Write-mode reverification retained timestamped old
  verdict backups and recorded the replacement verdict metadata.
- Validation: full pytest reports `230 passed, 2 skipped, 2 failed`; the only
  failures remain the documented port-8080 fixture collision and PyYAML
  block-scalar newline assertion. The shell harness retains its same one port
  collision and all other 46 assertions pass. Python compilation and
  `git diff --check` pass.
- Next action: dry-run reverify all 225 DS4 trials for any additional grader
  drift, then retain and report the corrected full score.

## 2026-08-12 — Add Muse Glimmer 30B to the model matrix

- Context: Meta's Muse Glimmer 30B is served locally at
  `http://stg04.local:8989/v1` (pi provider `local`, served model id
  `Muse-Glimmer-30B`). Add it to the cospa matrix with real pricing so cost
  accounting reflects the provider.
- Evidence: `bash scripts/check-models.sh` reports `local/muse-glimmer-30b`
  ALIVE (46 ms, HTTP 200); metadata resolves to pi `Muse-Glimmer-30B` with
  context 131072 / max 65536 / reasoning; a 5-problem Aider Polyglot smoke
  (`pi_vanilla`, k=1) passed all trials and the manifest records the cost.
- Decision: price per the deepinfra numbers from the OpenRouter listing:
  $0.30 input / $1.20 output / $0.04 cache-read per 1M tokens
  (`input: 0.30, output: 1.20, cacheRead: 0.04, cacheWrite: 0`). The score
  viewer's `_estimate_cost_usd` reads this repo config via `load_model_metadata`
  (strict id match), so per-trial and total cost reflect the deepinfra rates.
- Validation: `configs/models.yaml` parse + metadata lookup, model reachability
  check, and one real end-to-end smoke run.
- Next action: full Aider Polyglot run (225 problems, pi_vanilla + pi_devstack,
  k=1) underway as `muse-glimmer-20260812-aider-full`; report scored results
  when complete.

## 2026-08-12 — Fix Aider hidden-test contamination

- Context: A Muse-Glimmer Aider Polyglot run scored 223/225, implausibly high.
  Trace review showed the model read `all_your_base_test.cpp` before solving:
  the suite copied the problem's test files into the agent workdir, so the
  model saw the exact assertions. The prior isolation audit excluded
  `.meta/.approaches` but not the test files themselves.
- Evidence: RED tests `test_materialize_task_hides_test_files_from_workdir`
  (6 languages) and `test_verify_reinjects_hidden_tests_at_grading_time`
  failed before the fix (test file present in workdir); GREEN after. Real
  vendor python (16 collected) and cpp (test file compiled) runs confirm
  tests are hidden during the solve and re-injected+run at grading time.
- Decision: exclude hidden test files/subtrees from the agent workdir
  (`HIDDEN_TEST_PATTERNS`/`HIDDEN_TEST_RELATIVE`); `verify()` restores them
  after the agent finishes via `vendor_problem_dir`/`hidden_test_paths`.
  Replaced the two tests that had codified the leak.
- Validation: full pytest reports `236 passed, 2 skipped, 2 failed`; the only
  failures are the pre-existing check-models port-8080 collision and the
  PyYAML block-scalar newline assertion (both confirmed present on baseline).
- Next action: clear contaminated Aider results (Bonsai, DeepSeek, Muse-
  Glimmer) and re-run Muse-Glimmer Aider Polyglot for clean numbers.

## 2026-08-13 — Add DeepSeek V4 Flash 0731 to the matrix

- Context: run a second local model in parallel with Muse-Glimmer to get more
  eval throughput without endpoint contention (DeepSeek is served on separate
  GPUs behind the same stg04.local pool).
- Evidence: `local/deepseek-v4-flash-0731` resolves to pi `DeepSeek-V4-Flash-0731`
  (context 262144 / max 65536 / reasoning); a 1-token ping returns the served
  model `deepseek-v4-flash-0731`.
- Decision: add to `configs/models.yaml` with the provider's own pricing
  (input 0.14 / output 0.28 / cacheRead 0.0028 / cacheWrite 0.14 per 1M).
- Validation: metadata lookup + reachability ping; run launched in parallel
  with the Muse-Glimmer Aider run (vanilla + devstack).
- Next action: report clean scored results for both models when the runs finish.

## 2026-08-13 — Route Ornith through codex-pool shisa provider

- Context: prior `local/ornith-1.0-35b` id routed to codex-pool's `local`
  provider, which has no live ornith account -> HTTP 503. Ornith is served on
  Shisa production (`api.shisa.ai/openai`), reachable via codex-pool as
  `ornith-35b-fp8-block`.
- Evidence: direct curl through codex-pool returned reasoning_tokens +
  cached_tokens (256 on prefix repeat); pi->codex-pool->shisa end-to-end
  (stopReason stop, thinking block, cacheRead 12288 on turn 2); pi initially
  failed with 400 because it sent `role:developer` which api.shisa.ai rejects.
- Fix: added a `shisa` provider to `~/.pi/agent/models.json` (baseUrl ->
  codex-pool, model `ornith-35b-fp8-block`, compat.supportsDeveloperRole=false
  so pi sends `system`, supportsReasoningEffort=true so `--thinking xhigh`
  forwards); pointed `configs/models.yaml` ornith id at `shisa/ornith-35b-fp8-block`.
- Validation: load_model_metadata resolves reasoning+cost; tests
  test_harness / test_usage_capture / test_usage_backfill pass.
- Next action: launch Ornith Aider run (pi_vanilla + pi_devstack, --thinking
  xhigh) as bg tasks once muse/ds4 slots free, or on request.

## 2026-08-13 — Add no-network hint to all adapter prompts

- Context: devstack runs scored 0% because the full-pi agent (with web/search
  tools) tried to fetch the hidden *_test.cpp from GitHub when it couldn't find
  it; all network is blocked in the sandbox (SSRF/DNS), so it retried across
  web_fetch/tff-fetch_url/curl/tff-search_web until the 600s timeout. Muse
  devstack: 55/55 traces hit SSRF walls. Not a scoring bug (one ds devstack
  trial compiled+ran and failed a real test).
- Change: added `with_no_network_hint()` in harness/adapters/session_utils.py
  and prepended the single-line hint to the prompt in all six adapters
  (pi_vanilla, pi_devstack, pi_superpowers, pi_devstack_superpowers,
  little_coder, little_coder_superpowers).
- Evidence: tests/test_adapter_prompt_hint.py (all adapters prepend the hint,
  original task preserved). test_harness/test_usage_* pass; the 2 remaining
  suite failures (test_terminal_bench materialize, test_scripts) are pre-existing
  on clean tree.
- Next action: restart devstack runs under the hint once current runs finish.
