# Ornith-35B featurebench pareto12 — failure review (model vs eval)

Generated 2026-08-18. Goal: for every failed query in
`results/runs/ornith35-vanilla-high-matrix-c8-20260816`
(`shisa/ornith-35b-fp8-block`, `pi_vanilla`, `featurebench_lite_pareto12`,
`--thinking high`, `--k 1`, `--concurrency 8`, `--retries 2`), determine
whether the failure is a **model failure** (the model endpoint did not
deliver a usable response) or an **eval failure** (Harbor environment,
budget enforcement, or verifier malfunctioned).

## Bottom line

**All completed trials failed on the MODEL side. Zero eval failures.**

- **9/9 completed trials** ended as `budget_exhausted` (`AgentTimeoutError`
  after exactly 3600 s): pi produced **zero output** for the whole budget
  (0-byte agent output, no pi session messages, no reasoning, no tool calls,
  no edits), then Harbor killed the agent and the verifier ran cleanly scoring
  `reward: 0.0` on the untouched `/testbed`.
- **2 further attempts** (xarray #1, sympy #1) ended as
  `NonZeroAgentExitCodeError` with pi printing `Connection error.` — pi
  connected, received empty assistant chunks, then lost the connection.
- **The identical eval path now works**: the two trials that started at
  10:06–10:07 JST (pandas, pydantic) are running real agent episodes —
  pi is producing `thinking` content and `read` tool calls as of 10:15 JST.
  The model backend came back up around 10:06.
- **No evidence of an eval/harness defect anywhere**: every failure is
  "the ornith endpoint did not answer pi," not "the grader/harness broke."

## Failure timeline

| Window (JST) | Trials | pi behavior | Harbor outcome |
|---|---|---|---|
| ~01:33–01:37 | first wave (all 12) | `Connection error.` (empty assistant chunks, ~2 min) | `NonZeroAgentExitCodeError` |
| ~01:35–02:36 | xarray, sympy retries | zero output, 60 min | `AgentTimeoutError` → budget |
| 06:04–07:05 | pytorch-lightning, sphinx | zero output, 60 min | `AgentTimeoutError` → budget |
| 07:05–08:06 | metaflow, astropy | zero output, 60 min | `AgentTimeoutError` → budget |
| 08:05–09:06 | transformers, mlflow | zero output, 60 min | `AgentTimeoutError` → budget |
| 09:06–10:06 | seaborn ×2 | zero output, 60 min | `AgentTimeoutError` → budget |
| 10:06–10:07+ | pandas, pydantic | **working** (thinking + read tools) | in progress |

## Per-trial evidence

| Trial | Attempts | Exception | pi session | Verifier |
|---|---|---|---|---|
| pytorch-lightning | 1 (06:04) | AgentTimeoutError (60 m) | none (0 bytes) | reward 0.0, 19 s |
| metaflow | 1 (07:05) | AgentTimeoutError (60 m) | none | reward 0.0 |
| astropy | 1 (07:05) | AgentTimeoutError (60 m) | none | reward 0.0 |
| transformers | 1 (08:05) | AgentTimeoutError (60 m) | none | reward 0.0 |
| mlflow | 1 (08:05) | AgentTimeoutError (60 m) | none | reward 0.0 |
| seaborn (alg) | 1 (09:06) | AgentTimeoutError (60 m) | none | reward 0.0 |
| seaborn (reg) | 1 (09:06) | AgentTimeoutError (60 m) | none | reward 0.0 |
| sphinx | 1 (06:04) | AgentTimeoutError (60 m) | none | reward 0.0 |
| xarray | 2 | #1 NonZeroAgentExitCodeError (2 m, `Connection error.`); #2 AgentTimeoutError (60 m) | #1: user + 4 empty assistant; #2: none | reward 0.0 |
| sympy | 2 | #1 NonZeroAgentExitCodeError (2 m, `Connection error.`); #2 AgentTimeoutError (60 m) | #1: user + 4 empty assistant; #2: none | reward 0.0 |
| pandas | running (10:06) | — | **working** (thinking + reads) | — |
| pydantic | running (10:07) | — | **working** (thinking + reads) | — |

## Why this is a model-side failure, not an eval failure

1. **The eval path is identical and works.** Same Harbor flow, same pi
   runtime/config, same containers. As soon as the backend answered
   (~10:06), pi ran normally. Nothing about the harness changed.
2. **pi never completed a single model exchange in any failed trial.**
   Zero reasoning, zero tool calls, zero edits, zero session messages in the
   60-min hangs. This is an upstream serving failure, not a wrong answer and
   not a grading failure.
3. **The eval behaved correctly throughout.** Harbor built the env, launched
   the agent, enforced the 3600 s agent budget, recorded `AgentTimeoutError`,
   then ran the verifier (19 s, `reward: 0.0` on the untouched `/testbed`).
   No compose failures, no verifier crashes, no scoring anomalies.
4. **Reachability is not the issue.** From inside a container, `curl` and
   Node `fetch` to `http://stg04.local:8989/v1/chat/completions` for
   `ornith-35b-fp8-block` both return HTTP 200 with reasoning content in
   ~4–5 s. The hang/empty-response is in pi's streaming request to the
   ornith backend specifically.
5. **Root-cause locus is the ornith serving path** (router
   `stg04.local:8989`, a separate LAN host at 192.168.20.250, not this host;
   this host runs vllm :8001 for DeepSeek and sglang :8000 for Qwen but no
   :8989 listener). DeepSeek and Qwen through the same router worked during
   the same window, so the outage is ornith-specific.

## Classification summary

- Model failures (ornith endpoint unavailable / non-responsive): **9 completed
  trials + 2 connection-error attempts = 100% of failed queries.**
- Eval failures: **0.**
- In progress at review time: **pandas, pydantic** — first trials to actually
  run, so the first real ornith scores (if any) come from these.

## Caveats / next steps

- The router/backend internals are not visible from this host, so the exact
  cause of the ~8.5 h outage (01:30 → 10:00 JST: ornith model not loaded,
  backend OOM/queueing, or a router misroute for the ornith model) needs the
  stg04 host's server logs to confirm. The log evidence cleanly separates
  model-serving failure from eval failure regardless.
- If ornith is needed for the matrix, re-run the featurebench cell now that
  the endpoint is serving; the 9 budget-exhausted trials carry no signal and
  should be treated as invalid (agent never ran), not as `incorrect`.
- DeepSeek/Qwen rows through the same router are unaffected; their results
  stand.
