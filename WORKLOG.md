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

## 2026-07-16 — Audit suite protection and network boundaries

- Context: the Aider cutover was hermetic, but Terminal-Bench and SWE Atlas
  still depended on Harbor phase semantics and had not received an adversarial
  filesystem, credential, and required-network review.
- Findings: SWE Atlas agents had public egress, inherited judge/unselected
  provider credentials, omitted devstack mounts, and could leave a daemon to
  observe later verifier files. Terminal-Bench restricted ordinary agent turns
  but retained public verification, could be bypassed by explicit Compose
  `main` networking, and cannot faithfully run at least 27 dependency-installing
  official solutions under a model-only policy. A real Harbor watcher saw
  hidden tests after the agent returned.
- Decision: add model/judge phase allowlists, selected-credential-only agent
  env, SWE Atlas daemon cleanup, IP-literal and explicit-Compose fail-closed
  checks, and preserve an honest `partial` status where benchmark semantics
  still conflict with isolation.
- Evidence: RED/GREEN tests cover each protection; the real Aider boundary,
  real Terminal `hello-world` path, real migrated Compose refusal, pinned SWE
  task policy, adversarial Harbor watcher, and Docker process-cleanup probes
  were exercised. Full pytest and shell-harness results are recorded in
  `docs/PROTECTION-AUDIT.md`.
- Next action: partition/prefetch Terminal-Bench and isolate its verifier;
  isolate SWE Atlas candidate tests from hidden rubrics/judge credentials, then
  run a judge-backed Q&A smoke.

## 2026-07-17 — Mark hermetic Aider manifests explicitly

- Context: trace-based cleanup left pre-cutover and hermetic trials impossible
  to distinguish mechanically from manifest data alone.
- RED evidence: `test_manifest_has_required_fields` failed because the Aider
  suite manifest had no `isolation` block.
- Decision: bump the suite protocol to 0.3 and record the exact
  `aider-hermetic-v1` filesystem, agent-network, verifier-network, and excluded
  reference-artifact policy in every new Aider manifest.
- Validation: focused manifest/Aider tests report 44 passed; full
  `mamba run -n coding-eval python -m pytest -q` reports 237 passed; `git diff
  --check` passes.
- Next action: archive every unmarked Aider result before starting fresh
  campaigns; never combine unmarked and `aider-hermetic-v1` trials.

## 2026-07-17 — Archive every pre-cutover Aider result

- Context: the first trace-based quarantine left 4,592 unmarked trials in score
  discovery even though their workdirs had exposed answer-bearing metadata.
- Decision: archive every extant Aider suite tree rather than infer cleanliness
  from incomplete tool-call traces, and retire the mixed resume plan.
- Evidence: 66 suite trees moved to
  `results-malformed-quarantine/aider-polyglot-pre-cutover-20260716T193340Z/`,
  preserving 4,658 trials and 1,212 stale task directories in a durable JSONL
  move manifest. All 66 sources are absent, every destination exists, and the
  archive contains all 4,657 original manifest/verdict pairs.
- Validation: `find results -type d -name aider_polyglot` returns zero and
  `./view --all --no-cache` shows zero Aider rows; `git diff --check` passes.
- Next action: use only fresh run IDs whose manifests carry
  `aider-hermetic-v1`; keep both quarantine generations for forensic review.

## 2026-07-17 — Expose FNM adapters inside the Aider sandbox

- Context: the first fresh hermetic ThinkingCap canary exited 127 because the
  empty-root namespace only recognized NVM while this host installs pi and
  little-coder through FNM.
- RED evidence: the real `cpp/all-your-base` canary reported `pi: command not
  found`; the new FNM root test failed before the installation detector existed.
- Decision: resolve the selected Node binary to its allowlisted NVM/FNM
  installation, mount only that installation read-only, and replace its host
  shim directory in `PATH` without shadowing task-local test executables.
- Validation: the rerun canary reached the model and passed all 17 native C++
  assertions; focused tests report 5 passed and full
  `mamba run -n coding-eval python -m pytest -q` reports 238 passed.
- Next action: persist the explicit pi session directory through Bubblewrap so
  the same canary retains its JSONL trace and token/cost telemetry.

## 2026-07-17 — Persist hermetic Aider session telemetry

- Context: after the FNM launch fix, the real canary passed grading but pi wrote
  its explicit session directory only inside the ephemeral Bubblewrap root, so
  the manifest had no trace, tokens, or cost.
- RED evidence: the real canary had empty `token_usage`; the persistence test
  found no host JSONL, and the runner wiring test could not match a persisted
  trace whose header used the virtual sandbox cwd.
- Decision: rewrite `--session-dir` to a private `/mnt` path, bind only its
  trial-local host directory read/write, restrict repository mounts to explicit
  `--skill` values, and match explicit sessions against the sandbox cwd.
- Validation: the third real `cpp/all-your-base` canary passed all 17 assertions,
  preserved both raw and copied JSONL traces, and recorded 31,820 tokens plus
  $0.0123621 cost. Focused tests report 7 passed; full
  `mamba run -n coding-eval python -m pytest -q` reports 240 passed.
- Next action: resume this fresh run ID across all five adapters sequentially.

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

## 2026-08-14 — Show average model turns in verbose scores

- Context: compare how many model/tool-loop turns different models need to
  solve benchmark tasks, alongside the existing average wall-clock time.
- Evidence: RED→GREEN
  `test_verbose_scores_average_response_turns_across_trials` uses three real
  encoded trial artifacts (2, 4, and 9 responses) and verifies a 5.0-turn
  average rendered after `Avg`. All 48 viewer tests pass; a live
  `./view --results-dir results/runs --no-cache -v` shows populated turns.
- Decision: treat each usage-bearing assistant response in pi's session JSONL
  as one turn, average over completed trials with observed response counts,
  expose `mean_turns`/`turn_counted_trials` in score JSON, and invalidate the
  viewer cache so existing rows are recomputed.
- Validation: full pytest reports `242 passed, 2 skipped, 2 failed`; the only
  failures are the pre-existing check-models port collision and Terminal-Bench
  PyYAML block-scalar newline assertion documented on the prior baseline.

## 2026-08-14 — Enforce model-card sampling profiles in pi runs

- Context: manifests recorded `server-default` and adapters did not set
  temperature/top-p/top-k. Direct server inspection found DeepSeek's vLLM
  auto-generation config already uses the card's 1.0/1.0, but Muse's SGLang
  defaults were 1.0/1.0/top_k=-1 rather than its card's 1.0/.95/64. Ornith's
  Shisa route also received no explicit sampling fields.
- Change: added model-card profiles to configs/models.yaml (DeepSeek 1/1;
  Muse 1/.95/64; Ornith .6/.95/20), propagated them into manifests, added
  pi-adapter fail-closed validation against pi models.json `samplingParams`,
  and configured those actual pi entries. Manifest now records model maxTokens
  because pi sends it as max_tokens.
- Evidence: a localhost logging proxy captured actual pi completion payloads:
  DS `{temperature:1,top_p:1,reasoning_effort:max}`, Muse
  `{temperature:1,top_p:.95,top_k:64,reasoning_effort:xhigh}`, Ornith
  `{temperature:.6,top_p:.95,top_k:20,reasoning_effort:xhigh}`. Focused suite:
  47 passed. Full suite: 247 passed, 2 skipped; only pre-existing
  test_terminal_bench newline and test_check_models shell failures remain.
- Decision: discard partial Muse and Ornith runs made before explicit profiles;
  DeepSeek's paused partial uses its matching 1/1 effective defaults.

## 2026-08-14 — State hidden references are unavailable in task prompts

- Context: Muse spent a live trial recursively searching the sandbox after
  implementing its solution, attempting to find a hidden test/reference. The
  benchmark intentionally exposes neither; this should be factual task context,
  not a prohibition that masks subsequent agent behavior.
- Change: added “There are no hidden tests or reference solutions available.”
  to the shared no-network prompt hint used by every adapter.
- Evidence: RED then GREEN test in test_adapter_prompt_hint.py; focused prompt
  and sampling tests: 11 passed.

## 2026-08-14 — Direct agents to solve from visible task context

- Context: the prior hint’s phrase “provided files” could imply that a missing
  test interface should be located elsewhere, reinforcing futile hidden-test
  searches.
- Change: replaced it with the concise factual boundary: “Network access,
  hidden test files, and reference solutions are unavailable. Solve the task
  directly from the problem statement and visible workspace.”
- Evidence: RED then GREEN test_adapter_prompt_hint; prompt and sampling tests:
  11 passed.

## 2026-08-14 — Capture and expose behavioral telemetry

- Context: pi session JSONL preserves tool calls and usage, but its timestamps
  cannot separate provider inference from tool execution. Behavioral comparison
  also needs exact tool names, categories, counts, errors, and search patterns.
- Change: all pi-backed adapters now load a telemetry-only extension that records
  provider/message/tool boundaries. The runner persists parallel-safe timing and
  tool/category rollups; the viewer exposes LLM%, Tool%, Calls, and Search while
  APIs retain detailed maps and slow-call examples. Legacy backfill recovers
  counts/types/errors/search examples as `counts_only`, never invented timing.
- Evidence: RED/GREEN behavior, adapter, runner, backfill, and viewer tests; 76
  affected tests pass. Real pi tests against a local fake OpenAI server captured
  inference and a real bash call end-to-end. A copied DeepSeek trace backfilled
  16 calls, 2 errors, and 4 searches. Full suite: 270 passed, 2 skipped; only the
  pre-existing non-hermetic check-models endpoint test and Terminal-Bench `|-`
  newline assertion fail. Excluding those known tests: 267 passed, 2 skipped.
- Decision: use unioned tool intervals for percentage (parallel-safe), preserve
  summed worker time separately, and keep full tool payloads only in pi JSONL.
  Existing in-flight runs can be count-backfilled but require restart for timing.

## 2026-08-14 — Define the Cospa evaluation portfolio

- Context: Aider's 225-task difficulty sample and retry/test-feedback protocol
  conflate contract inference with implementation, and the prior eval review
  contained pre-hidden-test Aider measurements that are no longer valid.
- Change: rewrote `docs/EVALS.md` around the `aider_cospa` protocol, a 50/50
  repeated-versus-language-specific contract panel, explicit benchmark quality
  gates, separate capability/time budgets, a repository-source bake-off, and
  reviewed methodologies for the leading multilingual, feature, terminal,
  fresh, and low-cost coding evaluations. Updated `README.md` and
  `docs/PLAN.md` so the public overview and architecture source of truth carry
  the same protocol names, contamination boundary, and cost-gated campaign.
- Evidence: checked the 225-task vendored corpus (225 instances, 100 concepts,
  183 repeated-concept instances); reviewed first-party papers, repositories,
  dataset cards, and harness docs; calculated a labeled runtime table from the
  clean in-progress Cospa manifests and published budgets; re-read the document
  end to end; `git diff --check` passes.
- Decision: keep `aider_canonical` only as a legacy comparator; do not assign
  the `aider_cospa` name until all 225 public contracts and hidden assertions
  are reviewed. Treat unknown external runtimes as pilot-required rather than
  implied by task count, and measure `c=1` versus `c=2` before scaling.
- Next: create the versioned 225-row contract audit manifest and run the
  Multi-SWE Flash / SWE-bench Multilingual / SWE-PolyBench validity bake-off.

## 2026-08-14 — Repair and pin the evaluation setup path

- Context: the real setup path still targeted the retired `coding-eval` mamba
  environment, advanced Polyglot from mutable head, referenced the rewritten
  Terminal-Bench repository that no longer exposes the Core 0.1.1 commit, and
  installed an unpinned Harbor 0.2.0 CLI incompatible with Cospa's validated
  Harbor 0.16.1 command contract.
- Change: setup now verifies the canonical `cospa` Python 3.12 environment,
  pins Polyglot at `7e0611e77b54e2dea774cdc0aa00cf9f7ed6144f`, clones Core
  0.1.1 from archived `harbor-framework/terminal-bench-1`, and enforces Harbor
  0.16.1. The exact Harbor install bypasses a host-level `UV_EXCLUDE_NEWER`
  cutoff only for that immutable version. PLAN, the dataset manifest, and the
  runner usage example now agree with the executable setup.
- Evidence: RED then GREEN `tests/scripts/test_setup.sh` (16 assertions),
  `bash -n scripts/setup.sh tests/scripts/test_setup.sh`, JSON validation, and
  `git diff --check`. Two consecutive real setup passes installed/verified
  Harbor 0.16.1 and pinned Terminal-Bench, SWE Atlas, and Polyglot; real suite
  discovery returns exactly 80 Terminal-Bench and 12 SWE Atlas tasks.
- Decision: retain lower-level suite execution as `wired` until fresh Docker
  smokes pass. A focused Terminal-Bench/SWE Atlas pytest run produced 35 passes
  and only the already-documented PyYAML `|-` newline fixture failure; it does
  not block this setup-path correction.
- Next: freeze the deterministic pilot manifests, validate null/gold/repeat
  behavior, then run Ornith smoke and concurrency crossover gates.

## 2026-08-14 — Freeze the Ornith runtime pilot

- Context: a 10% sample can project operational time but is too small for a
  precise score estimate. The campaign also needs explicit c=16 safety gates
  rather than assuming serving throughput translates into agent throughput.
- Change: added `configs/ornith_runtime_pilot_v1.json` with immutable source
  and dataset revisions/checksums, outcome-blind task IDs and strata, the
  Ornith/pi-vanilla configuration, required timing/tool telemetry, failure
  taxonomy, host reserves, and a gated `c=1/2/4/8/16` ladder. Pilot sizes are
  23 Aider source tasks, 8 Terminal-Bench Core, all 12 SWE Atlas tasks, 30 each
  from Multi-SWE Flash and SWE-bench Multilingual, 38 PolyBench Verified, 6
  FeatureBench Lite, and 15 BigCodeBench-Hard Instruct.
- Evidence: RED then GREEN `tests/test_eval_runtime_pilot.py` (10 tests),
  including real-vendor revision/hash/task checks. All eight source checkouts
  match their 40-character pins; all five downloaded dataset files match the
  manifest SHA-256 values. The host has 683 GiB free on `/`.
- Decision: target a 12-hour result with a 20% reserve (9.6-hour campaign
  budget). Treat pilot scores as directional. Aider remains blocked on the
  contract audit, SWE Atlas on judge configuration, and repository suites on
  image-digest plus repeated null/gold validation; these gates are explicit,
  not ordinary model failures.
- Next: resolve selected image digests, exercise null/gold/repeat verification,
  integrate the cheap BigCodeBench anchor, then begin matched Ornith smokes.

## 2026-08-14 — Lock first-wave evaluation images

- Context: five selected evaluation families still referenced mutable task or
  verifier image tags, so model runs could not be reproduced or safely start.
- Change: added a fail-closed resolver and a Linux/amd64 lock containing 105
  immutable platform-manifest digests: 30 Multi-SWE Flash, 30 SWE-bench
  Multilingual, 38 SWE-PolyBench, 6 FeatureBench, and one BigCodeBench verifier.
  The resolver computes upstream Multi-SWE image names, writes atomically, and
  retries transient registry failures with bounded backoff.
- Evidence: RED then GREEN digest-status and transient-retry tests; two complete
  real registry resolutions produced the same 105 digests; 18 focused tests
  pass. Full pytest reaches 290 passes with only the two already-documented
  baseline failures in the non-hermetic check-models endpoint test and the
  Terminal-Bench YAML `|-` newline assertion.
- Decision: advance repository suites to `blocked_gold_null_validation`, not
  runnable. A resolved tag proves artifact identity, not verifier validity.
- Next: integrate BigCodeBench-Hard, then run repeated null/gold checks against
  pinned repository-suite images before any Ornith score episode.

## 2026-08-14 — Reuse unchanged evaluation image locks

- Context: advancing suite-readiness metadata changed the pilot manifest hash
  but not its 105 image requests; re-querying every mutable registry tag failed
  after three retries and could unnecessarily change a frozen lock.
- Change: added an explicit `--reuse-existing` mode that validates exact image
  keys, suite/task provenance, Linux/amd64 platform, digest syntax, and pinned
  references before refreshing only the source-manifest path and hash.
- Evidence: RED then GREEN reuse/mismatch tests; all 9 resolver tests pass; the
  real 105-image lock reused successfully and its source SHA-256 matches the
  updated pilot manifest.
- Decision: full resolution remains the default. Reuse is fail-closed and is
  permitted only when the requested image set and provenance are identical.
- Next: use full resolution for image changes and validated reuse for metadata-
  only pilot updates.

## 2026-08-14 — Integrate BigCodeBench-Hard Instruct pilot15

- Context: BigCodeBench is a cheap one-shot generation anchor, not an agent
  scaffold arm; running it through pi's coding loop would make its score
  incomparable and invent tool behavior the upstream protocol does not have.
- Change: added a 15-task public prompt spec, a protocol-only adapter that sends
  exactly one OpenAI-compatible user message with no system/tools, and upstream
  calibrated scoring in the immutable Linux/amd64 evaluator. The runner now
  preserves suite sampling overrides, records explicit zero-tool telemetry and
  inference/verifier/total timing, and rejects a mismatched adapter. Hidden
  parquet rows are converted only in container `/tmp`; no tests or canonical
  solutions enter the model request or retained workdir.
- Evidence: RED then GREEN `tests/test_bigcodebench.py` (7 tests); full pytest
  reaches 299 passes with only the two documented baseline failures. In the
  real 15.1 GB offline image, all 15 selected gold solutions pass, all 15 null
  solutions fail, and every ground-truth rate is 1.000. `BigCodeBench/15`
  repeated gold/null three times and the final single-container path repeated
  both once with no hidden export retained.
- Decision: mark the suite `ready_smoke (real verifier)`, not end-to-end model
  verified. Keep its calibrated Pass@1 and zero-tool behavior separate from
  all agentic/scaffold scores; preserve raw model completions for audit.
- Next: finish repository-suite gold/null/repeat gates, then run the predeclared
  Ornith smoke and concurrency ladder.

## 2026-08-14 — Add GLM 5.3 to the model matrix

- Context: codex-pool now advertises `zai/glm-5.3`; Pi's existing route uses
  the `stg04.local:8989` proxy while the generated direct localhost route is
  unreachable from this client.
- Change: added GLM 5.3 limits, reasoning, and zero pool cost metadata to
  `configs/models.yaml`; installed the proxy-adapted generated Pi provider list
  at `~/.pi/agent/models.json` with directory/file modes 700/600.
- Evidence: RED then GREEN
  `test_repo_models_include_glm_53_pool_metadata`; all 13 usage-capture tests
  pass. The existing Anthropic route returned HTTP 200, runner reachability is
  true, and a minimal no-tools Pi prompt on `zai/glm-5.3:xhigh` returned `OK`.
  Full pytest reached 300 passes; its six failures are the two documented
  baseline failures plus four tests from the unrelated untracked SWE PolyBench
  worktree files.
- Decision: preserve the required proxy host/path instead of overwriting it
  with unreachable localhost URLs. Treat the generated pool list as the source
  of healthy providers and retain its advertised zero GLM 5.3 pool pricing.
- Next: use `zai/glm-5.3` in a benchmark smoke before launching a matrix.

## 2026-08-14 — Integrate SWE-PolyBench Verified pilot38

- Context: the frozen 38-task repository pilot had immutable image digests and
  a pinned dataset but no Cospa execution path or verifier evidence.
- Change: added a Harbor suite that starts from each digest-pinned image,
  resets the repository baseline in a derived image, withholds test/gold
  patches until their Harbor phases, replays the captured model patch after
  hidden tests, and scores F2P/P2P using isolated pinned upstream parsers.
  Java uses the image's Maven cache offline. Setup now fails early when Docker
  or Buildx is unavailable for Harbor's phase-network sidecar.
- Evidence: RED then GREEN `tests/test_swe_polybench.py` (10 tests), including
  real parser-output fixtures for Python, Java, JavaScript, and TypeScript;
  setup's shell test passes 17 assertions. A real Harbor 0.16.1 Gson gate over
  the pinned image produced null 4/6 incorrect with a zero-byte model patch and
  gold 6/6 resolved with a 1,460-byte patch, both verifier runs offline. Full
  pytest reports 310 passed plus the two documented baseline failures; the
  shell suite likewise has only the existing check-models fixture failures.
- Decision: call the adapter ready with representative end-to-end verifier
  evidence, but retain the suite's blocked gold/null status until the other 37
  selected tasks and repeat gate pass. Do not report an Ornith score yet.
- Next: validate gold/null across all 38 selected images, then run repeats and
  the predeclared Ornith smoke if the verifier gate remains clean.

## 2026-08-14 — Make PolyBench dataset loading thread-safe

- Context: the first concurrency-4 real verifier batch raced Python's
  process-global CSV field limit, causing large dataset rows to fail parsing.
- Change: serialize field-limit adjustment, full CSV consumption, and limit
  restoration with a module lock.
- Evidence: the new 16-load, 8-worker RED test reproduced `_csv.Error`; all 11
  PolyBench tests now pass. Full pytest reports 311 passed and only the same two
  documented unrelated baseline failures.
- Decision: discard the interrupted batch evidence and restart validation from
  a clean directory; no task verdict from the raced run is accepted.

## 2026-08-14 — Parse raw Harbor JavaScript verifier output

- Context: the real PolyBench batch produced complete Mocha JSON, but the
  pinned upstream JavaScript parsers returned zero tests because they expect
  their Docker runner's trailing `Container exited` framing sentinel.
- Change: recreate that runner boundary only when Harbor's raw verifier output
  lacks it, without changing the test command or test content.
- Evidence: the RED test failed for all three selected JavaScript parser
  mappings and is GREEN. Re-parsing real Harbor artifacts recovers valid
  null/gold outcomes for two Serverless and two Svelte tasks (13, 195, 770,
  and 2,748 tests). Full pytest reports 314 passed and only the two documented
  baseline failures.
- Decision: preserve the pinned upstream parsers rather than forking their
  result logic; normalize only the execution-wrapper framing Cospa replaced.
- Next: rerun the 38-task null/gold gate with corrected parser framing.

## 2026-08-14 — Fail closed on PolyBench submodule edits

- Context: code-server's pinned image intentionally carries a dirty VS Code
  submodule baseline. Root `git diff` falsely attributed that baseline to a
  no-op agent and cannot faithfully replay later edits inside the submodule.
- Change: hash each image's non-ignored submodule baseline in the derived image,
  omit unchanged submodule dirtiness from the root model patch, and reject any
  agent episode that changes nested repository state.
- Evidence: RED then GREEN PolyBench materialization tests. On the real pinned
  code-server image, null now has a zero-byte patch and gold resolves with 282
  of 283 parsed tests passing. A deliberate nested edit is rejected before
  hidden tests with `submodule_patch_capturable=false`. Full pytest reports 314
  passed and only the two documented baseline failures.
- Decision: preserve upstream images' intentional nested working trees, but
  never silently discard or misattribute nested model changes.
- Next: finish and classify the complete PolyBench gold/null gate.

## 2026-08-14 — Preserve PolyBench's pinned MUI test reporter

- Context: both selected MUI images contain an untracked custom Mocha reporter
  required by their declared test commands; cleaning the agent repository
  correctly removed it but left the verifier unable to run.
- Change: copy the digest-pinned reporter to `/opt/cospa` before repository
  cleanup and set `NODE_PATH` so its unchanged code resolves the image's pinned
  Mocha dependency without network access.
- Evidence: RED then GREEN materialization test. Real Harbor null/gold pairs on
  the two pinned MUI images transition 5/6 to 6/6 and 51/52 to 52/52, with
  zero-byte null patches. Full pytest reports 315 passed and only the two
  documented baseline failures.
- Decision: preserve only the explicitly referenced evaluator helper outside
  the agent repository; continue deleting unrelated untracked image files.
- Next: retain both MUI tasks in the repeat-qualified PolyBench subset.

## 2026-08-14 — Qualify the SWE-PolyBench pilot28

- Context: the outcome-blind 38-task screen included pinned images whose
  verifier environments could not run hermetically or whose oracle patches
  regressed declared P2P tests; target-model outcomes were never consulted.
- Change: retain the 28 tasks that satisfy the null/gold contract, record all
  ten exclusions and their reasons in the runtime manifest, bump the suite to
  version 0.2, and remove excluded image requests from the runnable image lock.
- Evidence: RED then GREEN qualification-manifest tests. Across three
  observations per condition, all 84 Harbor no-op runs were incorrect with
  zero-byte model patches and all 84 oracle runs resolved with non-empty
  patches under the no-network verifier. The two final complete 28-task passes
  finished 28/28 in 683.339 and 658.264 seconds. Full pytest reports 316 passed
  and only the two documented unrelated baseline failures.
- Decision: promote the multilingual 28-task subset to `ready_smoke`; do not
  weaken verifier isolation or retain tasks whose gold patch is not replayably
  correct in the pinned image.
- Next: qualify the remaining repository and feature candidates before running
  Ornith.

## 2026-08-14 — Survey domain candidates for wide harness-comparison panel

- Context: strategy shift toward a Cospa-owned multi-domain panel
  (`cospa_wide`) whose primary axis is adapter/scaffold comparison;
  `docs/EVALS.md` repo-suite review runs in parallel and keeps adoption
  authority.
- Change: add `docs/EVALS-WIDE-PANEL.md` surveying GPU-kernel/low-level
  (KernelBench, TritonBench, SWE-Perf), data science (DABstep, DSBench),
  visualization (MatPlotBench, PandasPlotBench, Plot2Code, ChartMimic),
  text manipulation (gap; propose authored mini-corpus), and fresh
  repo/feature context (SWE-Lancer, R2E-Gym, Commit0, LiveSWEBench),
  each against the EVALS.md hard gates, plus a strawman ~120-150-slot
  panel and sequencing plan.
- Evidence: sources fetched 2026-08-14 (KernelBench/TritonBench/SWE-Perf/
  DSBench/PandasPlotBench READMEs, arXiv abstracts, DDG-HTML discovery);
  all unverified quantities labeled Unknown/pilot-required in the doc.
  Docs-only change; re-read end-to-end, no test run required per AGENTS.md
  verification tiers.
- Decision: KernelBench + DABstep are leading adopt candidates; viz domain
  requires a Cospa deterministic grader; text-manipulation domain must be
  authored; EVALS.md Decision table intentionally untouched.
- Next: merge with the repo-suite bake-off into one portfolio decision in
  docs/EVALS.md; pin host GPU inventory; build the deterministic plot
  grader and KernelBench null/gold screen first.

## 2026-08-14 — Pin tri-model task discovery

- Context: use the two independent local serving lanes plus fast Codex Spark to
  broaden candidate-task review without allowing reviewer-model outcomes to
  select tasks around their own strengths.
- Change: add `configs/task_discovery_panel_v1.json` and make its outcome-blind
  review/adjudication boundary normative in `docs/EVALS.md`. Muse-Glimmer,
  DeepSeek V4 Flash 0731, and `codex/gpt-5.3-codex-spark` review identical
  public-only packets; executable qualification remains authoritative.
- Evidence: Muse and DeepSeek each returned HTTP 200 through the local pool;
  Spark returned the requested `OK` in 2.084 seconds. JSON parsing,
  `git diff --check`, and an end-to-end reread of the changed docs/config pass.
- Decision: all three review every calibration candidate. Scaled batches rotate
  primary/validator roles and use the third model for disagreements/high-risk
  tasks. No model vote can waive pinned artifact isolation, three clean null
  and gold observations, regression checks, timing, or legal gates.
- Next: build a small review runner and calibrate the three reviewers on an
  outcome-blind block from KernelBench-Verified, DABstep, and optional DS-1000
  Matplotlib without delaying already-qualified target-model smokes.

## 2026-08-15 — Narrow expansion discovery to DABstep

- Context: the three-model source calibration completed, but a dedicated GPU
  cannot be assumed for kernel evaluation and another one-shot generation
  anchor is unnecessary.
- Evidence: DABstep received a unanimous pilot recommendation. Source-review
  walls were 9.573 seconds for Codex Spark, 26.713 for Muse, and 38.282 for
  DeepSeek; all normalized reviews passed the value schema.
- Decision: select DABstep for task-level discovery; explicitly skip
  KernelBench-Verified for lack of a guaranteed evaluation GPU and DS-1000
  Matplotlib for overlap with existing one-shot coverage.
- Validation: task-discovery JSON parses, `git diff --check` passes, and the
  changed policy text was re-read. No code tests are required for this
  docs/config-only decision.
- Next: pin DABstep artifacts, review an outcome-blind task block with all
  three discovery models, and mechanically qualify any nominated tasks.

## 2026-08-15 — Bound concurrent runner trials

- Context: the restarted Muse and DeepSeek servers each expose 16 request
  slots, but the runner could only execute task trials serially.
- Change: add `--concurrency` to `harness/runner.py`; each worker owns one
  complete task trial including infrastructure retries, and the heartbeat now
  records configured and active concurrency. Document in-cell parallelism.
- Evidence: RED tests rejected `c=0` and observed only one active task at
  requested `c=3`; both pass after the change, including exact `k=2` work
  counts. A real BigCodeBench DeepSeek smoke ran two tasks concurrently and
  produced two native verifier verdicts (one resolved, one incorrect).
  Full pytest: 333 passed with only the two documented unrelated baseline
  failures in `test_check_models.sh` and Terminal-Bench newline handling.
- Decision: use one runner process per model/suite cell and keep aggregate host
  trial concurrency at or below 16 for the first campaign.
- Next: finish the Harbor-backed PolyBench concurrency smoke, then launch the
  matched `c=8` model cells.

## 2026-08-15 — Unblock target-model PolyBench trials

- Context: the first real PolyBench agent smoke failed before inference because
  Amazon Linux task images do not provide `apt-get`; successful reruns also
  exposed missing Harbor tool rollups and model/test patch conflicts mislabeled
  as retryable evaluator failures.
- Change: make Harbor agent bootstrap detect existing `curl` and support apt,
  dnf, microdnf, yum, and apk; recover per-tool counts, categories, errors, and
  message-bound wall timings from exported pi sessions; score an unapplied
  model patch as incorrect when the hidden test patch applied successfully.
- Evidence: RED tests reproduced unconditional apt, absent Harbor behavior, and
  the incorrect retry class. Targeted tests pass. Real `c=2` target-model
  smokes produced native verifier artifacts on both lanes: Muse resolved one
  of two tasks in 589.4/703.1 seconds; DeepSeek completed in 235.6/371.9
  seconds. DeepSeek emitted 42/36 tool calls and Muse 110/92, with tool types
  and inference/tool wall time recoverable from every session. Full pytest:
  333 passed with only the two documented unrelated baseline failures.
- Decision: accept the package bootstrap as fixed (integration test), treat
  hidden-test patch conflicts as model outcomes without retries, and use raw pi
  sessions as the authoritative Harbor behavior source.
- Next: launch BCB on both models at `c=8`, then matched PolyBench vanilla and
  devstack phases at `c=8` while recording GPU/queue telemetry.

## 2026-08-15 — Preserve Muse BigCodeBench final-answer budget

- Context: the first full `c=8` BCB phase was valid for DeepSeek (3/15) but
  invalid for Muse: the pool dropped SGLang chat-template kwargs, Muse spent
  the entire fixed 1,280-token cap in reasoning, and 10/15 final attempts had
  no textual completion after unnecessary retries.
- Change: pin a Muse-only BCB request override (`reasoning_effort: none`) in the
  model config, propagate and record protocol overrides, retain malformed raw
  provider responses, and make a reasoning-only successful HTTP response
  non-retryable. Keep the upstream 1,280-token cap unchanged.
- Evidence: direct pool probes showed chat-template kwargs produced 0 final
  characters at the length cap while `reasoning_effort: none` produced a final
  answer in 3.383 seconds. RED tests covered request propagation, manifest
  provenance, raw-response retention, and retry class. A real runner `c=2`
  smoke then produced textual completions for both tasks, one resolved and one
  incorrect. Full pytest: 335 passed with only the two documented unrelated
  baseline failures.
- Decision: exclude the original Muse BCB15 cell from scoring and rerun it in a
  fresh result root; retain the valid DeepSeek BCB15 cell.
- Next: rerun Muse BCB15 at `c=8`, then proceed to PolyBench vanilla only if all
  15 trials have textual completions and native verifier verdicts.

## 2026-08-15 — Make Harbor bootstrap portable across task images

- Context: fresh `c=8` PolyBench runs passed the Java-image bootstrap but failed
  on JavaScript images whose preinstalled NVM root is `/usr/local/nvm`; setup
  sourced `$HOME/.nvm`, and later shells selected Node 16 and could not find the
  Node 22 global `pi` command.
- Change: honor `${NVM_DIR:-$HOME/.nvm}` throughout setup/config/run commands,
  pin the NVM default and active shell to Node 22, classify Harbor trial
  `exception_info` as retryable infrastructure instead of a wrong answer, and
  flush runner heartbeats as interrupted before signal termination.
- Evidence: RED tests reproduced NVM-root, run-shell, hidden Harbor exception,
  and stale-heartbeat behavior. A real Muse trial on JavaScript task
  `mrdoob__three.js-14836` completed agent and native verifier phases in 435.85
  seconds with observed usage and 71 tool calls; its incorrect verdict is a
  genuine model outcome, not infrastructure. Full pytest: 337 passed with only
  the two documented unrelated baseline failures.
- Decision: preserve stopped/invalid cells under
  `results/validation/excluded-campaign-cells-20260815`; do not score them or
  resume their mixed retry artifacts.
- Next: add the separately labeled agentic BigCodeBench workspace suite, then
  start fresh vanilla and devstack cells for agentic BCB and PolyBench.

## 2026-08-15 — Adapt BigCodeBench for scaffold comparison

- Context: the requested experiment compares `pi_vanilla` and `pi_devstack`,
  while the existing official BigCodeBench arm intentionally bypasses both and
  therefore cannot answer the scaffold question.
- Change: add separately labeled `bigcodebench_hard_agentic`, reusing the same
  public pilot15 and pinned hidden evaluator while directing agents to implement
  `solution.py` under model-card sampling and normal tools. Keep official BCB
  results separate. Export the same sampling/max-token config into Harbor, and
  resolve relative trial session paths so generic runs retain behavior traces.
- Evidence: unit tests cover public-only materialization, suite/adapter
  distinctness, unchanged-starter rejection, native submission packaging, and
  model-card sampling. `BigCodeBench/15` passed native null/gold qualification
  for three of three repeats per condition. Real Muse and DeepSeek vanilla
  agents both edited the workspace and reached native verdicts; a final
  DeepSeek smoke recorded 25,020 tokens, five turns/tools, and 38.98/0.03
  seconds inference/tool time. Full pytest: 343 passed with only the two
  documented unrelated baseline failures.
- Decision: official `bigcodebench_hard_instruct` remains an orthogonal anchor;
  only `bigcodebench_hard_agentic` enters the vanilla/devstack matrix, and the
  two score namespaces never merge.
- Next: launch fresh `c=8` vanilla cells for agentic BCB15 and PolyBench28 on
  both models, validate all artifacts, then run matched devstack cells.

## 2026-08-15 — Fail closed on effective thinking-level drift

- Context: trace review found PolyBench manifests requested `xhigh`, while every
  copied Harbor pi session recorded `thinkingLevel: high`. The custom container
  model config propagated sampling but omitted model-specific
  `thinkingLevelMap`/`compat`, and case-sensitive model matching missed the host
  entries entirely.
- Change: match provider model IDs canonically, propagate thinking maps and pi
  compatibility settings into Harbor, and reject a trial as infrastructure
  before verification whenever observed session thinking differs from the
  requested level.
- Evidence: RED tests reproduced missing config and a requested-xhigh/observed-
  high session. A real DS4 Keras PolyBench smoke then recorded requested and
  observed `xhigh`, reached the native verifier, and resolved in 61.48 seconds.
  Full pytest: 345 passed with only the documented unrelated Terminal-Bench
  newline fixture failure.
- Decision: do not treat the completed PolyBench vanilla cells as xhigh or
  launch matched devstack yet; preserve them as high-thinking diagnostics and
  run controlled corrected ablations before interpreting model quality.
- Next: finish the trace disagreement audit, relabel the affected artifacts
  honestly, and run a true-xhigh disagreement panel before the full matrix.

## 2026-08-15 — Keep validation artifacts out of default scores

- Context: default `./view` merged c1 validation smokes and preflight trials into
  campaign token, cost, and costed-trial totals, producing rows such as 17/17
  costed trials for a 15-task BCB campaign.
- Change: hide `results/validation` and preflight paths alongside smoke/probe
  paths in the default view while preserving explicit `--all` visibility.
- Evidence: a RED viewer fixture showed validation and preflight rows leaking;
  all 50 viewer tests pass. Against live artifacts, default `results` output is
  now exactly equal to `--results-dir results/runs` across all six campaign
  rows, including task, token, and costed-trial counts.
- Decision: scored campaign rows come from `results/runs`; qualification and
  diagnostic artifacts remain durable and available only through `--all`.
- Next: complete controlled thinking and test-overlap sensitivity checks before
  starting the corrected devstack matrix.

## 2026-08-15 — Remove Harbor's per-task Pi network install

- Context: five PolyBench outcomes were infrastructure failures because task
  images without preinstalled Node/NVM repeatedly cloned NVM and installed pi
  over public DNS; retries on MUI stalled or failed before model execution.
- Change: mount the selected host NVM version read-only at
  `/opt/coding-eval-pi-runtime` for every Pi/little-coder Harbor arm, activate
  its node/CLI directly in setup, config, devstack, and run shells, and retain
  the portable NVM/package-manager path only as a fallback.
- Evidence: RED tests required a runtime mount for vanilla plus runtime/profile
  mounts for devstack and verified native/fallback activation. A real DS4 MUI
  trial that previously failed setup completed agent and native verifier phases
  in 255.75 seconds, with requested and observed `xhigh` and no infrastructure
  failure. Full pytest: 345 passed with only the documented unrelated
  Terminal-Bench newline fixture failure.
- Decision: the mounted tree contains only the immutable selected node/global
  package runtime, is read-only, and exposes no host settings, sessions, or
  credentials to benchmark containers.
- Next: finish the true-xhigh disagreement panel, then use the mounted runtime
  for any corrected full vanilla/devstack cells.

## 2026-08-15 — Support Pi on legacy-glibc task images

- Context: Tailwind 853 uses glibc 2.23, which cannot execute the selected host
  Node binary; the initial read-only runtime mount therefore still failed
  before pi despite removing network installation.
- Change: mount a SHA-pinned Node 22.14.0 glibc-2.17 compatibility build beside
  the host pi package, select it only when the primary Node cannot execute, and
  teach setup to download and verify the exact unofficial-builds archive.
- Evidence: RED tests covered the compatibility mount, activation branch, and
  setup URL/SHA pin. A real DS4 Tailwind 853 retry then ran pi, recorded
  effective `high`, reached the native verifier, and completed in 109.66
  seconds without infrastructure failure. Full pytest: 346 passed with only
  the documented unrelated Terminal-Bench newline fixture failure.
- Decision: keep the modern host runtime first; use the compatibility binary
  only as the interpreter for the same read-only pi package on legacy images.
- Next: rerun Muse's two remaining infrastructure tasks only after its server
  returns; GPU0 is currently occupied by an unrelated Qwen benchmark and the
  local model pool reports no live Muse account.

## 2026-08-15 — Replace Muse with Qwen 3.8 27B

- Context: the local GPU0 pool retired Muse Glimmer 30B and now serves Qwen 3.8
  27B. Historical Muse result labels remain unchanged; only the active model
  catalog and run example move to Qwen.
- Change: record the pool's 262,144-token context, 131,072-token output limit,
  pricing, reasoning support, and the official thinking-mode sampling profile.
  Preserve `presence_penalty` in safe telemetry so manifests and Harbor receive
  the complete profile. Refresh the current user's generated pool providers
  while retaining the established `stg04.local:8989` proxy topology.
- Evidence: both old and newly generated credentials completed authenticated
  Qwen chat requests through the existing proxy (HTTP 200, served model
  `qwen38-27b-nvfp4-mtp`); a fresh Pi process listed `local/Qwen3.8-27B` and
  returned `OK`. RED tests failed on missing Qwen metadata/profile, then the
  targeted set passed 7/7. Full pytest passed 345 tests; only the two documented
  unrelated shell-port and Terminal-Bench newline fixture failures remain.
- Decision: use the model-card thinking profile (`temperature=1.0`,
  `top_p=0.95`, `top_k=20`, `min_p=0`, `presence_penalty=0`, and
  `repetition_penalty=1`) for agentic comparisons, and continue disabling
  reasoning for the 1,280-token BigCodeBench Instruct protocol.
- Next: validate effective xhigh control and run one Qwen agentic BigCodeBench
  and PolyBench smoke before launching the full scaffold matrix.

## 2026-08-15 — Qualify Qwen 3.8 for scaffold evaluation

- Context: Qwen needed real-artifact validation of the generated provider route,
  sampling metadata, thinking control, Harbor container path, and native graders
  before replacing Muse in any full campaign.
- Evidence: at observed `xhigh`, vanilla Qwen resolved BigCodeBench/15 in 48.5
  agent seconds (7 turns, 9 tools, 3,511 input / 7,170 output / 36,992 cached
  tokens) and resolved PolyBench `apache__dubbo-3855` with all 17 target tests
  passing in 723.8 wall seconds (63 turns, 73 tools, 36,868 input / 27,677
  output / 2,083,392 cached tokens). Both traces report served model
  `qwen38-27b-nvfp4-mtp`, explicit thinking blocks, and an observed `xhigh`
  level change.
- Change: treat `results/qualification/` as a diagnostic root hidden from the
  default score table, while retaining it under `view --all`; the two Qwen
  smokes now stay durable without contaminating campaign rows.
- Validation: the viewer RED test exposed qualification rows in the default
  table, then passed after the filter change; all 50 viewer tests pass. Full
  pytest passes 345 tests with only the same two unrelated shell-port and
  Terminal-Bench newline fixture failures.
- Decision: the Qwen vanilla path is qualified for a full xhigh scaffold cell.
  Keep these `k=1` passes as plumbing evidence, not a capability estimate.
- Next: run the full Qwen vanilla cells at the validated concurrency, then the
  matched devstack cells without mixing qualification artifacts into scores.

## 2026-08-15 — Keep headless devstack profiles deterministic

- Context: the DS4 PolyBench devstack c=16 cell repeatedly failed before model
  execution because the default Harbor path mounted mutable workstation
  settings and Camoufox attempted to fetch its browser inside no-network task
  containers. The earlier qualification's explicit sanitized-profile override
  had hidden this default-path regression.
- Change: derive a content-addressed settings snapshot from the canonical host
  profile, preserve all normal devstack packages, and disable only Camoufox and
  pi-zentui resources through Pi's documented package filters. Explicit pinned
  profile overrides remain untouched.
- Evidence: the RED test showed the original workstation settings mounted
  directly. The GREEN unit test verifies deterministic filtering without
  mutating the source profile. A real DS4 `apache__dubbo-3855` PolyBench
  devstack retry completed 29 model responses in 544.9 seconds and passed all
  17 native tests, with no Camoufox, fetch, or agent exception signatures.
  Full pytest reports 346 passed with only the two documented unrelated
  shell-port and Terminal-Bench newline fixture failures.
- Decision: preserve the interrupted artifacts under `results/validation/` and
  remove their 30 orphaned Harbor containers. Use the sanitized default profile
  for corrected PB campaigns; the profile remains behaviorally distinct from
  vanilla without requiring browser/TUI initialization in headless containers.
- Next: rerun the invalid DS4 PolyBench devstack cell and the full Qwen
  vanilla/devstack reasoning grid sequentially at client c=16.

## 2026-08-15 — Prepare proprietary-model comparison cells

- Context: add a curiosity comparison for GPT-5.6 Luna, Terra, Sol, and GLM 5.3
  on the same agentic BigCodeBench/PolyBench vanilla and devstack protocols at
  client c=2, using each model's highest configured reasoning level.
- Change: add explicit GPT-5.6 catalog limits, record the GLM reasoning-map
  source, accept Pi's `max` thinking level, and route non-Chat-Completions
  reachability checks through Pi's native provider implementation instead of
  falsely probing every provider at `/chat/completions`.
- Evidence: all four existing configured routes returned `OK` with authenticated
  Pi requests and exact served identities (`gpt-5.6-{luna,terra,sol}` and
  `glm-5.3`). Session traces recorded `max` for all GPT variants and `xhigh` for
  GLM; its provider map translates `xhigh` to `max`. Direct localhost:8989
  controls failed (`fetch failed` / connection error), so the established
  `stg04.local:8989` topology remains unchanged. All 18 targeted tests pass;
  full pytest reports 352 passed with the same two documented unrelated
  shell-port and Terminal-Bench newline fixture failures.
- Decision: use `max` for Luna/Terra/Sol and `xhigh` for GLM 5.3. Preserve the
  preflight traces under `results/qualification/`, which remains excluded from
  default scores. Catalog cost stays zero because the generated pool entries
  advertise zero client-side pricing; compare token counts directly rather than
  inferring external billing.
- Next: launch 16 sequential cells (four models x two suites x two adapters) at
  c=2 with fail-closed manifest, route, profile, and thinking checks.

## 2026-08-15 — Freeze the Pareto evaluation campaign

- Context: pilot15 BCB and pilot28 PolyBench scores had 15–22 point Wilson
  half-widths and concentrated their apparent discrimination in a few tasks;
  the original runtime pilot was not a ranking-quality matrix.
- Evidence: durable DS4 c=8 cells measured 24.5 seconds elapsed for BCB Instruct
  pilot15, 5m25s for BCB Agentic pilot15, and 2h05m for PolyBench pilot28.
  Recomputed task overlap shows no DS4 devstack `xhigh` gain over `off` on BCB
  despite about 3.9x estimated cost, while Muse had seven one-way PolyBench wins
  over DS4 on the fixed panel.
- Decision: fix DS4 + `pi_vanilla` + c=8 + k=1 as the campaign baseline, use
  `high` thinking for new agentic baselines, expand through nested outcome-blind
  panels, prefer executable headline graders, and defer SWE Atlas because it
  requires an LLM judge. `docs/PARETO-CAMPAIGN.md` records the measured
  projections and paired cost/discrimination promotion gates.
- Next: expand BCB to full148, finish Multi-SWE qualification, freeze
  Terminal-Bench Pareto20 and PolyBench balanced64/96, then qualify FeatureBench
  and the low-cost DABStep/SWE-Explore diagnostic bake-off.

## 2026-08-15 — Qualify Multi-SWE Flash hermetic25

- Context: the outcome-blind 30-task Multi-SWE Flash screen had pinned images
  but no local null/gold evidence, and unqualified tasks could turn dependency
  or flaky-test failures into model failures.
- Change: add the Harbor suite with construction-artifact removal, hidden test
  injection after patch capture, pinned upstream parsers for all seven
  languages, transition/P2P scoring, and a distinct repeat-qualified
  `multi_swe_bench_flash_hermetic25` suite ID. Model patches that conflict with
  hidden tests are classified as incorrect rather than verifier failures.
- Evidence: all 90 no-op observations were unresolved with empty patches. The
  gold screen resolved 78/90 observations; three Java tasks consistently needed
  uncached Maven/Gradle artifacts and two Vue tasks had unrelated timing-test
  flips. After those five outcome-blind exclusions, all 75/75 retained gold
  observations resolved and all 75/75 retained null observations failed under
  no-network verification. Fourteen suite tests and all ten runtime-pilot tests
  pass; full pytest reports 357 passed with the two documented unrelated shell
  and Terminal-Bench newline failures.
- Decision: promote the retained 25 tasks for DS4 `pi_vanilla` c=8 screening,
  report their 4 C / 4 C++ / 5 Go / 1 Java / 5 JavaScript / 4 Rust /
  2 TypeScript distribution, and never label them as the official Flash300
  score.
- Next: run the DS4 baseline after BCB registration is complete, then use paired
  outcomes to decide whether this suite earns scaffold expansion.

## 2026-08-15 — Expand BigCodeBench to hermetic143

- Context: pilot15 was too coarse for ranking, but exposing all 148 tasks without
  qualification would convert benchmark network/data assumptions into incorrect
  model outcomes under Cospa's offline verifier.
- Change: project all 148 public Instruct prompts without hidden tests or
  solutions, add distinct Instruct hermetic143, Agentic hermetic143, and nested
  outcome-blind Agentic Pareto60 suite IDs, and reuse the original Instruct
  protocol-override key for the expanded no-tool arm.
- Evidence: the first no-network gold screen passed 143/148 tasks. Excluded
  `/101`, `/1012`, `/177`, `/590`, and `/655` require external URLs or missing
  NLTK state. Across the retained set, 429/429 gold observations passed and
  429/429 null observations failed. A DS4 `pi_vanilla` high-thinking c=8 smoke
  produced eight authoritative native verdicts in about 61 seconds campaign
  elapsed (0/8 resolved, 335 summed task seconds, no infrastructure/verifier
  failures); all traces recorded the correct served model and an observed
  `thinking_level_change` to `high`.
- Decision: use Pareto60 for broad scaffold screening and hermetic143 for DS4 or
  promoted finalists. Keep full148 only as a public source projection and never
  report hermetic143 as the official complete score.
- Next: run the complete DS4 Pareto60 baseline, then expand to hermetic143 if the
  score and paired-discrimination gates remain useful.

## 2026-08-15 — Qualify SWE-PolyBench balanced64

- Context: pilot28 was too coarse and language-skewed for routine ranking, while
  the outcome-blind candidate96 gold screen left only nine viable Java tasks.
- Change: freeze and pin candidate96, a 32-task adaptive Java extension, and the
  final seven eligible small/medium Java candidates; add a deterministic
  finalizer, qualification ledger, and distinct
  `swe_polybench_verified_balanced64` suite with 16 tasks per language.
- Evidence: 54 new candidates passed their first oracle observation and all
  108/108 repeat oracle observations. Together with pilot28 this yielded 82
  gold-stable candidates. The selected panel passed 192/192 gold observations
  and failed 192/192 null observations; all 108 newly run no-op patches were
  empty and unresolved. `tests/test_swe_polybench.py` passes 21/21. Full pytest
  reports 363 passed with only the same pre-existing `check-models.sh` skip
  accounting and Terminal-Bench YAML-newline failures.
- Decision: promote balanced64 for the DS4 c=8 routine baseline, disclose its
  seven-Gson Java and nine-MUI TypeScript concentrations, and keep candidate96
  as a support artifact rather than fabricate a balanced96 score from the
  22 Java / 22 JavaScript / 21 Python / 17 TypeScript gold-stable pools.
- Next: freeze Terminal-Bench Pareto20, qualify FeatureBench and the low-cost
  diagnostic bake-off, then launch the matched DS4 baseline wave.

## 2026-08-15 — Normalize Terminal-Bench YAML prompt chomping

- Context: prompt extraction depended on whether PyYAML was installed: the
  fallback added a newline even for YAML's `|-` strip-chomping indicator.
- Change: make the dependency-free parser honor strip versus clip chomping and
  align the real materialization assertion with YAML semantics.
- Evidence: the new fallback parity test is RED before the fix; all 32
  Terminal-Bench tests pass afterward. Full pytest reports 365 passed with only
  the unrelated `check-models.sh` shell-fixture failure remaining.
- Decision: keep PyYAML optional while requiring identical prompt bytes for the
  literal block styles used by the pinned Core tasks.
- Next: freeze and smoke the Terminal-Bench Pareto20 panel.

## 2026-08-15 — Freeze Terminal-Bench Pareto20

- Context: Core 0.1.1 had an immutable official80 manifest but no reproducible
  routine panel or DS4 cost/utility measurement; the existing pilot8 also
  contained legacy tasks Harbor 0.16 could not migrate directly.
- Change: register frozen pilot8 and outcome-blind Pareto20 suite IDs; preserve
  all pilot tasks, stratify Pareto20 over nine capability categories, 5 easy /
  9 medium / 6 hard tasks, and 15 short / 3 medium / 2 long timeout buckets.
  Convert unsupported `solution.yaml` command sequences only in migration
  scratch copies and supply fixed 2-CPU / 8-GiB / `/tests` Compose defaults
  without modifying the pinned vendor checkout.
- Evidence: the corrected DS4 + `pi_vanilla` + high-thinking c=8 smoke resolved
  3/8 in 10m31s elapsed (37m42s summed task wall): three resolved, one incorrect,
  four official agent timeouts, and zero infrastructure failures. Five tasks
  exported token traces with $0.0157 partial estimated cost. All 34 focused
  Terminal-Bench tests and the full 368-test pytest suite pass.
- Decision: promote Pareto20 to the matched baseline wave and report timeout
  outcomes separately as `budget_exhausted`. Do not treat its linear 26m17s
  projection as clean throughput because two unrelated c=2 repository workers
  overlapped the smoke; remeasure Pareto20 without host contention.
- Next: qualify FeatureBench's campaign tier before launching the shared DS4
  baseline wave.

## 2026-08-15 — Make Harbor devstack packages cross-image safe

- Context: Luna PolyBench devstack completed 26/28 trials, but the fail-closed
  campaign guard quarantined two pre-model failures. `coder__code-server-6278`
  could not load host-native `pi-smart-fetch`/`wreq-js`, while
  `tailwindlabs__tailwindcss-853` tried to install a missing Camoufox package
  through the intentionally blocked agent network.
- Change: sanitize the container's private settings copy after selecting its
  compatible Node runtime and before `pi list`. Remove Camoufox, smart-fetch,
  and pi-zentui package entries entirely; empty resource filters are insufficient
  because Pi can still materialize a missing configured package. The canonical
  workstation settings and mounted package tree remain untouched.
- Evidence: both RED tests failed before the sanitizer and all 36 focused Harbor
  tests pass afterward. The two preserved invalid attempts remain under
  `results/validation/`; resume skipped the other 26 durable trials and reran
  only the affected tasks. Both retries exited Pi normally with observed Luna
  usage and no package/native errors. Code-server ran 283 native tests in 907.2
  seconds; Tailwind completed in 251.6 seconds. Their unresolved verdicts are now
  legitimate model outcomes, yielding a complete Luna devstack score of 7/28.
  Full pytest reports 379 passed with only the pre-existing shell-fixture failure.
- Decision: classify package installation and native-extension load errors as
  infrastructure, never model misses. Keep the devstack scaffold's portable
  packages while excluding browser/TUI/native-fetch facilities that cannot be
  used in no-network benchmark images. `~/devstack` commit `4c1dff5` adds the
  reusable generator and deployment guide for this boundary.
- Next: resume the proprietary c=2 matrix at Terra, then Sol and GLM 5.3,
  preserving Luna's completed 4/15, 4/15, 11/28, and 7/28 cells.

## 2026-08-15 — Stop retrying Harbor agent deadlines

- Context: the FeatureBench c=8 baseline exposed that Harbor
  `AgentTimeoutError` outcomes were classified as retryable infrastructure,
  spending another full one-hour episode and obscuring capability-budget
  exhaustion.
- Change: classify Harbor agent deadlines as `budget_exhausted` with exit code
  124, skip the benchmark verifier, and do not retry them. Other Harbor agent
  exceptions remain retryable infrastructure failures.
- Evidence: RED then GREEN
  `test_retry_does_not_retry_harbor_agent_budget_exhaustion`; 36 focused runner
  and Terminal-Bench tests pass. Full pytest reports 380 passed with only the
  pre-existing `test_check_models.sh` shell-fixture failure.
- Decision: an agent safety-wall hit is a measured capability-budget outcome,
  not a transport retry. Preserve timeout rates separately from incorrect
  native verifier outcomes.
- Next: use the corrected classification for the remaining Pareto baseline
  suites and report the already-running FeatureBench timeout from its Harbor
  artifact.

## 2026-08-16 — Reclaim stale Harbor networks before campaigns

- Context: overlapping PolyBench/FeatureBench campaigns accumulated 15 empty
  Compose networks and exhausted Docker's predefined address pools. Twenty-four
  Terra and 21 Qwen PolyBench trials failed before container startup; their
  valid sibling trials were preserved and the failures quarantined rather than
  scored.
- Change: add a Harbor-suite runtime preflight before task concurrency starts.
  It inspects Docker networks and removes only unattached
  `workdir__*__env_default` networks older than five minutes. Active endpoints,
  recent networks that may still be starting, unrelated Compose projects, and
  all non-Harbor networks are preserved. Docker inspection failures remain
  best-effort because Harbor startup is still the fail-closed authority.
- Evidence: both RED tests failed before implementation. All 44 focused Harbor,
  runner, and reachability tests pass afterward. A live disposable network was
  reclaimed by exact ID and verified absent. Full pytest reports 382 passed with
  only the pre-existing `test_check_models.sh` shell-fixture failure.
- Decision: do not use global `docker network prune`, remove active networks, or
  restart the daemon during campaigns. One age-gated preflight per Harbor runner
  prevents historical leakage from consuming the finite pool without racing
  concurrent Compose startup.
- Next: finish the salvaged Terra and Qwen PolyBench retries, then resume their
  queues; every subsequent Harbor cell will run the automatic preflight.

## 2026-08-16 — Qualify FeatureBench Lite Pareto12

- Context: FeatureBench's official Lite30 split was pinned but mixed four Level
  2 rows without released gold with Level 1 rows that could fail or flake in an
  offline verifier. Running all 30 as model misses would invalidate the score.
- Change: add the Harbor-backed FeatureBench suite, full outcome-blind Lite30
  candidate manifest and image lock, deterministic finalizer, and distinct
  `featurebench_lite_pareto12` panel. Hidden tests, test patches, gold patches,
  and the unmasked source repository remain unavailable during the agent phase;
  verdicts report binary resolution and F2P partial credit separately.
- Evidence: 21/26 Level 1 rows passed a first oracle screen. Pareto12 selects 12
  tasks across 11 repositories using only repeated verifier validity,
  repository coverage, and verifier wall time; 36/36 gold observations pass and
  36/36 null observations fail offline. The DS4 `pi_vanilla` high-thinking c=8
  stress run plus isolated SymPy transport repair produced 2 resolved, 9
  incorrect, 1 budget-exhausted, and 0 unresolved infrastructure outcomes. The
  11 native verdicts averaged 0.645 F2P pass rate (median 0.771). Fifty focused
  FeatureBench/runner/Terminal-Bench tests pass; the full-suite result is noted
  below.
- Decision: use Pareto12 as a milestone feature panel, not an official Lite30
  score. Defer Fast100 and broader Lite claims until new rows pass the same
  repeated no-network gate. The raw 2h40m c=8 stress run and $1.02 trace-priced
  retry cost are conservative infrastructure evidence, not clean throughput.
- Next: compare DABStep with SWE-Explore for the low-cost diagnostic slot, then
  begin the mechanically qualified DS4 baseline wave.
- Validation: full pytest reports 382 passed with only the pre-existing
  `test_check_models.sh` shell-fixture failure.

## 2026-08-16 — Select SWE-Explore Verified12 diagnostic

- Context: the Pareto campaign required an executable, outcome-blind 12+12
  DABstep/SWE-Explore bake-off and a grader-provenance audit before adding a
  low-cost non-coding diagnostic.
- Change: freeze one mechanically valid Verified-derived task from each of 12
  Python repositories, pin the official SWE-Explore dataset, evaluator, issue
  projection, and immutable base-commit snapshots, and register
  `swe_explore_verified12`. Agents emit at most five ranked regions while
  ground truth remains outside the sandbox. The viewer now reports task-macro
  weighted core coverage separately from pass rate and counts malformed
  diagnostic outputs as zero rather than silently dropping them.
- Evidence: 36/36 pinned-oracle observations scored 1.0 and 36/36 null
  observations scored 0.0. The DS4 `pi_vanilla` high-thinking c=8 run scored
  0.0968 panel-macro weighted core coverage with core-line hits on 10/12 tasks,
  132-second mean task wall time, 170,709 mean tokens, and no infrastructure or
  verifier failure. DABstep's third-party public-gold Harbor wrapper uses one
  deterministic official-derived scorer; its first ten completed provisional
  trials resolved 3/10 while averaging 266 seconds and 274,091 tokens, so the
  two remaining long trials were canceled after the gate was decided.
- Decision: select SWE-Explore for the diagnostic slot. Keep weighted core
  coverage, any-core-line hit rate, and coding resolution distinct; DABstep
  qualification artifacts remain provenance evidence, not a scored Cospa
  suite. RED tests demonstrated both invalid-output scoring defects; 52 focused
  SWE-Explore/viewer tests pass. Full pytest reports 390 passed with only the
  pre-existing `test_check_models.sh` shell-fixture failure.
- Next: begin the qualified DS4 baseline screening wave, then run matched
  scaffold ablations on fixed panels.

## 2026-08-16 — Complete DS4 Pareto baseline wave

- Context: the breadth-first campaign required every mechanically qualified
  fixed panel under DS4, the declared baseline scaffold, c=8, and k=1 before
  spending budget on scaffold ablations or stochastic repeats.
- Evidence: BCB Instruct hermetic143 resolved 17/143 and BCB Agentic Pareto60
  resolved 22/60. Multi-SWE hermetic25 produced 9 resolved, 15 incorrect, and 1
  budget-exhausted; Terminal Pareto20 produced 11/7/2; PolyBench balanced64
  produced 15/47/2; FeatureBench Pareto12 produced 2/9/1 after the isolated
  SymPy repair. None of those 324 binary task outcomes remains an
  infrastructure or verifier failure. SWE-Explore Verified12 separately scored
  0.0968 task-macro weighted core coverage with 10/12 any-core-line hits and
  two invalid outputs counted as zero.
- Cost/timing: the four new completed cells used 7m10s c=8 elapsed for Instruct,
  30m36s for Multi-SWE, 17m24s for Terminal, and 59m49s for PolyBench. Across
  all retained baseline artifacts plus FeatureBench's repair, observed token
  volume is 309.7M and estimated cost is at least $2.75; Multi-SWE, Terminal,
  and PolyBench each lack token coverage for budget-expired tasks. Exact result
  roots and suite-specific task wall, token coverage, and costs are recorded in
  `docs/PARETO-CAMPAIGN.md` and remain durable under `results/`.
- Decision: all routine panels clear either the 10–70% binary utility band or
  the predeclared continuous-diagnostic exception. Never aggregate their 324
  binary outcomes into one capability score. Proceed to matched scaffold
  ablations on identical task IDs; reserve full-suite promotion and k>1 for the
  later gates.
- Validation: every expected result root contains exactly 143, 60, 25, 20, 64,
  12, or 12 authoritative task verdicts respectively. Model, adapter, thinking
  policy, protocol metadata, hidden-artifact boundary, and failure taxonomy
  were checked from each manifest/verdict pair; all newly queued runners exited
  zero.
- Next: run matched scaffold ablations, then select a fixed 32-task stability
  sentinel without using repeat outcomes.

## 2026-08-16 — Reject devstack at the matched Pareto60 gate

- Context: the 15-task pilot gave identical devstack `off` and `xhigh` solves,
  so no expensive scaffold arm could advance until a broader fixed panel tested
  both reasoning value and scaffold value against vanilla.
- Evidence: all four BCB Pareto60 arms have 60 authoritative verdicts and no
  infrastructure, verifier, or budget failure. Vanilla `high` resolved 22,
  devstack `off` 16, devstack `high` 19, and devstack `xhigh` 21. At matched
  `high`, devstack had four wins and seven losses versus vanilla (exact McNemar
  p=0.549; paired-bootstrap 95% effect interval -15 to +5 points) while costing
  8% more. Devstack `xhigh` versus `off` had eight wins and three losses
  (p=0.227; interval -1.7 to +18.3 points), but used 3.86 times the task wall
  and cost 3.27 times as much. Devstack `high` versus `off` was likewise
  inconclusive at five wins and two losses.
- Decision: retain `pi_vanilla high`. Devstack `xhigh` fails all predeclared
  promotion routes: less than +10 points, wins:losses below 3:1, interval
  crossing zero, and incremental cost above 1.5x. Do not spend Multi-SWE,
  Terminal, PolyBench, FeatureBench, or SWE-Explore budget on any devstack arm.
  Superpowers/Little Coder remain optional future studies, not active Cartesian
  axes.
- Validation: model, panel, task IDs, adapter, thinking level, and result
  completeness were checked across all 240 manifest/verdict pairs. Costs and
  timing were recomputed through the score viewer; paired outcomes used the 60
  exact shared task IDs and a seeded 50,000-resample bootstrap.
- Next: freeze and run the outcome-blind 32-task k=3 stability sentinel on the
  retained vanilla scaffold.

## 2026-08-16 — Freeze outcome-blind Stability32 sentinel

- Context: the matched scaffold gate retained only DS4 `pi_vanilla high`, but
  stochastic measurement required a cross-suite panel declared before any
  repeat outcomes and exact non-prefix task selection in the generic runner.
- Change: add repeatable `--task-id` selection with fail-closed membership and
  order preservation, plus a deterministic selector and frozen
  `configs/pareto_stability32_v1.json`. The panel allocates 8 BCB, 7 Multi-SWE,
  5 Terminal, 8 PolyBench, and 4 FeatureBench tasks across the predeclared
  strata for 32 tasks and 96 independent `k=3` attempts.
- Evidence: RED tests failed because the runner ignored explicit IDs and the
  frozen manifest did not exist. GREEN tests reproduce the byte-stable manifest,
  assert all allocations/languages/difficulties/categories/task types/repository
  constraints, and prove the runner executes only requested IDs in their given
  order. The focused three tests pass; full pytest reports 393 passes with only
  the pre-existing `test_check_models.sh` port-8080 fixture failure.
- Decision: use only mechanically qualified source manifests and seeded SHA-256
  ranks; neither baseline nor repeat outcomes may alter membership. Report mean
  pass probability and outcome-flip rate, never best-of-three as Pass@1.
- Next: commit this freeze before outcomes exist, run its five suite slices at
  c=8, validate all 96 authoritative attempts, and publish stability metrics.

## 2026-08-16 — Define fail-closed stability metrics

- Context: the score viewer deliberately summarizes repeated binary trials by
  task-majority, while the Pareto campaign requires mean pass probability and
  outcome-flip rate without any best-of-k interpretation.
- Change: add `scripts/analyze-stability-panel.py`. It validates the exact model,
  scaffold, thinking policy, task IDs, trial numbers, manifests, verdicts, and
  infrastructure taxonomy before calculating per-suite metrics. A task flips
  only when its independent outcomes contain both pass and fail; pairwise
  disagreement is retained as a secondary stability diagnostic.
- Evidence: RED tests failed because no analyzer existed. GREEN tests cover
  mixed/unanimous `k=3` outcomes, incomplete `k=2` and `k=3` boundaries, and
  missing plus non-authoritative result artifacts. All three focused tests pass;
  full pytest reports 396 passes with only the pre-existing
  `test_check_models.sh` port-8080 fixture failure.
- Decision: suppress metrics for any incomplete suite and return nonzero until
  every expected attempt is authoritative. Keep suite scores separate; any
  aggregate panel stability block is explicitly labeled not a capability score.
- Next: apply the analyzer to the queued 96-attempt Stability32 result root,
  repair only infrastructure failures, and publish the complete report.

## 2026-08-16 — Record k=1 token and cost envelope

- Context: the campaign needed its measured one-pass shape — task mix,
  concurrency, wall time, token split, and cost — recorded against the
  declared one-day, few-million-output-token budget.
- Change: extend the DS4 baseline table in `docs/PARETO-CAMPAIGN.md` with
  uncached-prompt, cache-read, and output-token columns, a 336-task totals
  row, and budget-envelope observations.
- Evidence: viewer JSON aggregation over the seven durable k=1 cells
  (143+60+25+20+64+12+12 tasks): 19h17m summed task wall, about 4h50m c=8
  campaign elapsed, 6.8M uncached prompt, 229M cache-read, 3.0M output
  tokens, and $2.45 plus the $0.30 SymPy repair. Re-read the changed section
  end to end.
- Decision: keep suite scores separate in the measured table; record that
  locally served vLLM/SGLang do not emit reasoning_tokens in usage (the
  zeros are a server limitation, not absent reasoning) while the DeepSeek
  official API reports them via completion_tokens_details.
- Next: turn this table into a script-generated per-run one-sheet report with
  links to raw traces; rerun BCB Instruct at matched thinking if it joins a
  headline geomean.

## 2026-08-16 — Add script-driven one-sheet run report

- Context: the campaign table format needed to become a repeatable per-run
  artifact that an agent can navigate from headline numbers to raw rollouts,
  with statistical extensions expected later.
- Change: add `scripts/generate-report.py`. It aggregates every
  (model, adapter, suite, thinking) cell across the given results roots via
  the score viewer, renders the summary table with token and cost columns,
  then per-cell drill-downs: per-task trial verdict links, summed task wall,
  pi-session trace links, failed-trial taxonomy, campaign elapsed, and trace
  coverage. All links are relative to the output file so the report relocates
  with the results tree.
- Evidence: RED tests failed before the script existed. GREEN tests cover the
  summary row, relative trial/trace links that resolve on disk, trace
  suppression when absent, failure taxonomy, token formatting, and cost
  rendering for a priced model. Full pytest reports 398 passes with only the
  pre-existing `test_check_models.sh` port-8080 fixture failure. The real
  report over nine DS4 result roots rendered 566 lines with 706/706 links
  resolving and 273 trace links at
  `results/reports/ds4-pareto-baseline-k1-and-stability32.md`.
- Decision: the report is generated output, not a committed artifact;
  regenerate with the script whenever results move. Keep the raw navigation
  footer describing manifest/verdict/out/jobs layout for agent consumption.
- Next: fold stability metrics into the report once the 96-attempt run is
  authoritative; consider elapsed-column promotion and per-language cuts.

## 2026-08-16 — Add per-cell speed and behavior table to report

- Context: the report's summary table showed cost and tokens but not the
  comparative speed/capability shape (turns, inference share, tool intensity)
  that the terminal viewer exposes.
- Change: add a `## Speed & behavior` section to
  `scripts/generate-report.py` rendering Avg/task, mean turns, LLM%, Tool%,
  mean tool calls, mean search calls, and behavior-trial coverage per cell
  from the viewer's existing aggregation.
- Evidence: RED test failed before the section existed; GREEN covers a
  behavior-observed manifest asserting each column value (turns 8.0, LLM%
  70.0%, Tool% 20.0%, calls 30.0, search 4.0, avg wall 2m00s). Full pytest
  reports 399 passes with only the pre-existing `test_check_models.sh`
  fixture failure. The regenerated real report shows the expected shape:
  FeatureBench at 180 turns / 91.8 calls versus BCB agentic at 6.9 turns /
  6.1 calls, SWE-Explore at 98.6% LLM time, and BCB Instruct rendering `-`
  for absent single-turn behavior data.
- Decision: dash-render cells without behavior telemetry rather than zero;
  keep the behavior table derived from the same viewer rows as the summary so
  the two tables cannot disagree.
- Next: fold k=3 stability metrics into the report; then the Phase D finalist
  decision.

## 2026-08-16 — Complete Stability32 k=3 sentinel

- Context: the frozen 32-task outcome-blind sentinel needed three independent
  DS4 `pi_vanilla high` attempts per task at c=8 to quantify stochastic
  outcome variance before any finalist promotion.
- Evidence: all 96 attempts are authoritative after one isolated Lightning
  trial-3 repair (transient endpoint connection error; rerun completed as an
  ordinary incorrect verdict in 2193s). Per-suite mean pass probability /
  flip rate: BCB 29.2%/12.5%, Multi-SWE 14.3%/28.6%, Terminal 40.0%/40.0%,
  PolyBench 8.3%/25.0%, FeatureBench 0.0%/0%. Panel diagnostic: 18.75% mean
  pass probability, 7/32 flip tasks (21.9%), 14.6% pairwise disagreement.
  The fail-closed analyzer exits zero with no issues; the regenerated
  one-sheet report resolves 707/707 links.
- Decision: 25/32 tasks were unanimous, validating k=1 as the routine
  protocol; flips concentrate in Terminal and repository-repair suites, so
  close paired decisions there deserve repeat evidence. No best-of-three is
  reported as Pass@1. Durable artifacts: the result root, the analysis JSON,
  and the one-sheet report under `results/`.
- Validation: analyzer complete=true over exactly the frozen manifest's 32
  task IDs x 3 trials with identity, thinking-policy, and failure-taxonomy
  checks; full metrics recorded in `docs/PARETO-CAMPAIGN.md` Phase D.
- Next: Phase D finalist promotion decisions on the retained k=1 protocol.

## 2026-08-16 — Promote BCB143 and Terminal80, defer PolyBench382

- Context: task #15 required applying the predeclared full-suite gates
  (frontier-changing uncertainty, external comparability, budget envelope)
  to each candidate finalist.
- Decision: promote BCB-Hard Agentic hermetic143 (protocol comparability
  with Instruct143; ±10 → ±7.8 points) and Terminal-Bench full80 (Pareto20's
  ±22-point interval cannot discriminate; Terminal's 40% k=3 flip rate makes
  breadth the correct spend). Defer PolyBench full382 ($5.48 and ~5.3M extra
  output tokens break the one-day/few-million envelope without a pending
  decision needing ±4 points). No Multi-SWE/FeatureBench/freshness promotion.
- Evidence: gate arithmetic from the measured baseline table, the Stability32
  flip rates, and the linear finalist projections already recorded in
  `docs/PARETO-CAMPAIGN.md`; total incremental spend about $0.33 and 1.5h.
- Next: execute the two promoted cells sequentially at c=8 k=1 with endpoint
  waits and durable roots, then aggregate the final campaign report and
  freeze the next routine matrix (task #16).

## 2026-08-16 — Freeze four-model pi_vanilla matrix

- Context: the campaign's next matrix compares real model behavior under one
  identical scaffold; `docs/HARNESS-EVAL.md` establishes that devstack's
  real-world improvements have no opportunity in these hermetic suites, so
  the comparison runs `pi_vanilla` only at a pinned harness version.
- Change: add `codex/gpt-5.3-codex-spark` (128K context, codex-pool thinking
  map, $0 pool accounting) to `configs/models.yaml`; define the Phase F
  matrix in `docs/PARETO-CAMPAIGN.md` (4 models x 7 frozen panels, thinking
  high except the Instruct protocol exception, c=8 k=1); pin pi 0.84.2 in
  `docs/HARNESS-EVAL.md`; record the pi version and adapter surface in the
  report header via `scripts/generate-report.py`.
- Evidence: all four endpoints reachable via the runner probe; spark metadata
  resolves (name, 128K window, reasoning) through `load_model_metadata`;
  20 focused report/reachability/sampling tests pass. No-RED rationale: the
  report change is a cosmetic generated-header line, and the models.yaml
  addition is configuration consumed by existing tested lookups.
- Decision: DS4's row reuses the five completed baseline cells and adds only
  the Phase E agentic143/full80 cells; ornith/spark/qwen run all seven panels
  sequentially with one Harbor c=8 row live at a time and the local relay env
  set only for `local/*` models. Qwen's dollar column uses external list
  prices on a self-hosted endpoint, so token columns are the comparable
  quantity for that row.
- Next: execute the matrix (~19h serial), generate per-row and combined
  one-sheets, and publish the campaign analysis (task #16).

## 2026-08-16 — Add failure-audit script with capacity-streak detection

- Context: trace review revealed that naive failure classification had
  mislabeled codex usage-limit hits as context limits because the classifier
  matched embedded task prose inside the shell command rather than the real
  error surface; cascading capacity events also need explicit detection.
- Change: add `scripts/audit-failures.py`. `classify_failure` reads the
  manifest error field or the terminal stdout/stderr segment of grader output
  — never the embedded command — and maps it onto a signature taxonomy
  (budget_exhausted, verifier_timeout, compose_failure, usage_limit,
  auth_forbidden, context_limit, connection_error, http_error, timeout_other,
  adapter_error_other, incorrect). `audit_cell` adds trace evidence
  (instant-death failures with ≤2 session entries) and flags runs of ≥3
  consecutive same-class failures in end-time order as capacity events
  distinct from scattered model-quality failures.
- Evidence: RED tests failed before the script existed. GREEN covers the
  noise-proof classifier (task prose containing 'usage limit' and 'context
  length' inside the command no longer misclassifies), manifest-error
  preference, per-cell taxonomy with trace counts, and a four-failure
  usage-limit streak reported as one capacity event while a scattered
  incorrect stays non-event. Full pytest reports 403 passes with only the
  pre-existing `test_check_models.sh` fixture failure.
- Decision: the audit is the authoritative failure view for task #16's
  analysis; raw failure_class labels alone are not sufficient evidence.
- Next: run the audit across every matrix root, correct contaminated cells
  (spark PolyBench/FeatureBench usage-limit hits), and fold the corrected
  taxonomy into the campaign report.

## 2026-08-16 — Honor provider thinking-level remaps in verification

- Context: the four-model matrix's Qwen row failed every agentic trial with
  "Thinking level mismatch: requested high, observed xhigh" — the runner's
  post-hoc verification treated the provider's documented remap (Qwen3.8
  maps Pi `high` to no explicit effort; the server then reports its native
  `xhigh` default, per codex-pool MODEL-MAPPINGS.md) as an adapter failure.
- Change: add `pi_thinking_level_map()` to harness/telemetry.py (loads the
  model's provider `thinkingLevelMap` from pi models.json, empty when
  absent) and `_thinking_level_check()` to the runner. A null map value for
  the requested level now records `thinking_observed` without failing; an
  explicit translation must match the observed level or the trial still
  fails closed with the mapping in the error message.
- Evidence: RED tests failed before the change. GREEN covers the
  provider-managed case, explicit-map mismatch, exact/default passes, a
  high→xhigh translated match, and the real registry's Qwen map exposing
  `high: null`. 44 mismatch-garbage Qwen agentic trials were removed for a
  clean resume. Full pytest reports 412 passes with only the pre-existing
  `test_check_models.sh` fixture failure.
- Decision: keep the verification fail-closed for genuine mismatches; only
  provider-managed (null) levels are observations, and `thinking=high`
  remains a per-model label resolved by each provider's documented map.
- Next: relaunch the matrix (Qwen row resumes cleanly), then the audit and
  final analysis fold per-model effort resolution into the report.

## 2026-08-16 — Define capability-oriented harness evaluation

- Context: current BCB/PB vanilla-versus-devstack scores provide little stable
  adapter discrimination and do not exercise much of the day-to-day devstack's
  web, automation, context, provider, or interactive workflow value.
- Change: add `docs/HARNESS-EVAL.md` with the canonical and actually installed
  package inventory, generic/Harbor exposure boundaries, task-level tool-uptake
  evidence, statistical interpretation, and a design for modular capability
  profiles, disabled/sham/enabled/cued arms, deterministic capability tracks,
  and counterfactual replay from real development sessions. Link the methodology
  from `docs/EVALS.md`.
- Evidence: reviewed the complete devstack manifest/setup/headless guidance,
  current Pi settings and package resources, Cospa adapter/sandbox/Harbor paths,
  and exported BCB/PB Pi traces. The scored devstack roots contained 822 task,
  63 background, 96 web, 13 context, and 31 goal-tool calls; multiloop,
  scheduling, and boomerang had no uptake. Re-read both changed documents
  end-to-end and ran `git diff --check`.
- Decision: retain BCB as a coding/protocol anchor and PB as an offline patching
  benchmark, but do not interpret their adapter delta as full workstation
  utility. Freeze and fingerprint small capability profiles, keep public
  historical issue tasks offline, and report opportunity through causal lift
  and overhead rather than tool availability alone.
- Next: implement profile fingerprinting, then qualify one small deterministic
  diagnostic each for planning, async tests, long context, optimization loops,
  and frozen web before another scaffold campaign.

## 2026-08-16 — Make the Superpowers treatment real and reproducible

- Context: the prior repo-local and Harbor-generated Superpowers files lacked
  required Agent Skills descriptions, so Pi loaded zero skills even though the
  adapters passed `--skill` paths.
- Change: pin upstream Superpowers v6.3.0 at
  `b36e0829c6d0140e93cfef2ca599b1b07d4a7797`; retain the complete referenced
  workflow closure for systematic debugging, TDD, and verification; validate
  every source hash; materialize identical generic/Harbor profiles; and record
  source plus per-skill snapshot hashes in trial manifests.
- Evidence: RED tests observed an empty Pi resource inventory and absent
  manifest profile. GREEN loads all three names into a real Pi 0.84.2 session
  system prompt and reconstructs the same loadable inventory from the Harbor
  setup command. A live Ornith generic probe read the TDD skill and returned
  its Iron Law. Docker-backed `hello-world` passed 1/1 under `pi_superpowers`
  at `results/e2e-smoke-terminal-bench-superpowers-v1-20260816T2045Z/`.
- Validation: 68/68 focused tests pass. Full pytest reports 412 passes and the
  pre-existing `test_check_models.sh` fixture failure; standalone shell tests
  report only that fixture's two unrelated failures. Docker retained zero
  empty Harbor networks.
- Decision: historical Superpowers-labeled rows are invalid as methodology
  evidence. Use `superpowers-bench-v1` for future Pi/OpenCode comparisons and
  treat full interactive Superpowers as a separate product-profile question.
- Next: add the controlled OpenCode baseline and identical Superpowers arm,
  then run the small Ornith c=2 comparison.

## 2026-08-16 — Make the model-check fixture hermetic

- Context: the all-skipped `check-models` shell test probed real localhost
  ports, so an unrelated local service could turn fake providers into DEAD
  results and fail the suite nondeterministically.
- Change: shadow `curl` with a deterministic HTTP-000 stub only for the
  all-skipped fixture; retain the separate authenticated-request stub.
- Evidence: `bash tests/scripts/test_check_models.sh` reports 9 passes and
  `mamba run -n cospa python -m pytest -q tests/test_scripts.py` reports 4
  passes.
- Decision: endpoint absence is now a fixture property rather than a host-state
  assumption.
- Next: resume full validation of the OpenCode adapter unit.

## 2026-08-16 — Add controlled OpenCode ablation arms

- Context: the primary harness experiment needs Pi/OpenCode baseline and
  identical-Superpowers cells without silently inheriting user config, extra
  tools, auxiliary agents, or a different provider route.
- Change: add pinned OpenCode 1.18.8 baseline/Superpowers adapters with only
  read/bash/edit/write (plus native `skill` in the treatment), isolated XDG
  state, ephemeral credential-bearing config, native JSONL usage/tool summaries,
  explicit parser manifests, and fail-closed Harbor/reasoning checks. Extend the
  sandbox with declared read-only/writable adapter mounts. Override OpenCode's
  non-UUID `ses_...` headers with one canonical UUID per trial so codex-pool
  accepts the existing Shisa host/port/path without rerouting.
- Evidence: RED/GREEN tests cover registration distinctness, route preservation,
  exact sampling and outbound tool schemas, pinned-only skill discovery,
  session headers, no retained API key, JSONL usage/search/tool parsing, sandbox
  state isolation, parser manifests, and Harbor rejection. The installed CLI
  passed both arms through a real bubblewrap/model relay and fake endpoint. A
  live authenticated Ornith treatment selected the native skill tool, loaded
  `test-driven-development`, and returned its exact Iron Law in two requests.
- Validation: `mamba run -n cospa python -m pytest -q` reports 426 passes;
  `bash tests/scripts/run_all.sh` passes all shell checks; `git diff --check`
  is clean.
- Decision: use `opencode_vanilla` and `opencode_superpowers` only on
  workspace-native suites until a distinct Harbor agent exists. Cross-harness
  rows retain native prompts/tool descriptions and estimate harness fit, not
  prompt equivalence.
- Next: run the outcome-blind Ornith c=2 Pi/OpenCode × baseline/Superpowers
  pilot with matched budgets and sampling.

## 2026-08-16 — Classify workspace agent deadlines as budget exhaustion

- Context: the Ornith c=2 pilot's final two Pi-baseline tasks each reached the
  suite's exact 1,800-second agent deadline. Generic adapters returned `-1`, so
  the runner mislabeled both as retryable infrastructure and launched duplicate
  episodes instead of preserving capability-budget outcomes.
- Change: add explicit `budget_exhausted` signaling to every generic Pi,
  Superpowers, Little Coder, and OpenCode adapter; normalize those deadlines to
  exit 124 in the runner; skip benchmark verification; and suppress retries.
- Evidence: both RED tests reproduced the real failure shape: Pi's subprocess
  timeout exposed no budget signal, and the generic runner made three attempts.
  Both are GREEN, OpenCode has a matching timeout test, 21 focused tests pass,
  and the final full suite reports 429 passing tests.
- Decision: an agent wall deadline has the same semantics in workspace-native
  and Harbor suites. Transport and unexpected adapter exceptions remain
  retryable infrastructure; historical pilot artifacts remain immutable.
- Next: record the interrupted baseline-only pilot separately. Do not estimate
  a Superpowers or cross-harness effect without matched treatment cells.

## 2026-08-16 — Record the interrupted Ornith harness pilot

- Context: the frozen 15-task, c=2 Ornith campaign was intended to compare Pi
  and OpenCode baseline/Superpowers cells sequentially under matched sampling
  and wall budgets. Its wrapper disappeared externally before the first cell
  could hand off to any treatment.
- Evidence: Pi baseline covered all 15 task IDs in exact frozen order. Native
  grading produced 2 resolved and 11 incorrect outcomes; `/985` and `/1077`
  reached exactly 1,800 seconds and are semantically budget-exhausted. All
  observed provider headers were HTTP 200, the model and 0.6/0.95/20/81920
  profile stayed exact, and no treatment directory exists. Qwen c=8 shared the
  same router, so baseline wall time is not isolated throughput evidence.
- Decision: mark P14 `partial (real artifacts)`. Preserve the result root and
  its historical pre-fix timeout labels; do not report a paired effect, skill
  uptake, or harness ranking from a baseline-only run.
- Next: only a newly approved matched campaign under one runner version and a
  disclosed router-load policy can answer the 2×2 question.

## 2026-08-17 — Complete DS4 reasoning-effort sweep on Pareto60

- Context: DS4 (`local/deepseek-v4-flash-0731`) had only ever run `pi_vanilla`
  at `thinking=high`; the devstack gate (16/19/21 at off/high/xhigh) was the
  sole effort comparison and used the wrong adapter for a vanilla claim.
- Evidence: four fresh paired cells on `bigcodebench_hard_agentic_pareto60`
  (c=8, k=1, identical task IDs) in `results/runs/ds4-bcb-pareto60-effort-*`:
  off 20/60, low 20/60, high 19/60, xhigh 24/60; plus the original
  hermetic143-subset high sample 22/60. Two same-config high runs (22 vs 19,
  agreement 53/60) bound k=1 repeat noise at the same scale as the effort
  spread; off-vs-xhigh exact McNemar p=0.42. Verified counts by direct verdict
  scan; subset derivation re-checked (60/60 overlap, 22 passed).
- Decision: effort curve is flat within noise on this panel; effort is a
  throughput knob, not a quality knob. Protocol default stays `high`;
  `off`/`low` documented as throughput mode; `xhigh` promotion would need a
  confirmed-k (k>=3) panel. Recorded in docs/PARETO-CAMPAIGN.md (new sweep
  subsection) and docs/EVALS.md (two table rows).
- Infra note: bg-63 (matrix) and bg-64 (first sweep attempt) were killed by
  external signals during a session-restart window (~23:48/23:58); both were
  relaunched as bg-66/bg-67 with the artificial serialization gate removed
  (matrix rows qwen/ornith/spark never touch the DS4 endpoint) and the
  matrix's c=8 guard taught to ignore the sweep lane. Resume-skip verified:
  298 completed qwen trials skipped, zero re-runs.
- Next: bg-66 matrix continues (qwen multi_swe onward, then ornith row, spark
  repair); on completion generate per-row and combined one-sheet reports and
  close out tasks #15/#16.

## 2026-08-17 — Remove unrequested OpenCode benchmark support

- Context: OpenCode adapter work was added without an explicit user request.
  The interrupted Ornith campaign completed only its Pi baseline and never ran
  an OpenCode cell, so it provides neither an OpenCode failure nor outcome.
- Change: remove both OpenCode adapters, their registry entries and tests, and
  the OpenCode-only sandbox/manifest plumbing. Mark OpenCode explicitly not
  implemented in the README, plan, and audit follow-up while preserving prior
  commits, qualification notes, and result artifacts as historical evidence.
- Evidence: the RED registry test initially loaded both former adapter names;
  it is now GREEN and requires each to fail as unknown. Focused adapter,
  sandbox, and runner checks report 22 passes. Full validation with
  `mamba run -n cospa python -m pytest -q` reports 416 passes in the exact
  staged tree (excluding the unrelated, unstaged failure-audit changes).
- Decision: stop the abandoned 2×2 campaign. Do not restart, replace, or
  reintroduce an OpenCode arm without a new explicit request. The generic
  Pi-family deadline fix remains in place.
- Next: if P14 resumes, keep it scoped to the implemented Pi/little-coder
  Superpowers ablation unless the user explicitly changes that scope.

## 2026-08-17 — Scope failure classifier + backfill Harbor verdicts

- Context: the DS4 pareto/stability audit surfaced two featurebench mislabels
  and a classifier false positive. The `auth_forbidden` hit was ordinary gh-cli
  Go test output (`Test_detectDeviceFlow/403_forbidden`, `internal/authflow`);
  the sympy "adapter error" was a provider `Connection error.` hidden inside the
  embedded agent command; the pytorch-lightning timeout predated `531d457` and
  was recorded as a generic adapter failure instead of `budget_exhausted`.
- Change: extract classification into `harness/failure_classify.py`;
  provider/adapter substring rules now read only the cleaned manifest error
  surface (stdout tail), never task/test output or embedded command prose.
  `scripts/audit-failures.py` imports the shared classifier; capacity-event
  logic unchanged. Add `harness/backfill_harbor_verdicts.py` +
  `scripts/backfill-harbor-verdicts.py` to correct pre-`531d457` Harbor
  verdicts from `jobs/*/result.json` evidence (AgentTimeoutError →
  budget_exhausted exit 124; other agent exceptions → failure_class from the
  manifest surface). Idempotent with dry-run/filter/exclude.
- Evidence: RED classifier tests (Go test names → incorrect; command-embedded
  connection error → connection_error; manifest AgentTimeoutError →
  budget_exhausted) now pass. Backfill dry-run touched exactly 2 of 12
  featurebench trials; apply + idempotency re-run (0 updated). Full pytest 429
  passed; `tests/scripts/run_all.sh` 17 pass, 0 fail.
- Decision: backfilled `pytorch-lightning…lv1` (budget_exhausted, exit 124) and
  `sympy…lv1` (connection_error) in
  `results/runs/ds4-featurebench-pareto12-c8-20260815T2300Z`; originals
  snapshotted under `/tmp/feat-backfill-pre`. Featurebench cell now audits as
  `{incorrect: 8, connection_error: 1, budget_exhausted: 1}`. Report ledger
  updated to record the resolution.
- Next: none required; report/ledger consumers now see the corrected classes.

## 2026-08-17 — Dedup partial runs in one-sheet report

- Context: user flagged reports/ds4-pareto-baseline-k1-and-stability32.md mixing
  complete cells with stability-k3 subsets and repair re-runs (pareto60 shown
  as 60- and 8-task rows; featurebench as 12/4/1; totals double-counted to
  369 tasks / $4.50).
- Change: generate-report.py now groups cells by (model, adapter, suite,
  thinking), prefers the latest COMPLETE cell (canonical size via
  harness.suites.get_task_ids, falling back to max observed when the registry
  cannot resolve), falls back to the latest partial with a prominent
  **PARTIAL n/expected** marker, and footnotes every excluded partial with its
  results root. canonical_suite_size is injectable for host-independent tests.
- Evidence: RED first — test_report_prefers_complete_run_over_newer_partial
  and test_report_marks_partial_when_no_complete_run failed on the unfixed
  script, pass after; full suite 431 passed. Real report regenerated over the
  same nine roots: summary now 7 rows / 336 tasks / $2.45 with all six partial
  duplicates (8/4/7/8/5/1 tasks) in the footnote section.
- Note: runpy.run_path returns a namespace copy, so monkeypatching the
  returned dict does not affect the function's globals; the DI parameter is
  the test seam, not module-dict patching.

## 2026-08-17 — Viewer default ordering, results archive, report geomean

- Viewer: ./view (and API) now defaults to sorting by model, adapter,
  thinking (effort ladder: unspecified, off, low, medium, high, xhigh),
  suite. sort_scores(None) applies DEFAULT_SORT_BY; explicit () stays natural.
- Results hygiene: archived 7 superseded test roots out of results/runs to
  archive/results-20260817/ (ds4 terminal-pilot8 v1-v3, ornith pilot15 2x2,
  qwen health-generate x2, test/model-run-a). All campaign-cited evidence
  kept in place. ./view output correspondingly shrinks to real cells.
- Report: new "Headline geomean" section — geometric mean of per-suite rates
  per (model, adapter, thinking) over primary complete cells. Continuous
  diagnostics (SWE-Explore WCC) contribute their headline score, NOT the
  any-hit pass rate (which inflated the first cut: DS4 showed 36.5% before
  the fix, 25.5% after; qwen 33.2% -> 25.1%). Partials excluded; any 0%
  component floors the group at 0.
- Also generated the interim qwen row one-sheet (reports/qwen38-vanilla-high-
  matrix.md; 7 panels, featurebench 3/12 with fresh no-cache scan). Noted:
  ./view CLI reads cached scores (showed qwen featurebench 1/12 vs 3/12 on
  disk); server path uses DEFAULT_USE_CACHE=False.
- Evidence: tests test_sort_scores_defaults_to_model_adapter_thinking_suite,
  test_report_includes_headline_geomean_per_model_config,
  test_geomean_rate_prefers_continuous_score_over_anyhit_pass_rate; full
  suite 434 passed.

## 2026-08-18 — Report aggregation: smoothed geomean, macro, micro columns

- User questioned strict geomean (two 0% suites annihilate ornith to 0.0%).
  Kept strict geomean as headline, added: Laplace-smoothed geomean
  ((passed+1)/(total+2), continuous rows floored at the same floor), macro
  mean (unweighted mean of per-suite rates), micro pooled (sum passed / sum
  total; SWE-Explore contributes its any-hit count, footnoted).
- Current numbers: DS4 25.5/26.9/29.6/35.8; qwen 25.1/26.2/25.5/30.1;
  ornith 0.0/11.1/9.9/17.3 — ordering stable across aggregations, spreads
  differ (micro lifts big-panel strengths).
- Evidence: test_geomean_smoothed_column_laplace,
  test_geomean_table_includes_macro_and_micro_columns; full suite 436
  passed. All three row reports regenerated.

## 2026-08-18 — Four-aggregate topline, analysis, and report index

- Restored all four aggregates as the topline (strict geomean, Laplace
  smoothed, macro mean, micro pooled) per user preference, plus a
  deterministic "Aggregate reading" paragraph (ordering consistency,
  zero-floor notes, biggest micro-vs-macro lift).
- Reports now embed machine-readable <!-- cospa:agg ... --> markers per
  model config with scores plus tok_in/cached/out sums and wall seconds.
- New --build-index mode scans a reports dir for markers and writes
  README.md ordered by micro pooled descending with relative links,
  capability (Geomean/Smoothed/Macro/Micro) and verbosity (In/Cached/Out/
  Wall) columns.
- Evidence: three new tests (topline markers + analysis, index ordering +
  links, tokens/wall propagation); full suite 439 passed. All reports and
  reports/README.md regenerated.

## 2026-08-18 — Document run-management plan (P1-P5 resilience)

- Context: long-running evals over online APIs (Kimi, GLM, GPT, Claude) need
  mid-run resilience. The ornith featurebench run exposed the gap: 9 trials x
  60 min burned against a dead model endpoint because only a pre-run
  reachability probe guards the start.
- Change: add `docs/RUN-MANAGEMENT.md` auditing existing capabilities (per-trial
  resume, infra-shaped retry, reachability probe, heartbeat, failure taxonomy,
  backfill tools) and the five gaps: (P1) mid-run circuit breaker, (P2) retry
  backoff / Retry-After, (P3) structured provider-error capture, (P4)
  run-matrix self-resume/checkpoint, (P5) cost rollup. Pointer added to
  PLAN.md punchlist (P16). Durable ornith failure review at
  `reports/ornith-featurebench-failure-review-20260818.md`.
- Evidence: audit of `harness/runner.py` (resume/retry/reachability), failure
  taxonomy, and per-attempt log analysis of the ornith run (all 9 completed
  trials = model-side failures, 0 eval failures).
- Decision: implement P1-P5 as small RED/GREEN units in order, committed
  separately.
- Next: P1+P2+P3 (resilient retry/backoff + circuit breaker + structured
  provider errors), then P4 (matrix self-resume), then P5 (cost rollup).

## 2026-08-18 — Add resilient retry: provider errors + backoff (P2/P3)

- Context: RUN-MANAGEMENT P2/P3 for long-running online-API evals. Retries
  were immediate and identity, and provider failures were only visible as
  substring text.
- Change: new `harness/resilience.py` (structured provider-error record,
  retry backoff honoring Retry-After, outage classifier). Runner now records
  `manifest.provider_error = {kind, status, retry_after, provider}` on
  provider-shaped failures, and `run_trial_with_retries` sleeps between
  attempts (Retry-After > exponential backoff, jittered; injectable for
  tests). Classifier fix: 429/"too many requests" now classified `usage_limit`
  (a gap the P3 test exposed).
- Evidence: `tests/test_resilience.py` (11), `test_runner_failure.py` retry
  backoff + provider_error (2), full suite 453 passed.
- Decision: retries wait instead of hammering; provider failures become data.
- Next: P1 circuit breaker (bounded submission, cell pause, exit 3).

## 2026-08-18 — Add mid-run circuit breaker (P1)

- Context: RUN-MANAGEMENT P1. A dead provider mid-run burned the whole cell
  budget (ornith case: 9 x 60 min). Only a pre-run reachability probe existed.
- Change: `harness/resilience.py` gains `agent_produced_output`
  (distinguishes a hung budget_exhausted from one that did real work),
  `trial_is_outage`, `write_paused_marker`. Runner now uses a
  `CircuitBreaker` with bounded submission (c>1 keeps only `concurrency`
  futures in flight) and pauses the cell after N consecutive provider
  outages: writes `.cell-paused.json`, finishes heartbeat `paused`, exits 3.
  Capability outcomes (wrong answer) never trip it. Flags:
  `--breaker-threshold` (0 disables) / `--no-circuit-breaker`.
- Evidence: `tests/test_circuit_breaker.py` (4: c=1 pause+marker, disabled,
  bounded c>1, wrong-answer never trips) + resilience unit tests; my files
  447 passed (full suite minus the other agent's in-progress
  `test_report_generator.py`, which fails on the committed baseline too).
- Decision: pause-and-exit (resume re-arms) rather than in-process cooldown
  waits; P4 matrix resume will skip a paused cell.
- Next: P4 run-matrix.sh self-resume/checkpoint, then P5 cost rollup.

## 2026-08-18 — Add run-matrix self-resume/checkpoint (P4)

- Context: RUN-MANAGEMENT P4. Resuming a partially-run matrix was ad-hoc;
  re-running it re-invoked every cell (and re-probed every model).
- Change: `scripts/run-matrix.sh` writes a per-run state file
  (`results/runs/.matrix-<run-id>.json`) recording each cell as
  pending/running/done/paused. Re-invoking with the same --run-id skips
  done and paused (circuit-breaker) cells; --force ignores state. A cell
  failing outside 0/3 aborts the matrix. State file is computed after
  --run-id is parsed.
- Evidence: `tests/scripts/test_run_matrix_resume.sh` (13 checks: first run,
  paused+done recorded, resume skips with zero invocations, --force re-runs,
  fresh run-id starts fresh). Full shell suite run_all.sh green; test_scripts.py green.
- Next: P5 cost rollup from usage x models.yaml prices.

## 2026-08-18 — Index cleanup: dedup, sections, marker placement, file prune

- Fixed broken geomean table rendering: cospa:agg markers moved out of the
  table body into a contiguous block after the Aggregate reading section.
- Single-cell groups (instruct rows) no longer emit aggregate rows or
  markers — a one-cell "geomean" is just the cell; it stays in Summary.
- Index: dropped the Adapter column; one row per (model, thinking) with
  duplicates across reports collapsing (most tasks wins); markers now carry
  tasks= and elapsed=; two sections — Authoritative full-matrix runs
  (>= 300 tasks on identical panels) vs Other cells; added Wall + Elapsed
  (campaign span) columns next to token verbosity columns.
- Removed reports/four-model-matrix.md per user (README index + per-row
  one-sheets cover it); generated the spark per-row one-sheet so its
  numbers stay indexed. Committed the parallel session's ornith
  featurebench failure review (all failures model-side, zero eval defects).
- Evidence: 5 new/updated tests; full suite 462 passed.

## 2026-08-18 — Add cost rollup from usage x prices (P5)

- Context: RUN-MANAGEMENT P5. Token usage was captured but per-trial cost was
  not derived from models.yaml prices, and there was no per-run rollup — a
  blind spot for paid online APIs.
- Change: new `harness/cost.py` prices a trial from `model.cost`
  (usd_per_1m_tokens, long-context tiers) x `token_usage`; `runner.py` writes
  `manifest.cost`. New `harness/cost_summary.py` + `scripts/summarize-costs.py`
  roll up `cost-summary.json` per run with per-model/per-suite/per-cell
  breakdowns, re-deriving cost for historical manifests (backfill).
- Evidence: `tests/test_cost.py` (6), `test_cost_summary.py` (3), runner cost
  integration test in `test_usage_capture.py` using real codex/gpt-5.5 prices;
  CLI smoke on a fake run tree. Full suite 458 passed (minus the other
  agent's in-progress test_report_generator.py); shell suite green.
- Decision: price locally from configs/models.yaml (deterministic, works for
  historical backfill) rather than trusting pi's reported cost_usd alone.
- Next: none in P1-P5; RUN-MANAGEMENT plan complete. Consider wiring
  cost-summary into generate-report and adding backfill-usage reuse.

## 2026-08-18 — Phase F matrix complete: four-model results, qwen sweep, closure

- All four rows complete on the identical 336-task panel set after repair
  passes. Final aggregates (smoothed geomean / macro / micro): qwen 26.2/
  25.5/30.1; spark 22.9/22.4/30.4 (3 poly trials lost to API quota); ornith
  11.1/9.9/17.3 (strict geomean 0 — zero panels); DS4 26.9/29.6/35.8 on its
  own panel set. Ornith featurebench classified outage-affected: 2 valid
  attempts (both fail), 10 zero-byte trials from the stg04 router/sglang
  serving flap (root-caused to the serving path, harness exonerated; see
  reports/ornith-featurebench-failure-review-20260818.md and the live probe
  evidence: intermittent TCP refusals + streaming stalls + 43s trivial
  completions between healthy windows).
- Qwen effort sweep (5 distinct rungs, Pareto60, k=1): 15/19/19/20/9 of 60
  off->xhigh. xhigh collapse is the campaign's first significant effort
  effect (high vs xhigh exact McNemar p=0.0074); off->high trend within
  noise (p=0.36). Mirror of DS4's flat curve: effort direction is
  model-specific.
- Docs: PARETO-CAMPAIGN.md Phase F results + qwen sweep subsection; EVALS.md
  four-model results table. Reports: ornith/spark one-sheets regenerated,
  README index at 4x6-cell rows. Spark poly repair: +1 pass (13/64), 3
  re-run trials hit quota again — documented, not chased.

## 2026-08-18 — Wire-id resolution for alias model ids (fp8-block incident)

- Incident: the qwen FP8-BLOCK row burned 3 launches on 503s — pi sent the
  raw benchmark id (qwen3.8-27b-fp8-block) upstream; the router 400s unknown
  names into a codex-account error. Three leak layers found and fixed:
  (1) harbor run --model (terminal_bench._harbor_model_arg — all Harbor
  suites inherit), (2) host-side bwrap sandbox pi --model
  (subprocess_utils._wire_model_ref rewrite), (3) instruct HTTP adapter
  (earlier alias matching). Container/sandbox models.json bakes a one-model
  config from the resolved MODEL_ID, so --model must land on that exact id.
- pi itself is not alias-aware ("Using custom model id" fallback); the
  aliases live in ~/.pi/agent/models.json and are resolved harness-side.
- Circuit breaker did NOT catch the agentic-cell leak: pi's internal retries
  convert provider death into slow NonZeroAgentExitCode adapter failures.
  338 + 64 garbage verdicts across takes 2-3 detected by trace audit
  (503 signature in sessions), deleted; instruct cell (49/143, host HTTP
  path) was real and kept. Take 4 verified live: sandbox cmdline shows
  --model local/Qwen3.8-27B.
- Evidence: test_find_pi_model_matches_aliases,
  test_pi_model_arg_resolves_alias_through_env,
  test_harbor_model_arg_resolves_wire_id,
  test_wire_model_ref_resolves_aliases; full suite 478 passed.

## 2026-08-18 — Add canonical run-id naming convention (RUN-MANAGEMENT)

- Context: run dirs followed an informal `<model>-<suite>-...-c<n>-<date>`
  pattern, but nothing formalized it and run-matrix.sh's auto run-id was a
  raw timestamp (unused by any real run). Asked to normalize run naming.
- Added `scripts/run-id-lib.sh` (slugify fallback + model/suite slug catalogs
  matching existing dirs + `make_run_id`) emitting
  `<model>-<suite>[-<adapter>]-<effort>-c<K>-<YYYYMMDD>T<HHMM>Z`; documented
  the convention in `docs/RUN-MANAGEMENT.md` §4.5. run-matrix.sh now sources
  the lib and generates a conventional-prefixed run-id when `--run-id` is
  omitted; multi-model cells fall back to timestamp+pid; explicit ids unchanged.
- Decision: auto ids append `-<pid>` so a no-run-id invocation always runs
  fresh — a deterministic conventional id would collide with P4 resume state
  (caught by the pre-existing test_run_matrix.sh --problems case) and
  silently skip done cells.
- Evidence: `tests/scripts/test_run_id_convention.sh` (7 checks); full shell
  suite green; pytest 480 passed.
- Next: apply the convention to the fp8-block effort-ladder run-ids.
