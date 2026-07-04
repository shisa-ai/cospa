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
