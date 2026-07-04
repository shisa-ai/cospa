# coding-eval - Agent Guide

coding-eval is a multi-model, multi-adapter coding benchmark harness
(Aider Polyglot, Terminal-Bench) with a runner, adapters, suites, a score
viewer, and orchestration scripts. See `docs/PLAN.md` for architecture and
roadmap and `docs/ORNITH-CODER-REVIEW.md` for the audit history.

This `AGENTS.md` is read every session. It covers only ground rules that
apply to every task. Scope-specific detail lives in `docs/PLAN.md`,
`docs/ORNITH-CODER-REVIEW.md`, and `docs/IMPROVEMENT.md`.

Instruction precedence: if this file conflicts with platform / system /
developer instructions, follow those first.

## Summary

- **Source of truth:** `docs/PLAN.md`. Update it when architecture or phase
  plans move.
- **Testing discipline:** RED/GREEN TDD is the default. Write the failing
  test first, then fix the code until it passes. See "Testing" below.
- **Git discipline:** explicit, auto-commit after validation. Many small,
  atomic commits with clear provenance — not fewer larger ones. See "Git
  Discipline" below.
- **Verification before "done":** run the narrowest check that matches the
  change; never claim a fix is green on the strength of a mock-passing
  test alone. See "Verification Tiers" below.
- **Results are durable.** `results/` may contain expensive or
  hard-to-reproduce trial outputs. Do not delete, overwrite, or rebaseline
  without instruction.
- **Vendor datasets are large and external.** They are not committed; tests
  that need them use `@pytest.mark.requires_vendor` and skip cleanly when
  absent.

## Key Files

| Path | Purpose |
| --- | --- |
| `docs/PLAN.md` | Architecture, phase roadmap, matrix design. |
| `docs/ORNITH-CODER-REVIEW.md` | Audit history and per-finding resolution status. |
| `docs/IMPROVEMENT.md` | Process lessons from the third audit; re-read before a fix pass. |
| `WORKLOG.md` | Append-only development log. One entry per validated logical unit; never edit history. |
| `harness/runner.py` | Trial execution, manifest writing, reachability check. |
| `harness/adapters/` | Per-agent adapters (pi_vanilla, pi_devstack, pi_superpowers, little_coder*). |
| `harness/suites/` | Per-benchmark suites (aider_polyglot, terminal_bench). |
| `view-scores/server.py` | Score viewer (HTTP). Directory is hyphenated, not a package. |
| `scripts/check-models.sh` | Pre-run model reachability probe. |
| `scripts/run-matrix.sh` | Matrix orchestration (models x adapters x suites). |
| `scripts/setup.sh` | Dataset vendoring (polyglot-benchmark, terminal-bench). |
| `configs/models.yaml` | Matrix model list. |
| `tests/` | Pytest suite + `tests/scripts/` shell harness. |
| `vendor/` | Uncommitted external datasets (polyglot-benchmark, terminal-bench). |

## Workflow

### Before Starting

1. `git status -sb` — note unrelated changes and leave them alone.
2. Skim the relevant section of `docs/PLAN.md` and the tail of
   `docs/ORNITH-CODER-REVIEW.md` so you know what is already fixed,
   partial, or open.
3. Re-read `docs/IMPROVEMENT.md` before any fix/audit pass — it captures
   the process bugs that let regressions slip through.

### During Work

- Keep changes scoped to one logical unit (one suite, one adapter, one
  script, one doc).
- **Write the failing test first** when behavior changes (see "Testing").
- Convert user-supplied path args to `Path` at every entry point — argparse
  returns strings, and suites use `/` division that crashes on `str`.
- Treat `results/` and `vendor/` carefully. Do not mass-delete, rebaseline,
  or rewrite prior runs unless asked.
- Log non-trivial decisions in the commit message or
  `docs/ORNITH-CODER-REVIEW.md`, not just in chat.
- **Append to `WORKLOG.md`** when a logical unit is complete and validated
  (see "WORKLOG Discipline" below). Commit the append in the same unit.

### After Changes (before claiming done)

- Run the narrowest relevant verification tier (see below).
- For a bug fix: confirm the *RED* test you wrote at the start now passes,
  and that it would have failed before the fix.
- Update `docs/ORNITH-CODER-REVIEW.md` per-item status if your change
  resolves a listed finding. Use the explicit evidence vocabulary from
  `docs/IMPROVEMENT.md` (`fixed (unit test)` vs `fixed (integration test)`
  vs `wired (unverified)` vs `partial`).
- **Commit immediately** when the logical unit is complete and validation
  passes.

## Testing

RED/GREEN TDD is the default for any behavioral change.

1. **RED:** write a test that captures the bug or desired behavior. Run it
   and confirm it **fails for the right reason** (not a setup error). A
   test that fails with `ImportError` is not RED — it is broken.
2. **GREEN:** make the minimal change so the test passes. Do not refactor
   in the same step.
3. **REFACTOR:** clean up with the test still green.

If RED-first is genuinely impractical (e.g. probing an unknown external
API), record the no-RED rationale in the commit message — do not silently
skip.

### Test hygiene (from `docs/IMPROVEMENT.md`)

- **Test against real artifacts, not only fixtures.** Mocks and fixtures
  cannot catch "shape-correct but behavior-wrong" bugs (the category that
  caused the third-audit misses). At least one real end-to-end run per
  code path before claiming `fixed (end-to-end)`.
- **Boundary-test numeric parameters.** Any test that only exercises the
  default value of a numeric flag (e.g. `--k 1`) is a smell. Test `k=2`,
  `k=3`, and assert on total work done, not one iteration.
- **Ablation-equivalence invariant.** Anywhere the design promises "N
  distinct configurations" (adapters, models, suites), add a test that
  asserts they are actually distinct.
- **Cover every language in a multi-language suite.** A Python-only test
  for `aider_polyglot` does not cover Go/Rust/C++ scoring. Add
  language-specific scoring tests with real tool-output fixtures.

## WORKLOG Discipline

`WORKLOG.md` is the append-only development log. Convention-only
enforcement (no hook); the rule is upheld by review and by the commit
discipline below.

- **Append-only.** Never edit, reorder, or delete prior entries. Add new
  entries at the end only.
- **One entry per validated logical unit**, format:
  `## YYYY-MM-DD — short summary (imperative, ≤ 72 chars)` followed by
  bullets for context, evidence (test name / verification command),
  decision/rationale, and next actions.
- **Commit the append with the unit.** The WORKLOG entry is part of the
  atomic commit (or small atomic group) that completes the unit. Do not
  leave WORKLOG edits uncommitted across sessions.
- **Concurrent appends.** If two agents append in the same window,
  resolve by keeping both entries ordered by timestamp; never drop a
  prior entry.
- **Scope.** Log `coding-eval` development only (harness, adapters,
  suites, scripts, viewer, docs, audits). Do not log routine
  rebaselining of `results/` or vendoring churn in `vendor/`.

## Verification Tiers

Run the narrowest tier for your change; escalate at milestone boundaries.

| Scope | What to run |
| --- | --- |
| Docs / process | Re-read the changed file end-to-end; no test run needed. |
| Code (harness, suites, adapters) | `mamba run -n coding-eval python -m pytest -q` |
| Shell scripts | `bash tests/scripts/run_all.sh` (also run via `tests/test_scripts.py`) |
| Viewer | A viewer test in `tests/test_view_scores.py` against an encoded fixture tree |
| Bug fix | The RED test you wrote, plus the full suite to catch regressions |
| Milestone / release | Full `pytest -v` + `tests/scripts/run_all.sh` + one real end-to-end trial per affected suite |

## Git Discipline

Explicit, auto-commit-after-validation. Many small, atomic, working-state
commits with clear provenance.

### Commit Timing

- **Commit immediately** after a logical unit is complete and validation
  passes. Do not ask, do not wait to be asked, and do not start the next
  logical unit until the previous validated unit is committed.
- Include related docs in the same unit (a change that needed a
  `docs/ORNITH-CODER-REVIEW.md` or `docs/` update commits them together).
- Include the `WORKLOG.md` append in the same unit when the unit is
  significant enough to log (see "WORKLOG Discipline").
- Do not commit mid-task while exploring, debugging, or in a broken state.

### Commit Mechanics (hard rules)

- **Never** use `git add .`, `git add -A`, or `git commit -a`.
- **Never** revert, checkout, or restore files you did not modify.
- **Always** stage files explicitly: `git add <path1> <path2> …`.
- **Always** verify before committing:
  ```bash
  git status -sb
  git diff --staged --name-only
  git diff --staged
  ```
- If unrelated changes or staged files you did not create exist, leave
  them alone — another agent or the human owns them.

### Commit Messages

```
type: short summary (imperative, ≤ 72 chars)

- Non-obvious context
- Evidence (test name, verification command) when relevant
```

Prefixes: `feat:`, `fix:`, `docs:`, `test:`, `refactor:`, `chore:`,
`perf:`. **No bylines** — no `Co-authored-by`, no agent attribution, no
generated-by footers.

### Never Committed

- `vendor/` datasets (polyglot-benchmark, terminal-bench) — large, external
- Model weights, `*.safetensors`
- Python caches (`__pycache__`, `.pytest_cache`)
- Local results from smoke runs unless explicitly retained

### Never Discard Others' Work

Do not run `git restore`, `git checkout --`, `git reset --hard`,
`git clean -fd`, `rm -rf` across tracked paths, or bulk rewrites (aggressive
formatters, mass import reordering) unless the user explicitly asks.

## Coordination

Working tree is shared state. Other agents or the human may be editing
concurrently.

- **High-conflict files:** `AGENTS.md`, `docs/PLAN.md`,
  `docs/ORNITH-CODER-REVIEW.md`, `docs/IMPROVEMENT.md`,
  `harness/runner.py`, `harness/suites/*.py`, `view-scores/server.py`,
  `scripts/run-matrix.sh`, `scripts/check-models.sh`,
  `configs/models.yaml`, `pyproject.toml`, `WORKLOG.md`.
- Same-file contention: stop and coordinate. Do not force-stage or revert.
- Ignore unrelated modified files unless the task explicitly requires it.

## Blockers

| Situation | Action |
| --- | --- |
| A behavior change lacks an obvious test | Stop and write the RED test first, or record an explicit no-RED rationale in the commit message. |
| A fix passes its own test but you cannot express why it would have failed before | Re-examine — the test may not actually cover the claim. Add a real-artifact test (`docs/IMPROVEMENT.md` #1, #4). |
| A multi-language suite change is only tested in Python | Add coverage for the other languages before claiming done. |
| `vendor/<dataset>` is absent | Mark the suite/test experimental; do not assert "Fixed" on fixture-only tests. Use `@pytest.mark.requires_vendor`. |
| An adapter/model/suite axis looks identical to its siblings | Add an ablation-equivalence invariant test; do not assume distinctness. |
| Unrelated files changed in the worktree | Leave them. Another agent or the human owns them. |
| Same-file conflict with another agent | Stop and coordinate. |
