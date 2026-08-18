# RUN-MANAGEMENT.md — Long-running eval operations

Operational capabilities and the resilience plan for running cospa matrices
over many models (including online APIs such as Kimi K3, GLM-5.3, GPT, and
Claude) for long periods. This documents what the harness already does,
where it falls short, and the P1–P5 improvement plan.

Reference: the ornith featurebench failure review
(`reports/ornith-featurebench-failure-review-20260818.md`) is the motivating
case — 9 trials × 60 min burned against a dead model endpoint because
nothing stopped the run mid-way.

---

## 1. What the harness already does (audit, 2026-08-18)

### Trace / error analysis

- **Per-trial traces.** Every trial records `pi_session.jsonl` (the full agent
  transcript), `manifest.json`, and `verdict.json` under
  `results/runs/<run>/<model>/<adapter>/<suite>/<task>/trial-N/`. Harbor
  attempts additionally export pi sessions to the job artifacts on completion.
- **Structured error surface.** `manifest.error`, `manifest.harbor_agent_exception`
  (`exception_type` / `exception_message`), and `verdict.failure_class`.
  Adapter failures embed the real error (`stdout:` tail) so the classifier
  reads a clean surface.
- **Classification.** `harness/failure_classify.py` maps a failed trial to a
  taxonomy (`incorrect`, `budget_exhausted`, `connection_error`,
  `auth_forbidden`, `usage_limit`, `context_limit`, `http_error`,
  `verifier_timeout`, `compose_failure`, `adapter_error_other`, `timeout_other`).
  Provider/adapter substring rules read **only the manifest error surface**,
  never task/test output or embedded command prose.
- **Audit tooling.** `scripts/audit-failures.py` rolls classifications into
  per-cell failure counts and **capacity events** (consecutive same-class
  infrastructure failures in time order). `scripts/generate-report.py` renders
  score sheets. `scripts/backfill-usage.py` and
  `scripts/backfill-harbor-verdicts.py` correct historical records from
  evidence (usage from pi JSONL; Harbor agent-phase verdicts from
  `jobs/*/result.json`).

### Resumption

- **Per-trial resume.** `run_trial` skips any trial whose `manifest.json` +
  `verdict.json` are complete (`[resume] skip ... artifacts complete`); a
  killed run's partial artifacts are re-run (`[resume] incomplete artifacts ...
  re-running`). Proven on real data: a resumed qwen grid skipped 298 completed
  trials with zero re-runs.
- **Force.** `--force` bypasses resume for full re-runs.

### Retry

- **Infrastructure-shaped retries only.** `run_trial_with_retries` retries a
  trial when `_is_retryable_infra_failure` is true: `verifier_failed`, or
  `adapter_failed`/`exit -1` with an error. `budget_exhausted` (exit 124) is
  deliberately **not** retried — it is a capability-budget outcome, not
  infrastructure.
- **Per-trial retries are recorded.** `manifest.retry = {attempt, max_attempts}`.

### Pre-flight and liveness

- **Pre-run reachability probe.** `check_model_reachable()` issues a 1-token
  completion against the model's provider base URL before a matrix starts, so
  a dead endpoint fails fast instead of silently producing an all-fail run.
  `--skip-reachability` bypasses it.
- **Heartbeat.** `.runner-heartbeat.json` per cell feeds liveness-aware score
  views.

### Online-API model registry

- Model ids are provider-prefixed (`codex/`, `zai/`, `minimax/`, `shisa/`,
  `local/`, …) and resolve through `~/.pi/agent/models.json`
  (`{provider: {baseUrl, apiKey, models: [...]}}`) plus `configs/models.yaml`
  (price, context window, sampling). Any OpenAI-compatible online endpoint is
  expressible; provider keys (OpenAI, OpenRouter, Kimi, GLM, …) are injected
  into the Harbor agent environment as `CODING_EVAL_PI_PROVIDER_*`.

---

## 2. Gaps for long-running online-API evals

1. **No mid-run circuit breaker (P1).** The reachability probe guards only the
   start. If a provider dies mid-run, every remaining trial burns its full
   budget against the dead endpoint — the ornith case wasted 9 × 60 min.
2. **No retry backoff / Retry-After / 429 handling (P2).** Retries are
   immediate and identical. Online APIs return 429/5xx that need backoff;
   repeated immediate retries worsen rate limits. `Retry-After` is ignored.
3. **No structured provider error capture (P3).** pi embeds HTTP status as
   text; the manifest/verdict do not record a structured
   `{status, retry_after, provider, kind}`. Retry/resume/analysis logic is
   therefore substring-based and blind to the actual provider failure mode.
4. **Matrix-level resume is ad-hoc (P4).** `run-matrix.sh` has no self
   checkpoint; resuming a partially-run matrix depends on an external wrapper
   scanning for unfinished trials.
5. **Cost accounting is not automatic (P5).** Runtime `token_usage` is
   captured, but per-trial cost is not computed from `configs/models.yaml`
   prices, and there is no per-run cost rollup — a real concern for paid APIs.

---

## 3. Improvement plan

Each item is a small RED/GREEN unit, committed separately. They touch
`harness/runner.py` (shared file — coordinate), the retry/resume path, and
orchestration.

### P1 — Circuit breaker

- **Goal:** stop scheduling new trials for a cell when the provider is
  wholesale-failing, instead of burning the remaining budget.
- **Design:** a per-cell breaker that opens after `N` consecutive
  infrastructure-class failures in a row (same classification from
  `failure_classify`; e.g. `connection_error`, `http_error`, `auth_forbidden`,
  `usage_limit`). When open:
  - the runner stops launching new trials for that cell,
  - writes a `paused` marker + reason to the cell dir,
  - waits for a cooldown (or a manual resume flag) before testing the
    provider again with a probe, then either resumes or stays paused.
- **Config:** breaker threshold, cooldown, and an escape hatch
  (`--no-circuit-breaker` / env) for offline/smoke runs.
- **Key interaction:** a trial that fails while the breaker is closed counts
  toward the streak; a single pass resets it. `budget_exhausted` and
  `incorrect` do **not** count (they are model-capability, not provider).

### P2 — Backoff / Retry-After

- **Goal:** retries that respect provider signals instead of hammering.
- **Design:**
  - Classify the retryable failure into *immediate* (connection refused,
    5xx, DNS) vs *wait* (429 rate limit, 503 with `Retry-After`).
  - For *wait*, sleep for the `Retry-After` value when the provider returns
    one, otherwise an exponential backoff with jitter
    (`base * 2^attempt + rand(0, jitter)`), capped.
  - Honor the existing `--retries N` count; the backoff is only about timing.
- **Where:** `run_trial_with_retries` (sleep between attempts) and the
  trial-level breaker used by the runner loop.

### P3 — Structured provider errors

- **Goal:** the manifest records the provider failure mode as data.
- **Design:** when a trial fails and the error surface is provider-shaped
  (or the harbor agent exception / adapter error carries it), write
  `manifest["provider_error"] = {status, retry_after, provider, kind}`
  where `kind` is one of the classifier's infra classes. Extract `status` /
  `retry_after` from the error text where possible; leave `null` when absent.
- **Effect:** retry (P2) and analysis read `provider_error` instead of
  substring-matching; `audit-failures.py` can later prefer it as the
  authoritative surface.

### P4 — `run-matrix.sh` self-resume / checkpoint

- **Goal:** restarting a matrix picks up where it left off without an external
  wrapper.
- **Design:** `run-matrix.sh` writes a per-cell state file (e.g.
  `results/runs/<run>/.matrix-state.json`) listing `pending / running / done /
  paused`. On start it reads the state and only queues cells not already
  `done`/`running` (with a `--force` to ignore). A cell is marked `done` when
  its trial set is complete per the runner's resume semantics.
- **Interaction:** the circuit breaker marks a cell `paused`; the matrix
  skips it until it is re-armed.

### P5 — Cost rollup

- **Goal:** spend visibility for paid APIs.
- **Design:** per-trial cost computed at runtime from
  `manifest["token_usage"]` × `configs/models.yaml` price
  (`input * prompt_tokens + output * completion_tokens`). Write
  `manifest["cost"]` and roll up into a per-run cost summary
  (`results/runs/<run>/cost-summary.json`) with per-model and per-suite
  breakdowns. Backfill path (`scripts/backfill-usage.py`) gains the same
  computation so historical manifests can be priced retroactively.

---

## 4. Operating a long-running matrix (runbook notes)

- **Before starting:** run `scripts/check-models.sh`; confirm the provider
  reachability probe passes for every model in the matrix. For online APIs,
  confirm rate-limit headroom and cost budget up front.
- **During:** watch `results/runs/<run>/*/.runner-heartbeat.json` and cell
  progress via the score viewer. If a cell flips to `paused` (P1), check the
  provider before re-arming.
- **After an interruption:** restart the matrix — P4 resume skips completed
  cells; P1-paused cells are skipped until re-armed. Do not `rm` result dirs;
  they are durable evidence.
- **Cost:** with P5, check `cost-summary.json` per run; set a spend ceiling
  externally (stop the runner) for paid providers.
- **Treat `results/` and `vendor/` as durable.** Do not mass-delete or
  rebaseline prior runs unless explicitly asked.

---

## 5. Non-goals

- Not a replacement for a proper job scheduler; concurrency is still
  `--concurrency N` per runner.
- No automatic multi-provider failover (that is a routing-layer concern on
  the model router, not the harness).
- The circuit breaker is about *pausing* a broken cell, not about deciding
  which provider serves a model.
