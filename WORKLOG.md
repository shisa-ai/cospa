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
