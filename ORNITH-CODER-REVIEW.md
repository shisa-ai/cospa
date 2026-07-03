# Ornith Coder Review

Review target: current `main` at `de9279d` (`Fix critical bugs and add comprehensive tests`), checked against `PLAN.md` and the actual local tool/dataset behavior.

Summary: this implementation is mostly scaffolding, not a working eval harness yet. The repository has files for most P1-P15 items, but the core execution path cannot currently launch an adapter successfully, Terminal-Bench is not integrated, Aider Polyglot is wired to a placeholder/simplified dataset shape, and the score viewer cannot aggregate the result tree the runner writes.

## Blockers

### 1. Every adapter passes a `Path` object as `subprocess.run(stderr=...)`

Files:
- `harness/adapters/pi_vanilla.py:52-58`
- `harness/adapters/pi_devstack.py:68-75`
- `harness/adapters/little_coder.py:51-58`
- `harness/adapters/pi_superpowers.py:62-69`
- `harness/adapters/little_coder_superpowers.py:55-62`

`subprocess.run` requires `stderr` to be `None`, an fd integer, `PIPE`, `STDOUT`, `DEVNULL`, or an open file-like object. Passing `stderr_file: Path` raises `AttributeError: 'PosixPath' object has no attribute 'fileno'` before the process launches. The adapters catch broad `Exception` and return `AdapterResult(returncode=-1)`, so the runner records a failure without the real error.

I verified the exact behavior with Python 3.12 in `coding-eval`:

```text
AttributeError: 'PosixPath' object has no attribute 'fileno'
```

Impact: no adapter run can actually execute as written. The new tests miss this because they mock `subprocess.run`.

### 2. All adapter commands use `-m`, but the installed `pi`/`little-coder` reject it

Files:
- `harness/adapters/pi_vanilla.py:43-48`
- `harness/adapters/pi_devstack.py:42-48`
- `harness/adapters/little_coder.py:43-47`
- `harness/adapters/pi_superpowers.py:46-52`
- `harness/adapters/little_coder_superpowers.py:42-46`

Current local `pi --help` documents `--model`, not `-m`. Running `pi -m test/model --offline --no-session --print hi` and `little-coder -m test/model --offline --no-session --print hi` both return:

```text
Error: Unknown option: -m
```

Impact: even after fixing the `stderr` bug, every adapter still exits before invoking a model. The tests currently assert the wrong flag in `tests/test_harness.py:73`, `tests/test_harness.py:98`, and `tests/test_harness.py:121`.

### 3. Result paths cannot be aggregated by the score viewer

Files:
- `harness/runner.py:89`
- `view-scores/server.py:116-142`
- `view-scores/server.py:181-188`
- `tests/test_harness.py:216`

The runner writes paths using raw `model_id` and `task_id`:

```text
results/<model_id>/<adapter>/<suite>/<task_id>/trial-<k>/
```

Real model IDs contain `/`, e.g. `nvidia/nemotron-3-ultra-550b-a55b`, and Aider task IDs contain `/`, e.g. `python/hello`. That produces nested directories:

```text
results/nvidia/nemotron-3-ultra-550b-a55b/pi_vanilla/aider_polyglot/python/hello/trial-1/
```

The viewer assumes the first three path components are exactly model, adapter, suite, and then only checks for direct `trial-*` children under the suite directory. It never recurses through task directories. With real IDs, it will interpret `nvidia` as the model and `nemotron-...` as the adapter, then find no trials.

Impact: successful runs would not appear in `/api/scores` or `/api/tasks`. The tests encode the nested slash behavior but do not test the viewer.

### 4. Terminal-Bench is not connected to the runner and currently returns zero tasks

Files:
- `harness/suites/terminal_bench.py:27-52`
- `harness/suites/terminal_bench.py:54-101`
- `harness/suites/terminal_bench.py:103-137`

Problems:
- `TerminalBenchSuite().get_task_ids()` returns `0` locally because it hardcodes `vendor/terminal-bench/tasks`, but this checkout has `original-tasks/` and no `tasks/` directory.
- `materialize_task()` returns an empty prompt and does not create a runnable task workdir, so the normal runner path just launches an adapter against an empty task.
- `verify()` looks for `workdir/.harbor/score.json`, but Harbor writes job outputs under a jobs directory, not inside this per-trial workdir.
- `run_harbor_job()` is never called by `runner.py`.
- `run_harbor_job()` uses `-n` for attempts, but current `harbor run --help` says `-n` is concurrency and `-k/--n-attempts` is attempts.
- `run_harbor_job()` does not pass a model with `--model/-m`.
- The generated plugin import path for pi adapters is bogus: `f"harness.suites.terminal_bench:{adapter_name.capitalize()}Agent"` yields names like `Pi_vanillaAgent`, and no such classes exist.

Impact: P11 is not implemented in a usable way. A Terminal-Bench run through `harness/runner.py --suite terminal_bench` will run zero tasks or empty pseudo-tasks, not Harbor-scored Terminal-Bench trials.

### 5. Aider Polyglot setup/suite is wired to a placeholder dataset shape, not the real benchmark

Files:
- `scripts/setup.sh:117-120`
- `harness/suites/aider_polyglot.py:31-45`
- `harness/suites/aider_polyglot.py:59-90`
- `tests/test_harness.py:147-167`

The setup script clones `https://github.com/Aider-AI/aider-polyglot.git` and silently creates a placeholder if that fails. The checked-out local `vendor/aider-polyglot` has only one synthetic `python/hello` task, and `AiderPolyglotSuite().get_task_ids()` returns `['python/hello']`, not 225 tasks.

The Terminal-Bench Aider adapter documentation in the vendored repo points to `https://github.com/Aider-AI/polyglot-benchmark` and describes Exercism-style language directories and generated Terminal-Bench tasks. Ornith's suite assumes a simplified `vendor/aider-polyglot/problems/<lang>/<problem>/{problem.txt,starter,tests}` shape. The tests create that fake shape, so they do not validate the real benchmark.

Impact: P9 and P10 are not meaningfully complete. The harness can only run a toy task in the current vendor tree, and the setup path can report success after creating a placeholder.

## High-Severity Gaps

### 6. The runner verifies even after adapter failure

File: `harness/runner.py:134-158`

If an adapter returns `-1` or throws, the runner still calls `suite.verify(task_data, workdir)`. That can produce false passes when starter code already passes, when tests are absent, or when a verifier is disconnected from adapter execution. Adapter failure should be represented in the verdict and should normally skip suite verification unless explicitly configured otherwise.

### 7. `pi_devstack` is not the canonical devstack profile

File: `harness/adapters/pi_devstack.py:41-64`

The plan says this arm should launch "whatever `pi-setup.sh` configures" and represent "pi as we actually run it day-to-day." The implementation adds `--no-extensions --no-skills`, then manually scans `~/.pi/agent/extensions` and loads top-level files or `*.ts` children. That does not preserve the normal devstack discovery/settings behavior, and it omits other configured surfaces such as prompt templates, themes, enabled/disabled package resources, and any extension layouts that are not a single file or one-level `*.ts`.

Impact: this does not measure the intended `pi_devstack` condition.

### 8. Superpowers ablation does not strip interactive skill flows

Files:
- `harness/adapters/pi_superpowers.py:54-58`
- `harness/adapters/little_coder_superpowers.py:48-51`

The plan explicitly says the bench condition should strip interactive skill-check flows and keep only systematic debugging plus verification skills. Both adapters simply add the entire `~/.pi/agent/skills` directory. That can include arbitrary normal user skills and interactive flows, and it is not a controlled Superpowers bench subset.

Impact: P14 does not implement the intended 2x2 ablation and may stall headless runs.

### 9. Model reachability is not enforced

Files:
- `PLAN.md:137-138`
- `scripts/check-models.sh:109-142`
- `harness/runner.py:183-211`

The plan says the runner refuses to start if a model in the matrix is unreachable. The runner never calls any model check. `scripts/check-models.sh` also treats no provider endpoint as `SKIP`, does not increment `DEAD`, and exits 0. In this environment it printed seven skipped models and then:

```text
Alive:  0
Dead:   0
Total:  0
```

Impact: an unreachable matrix can look clean before failing later inside the adapters.

### 10. Manifest fields required by the plan are missing or placeholders

Files:
- `PLAN.md:49-50`
- `PLAN.md:140-144`
- `harness/runner.py:102-124`

Missing or weak fields:
- no parsed provider field
- no sampling params
- no served model name
- no tool-call parser/config identifier
- no run end time, only `created_at`
- `env.hash` is just `sys.executable`, not a hash of the environment
- no Harbor version or Terminal-Bench pin/patch hash

Impact: results will not be comparable or auditable in the way the plan requires.

### 11. The tests give a false sense of coverage

File: `tests/test_harness.py`

Issues:
- They mock `subprocess.run`, so they miss the invalid `stderr=Path` bug.
- They assert `-m`, which the installed CLIs reject.
- They create a fake Aider dataset layout instead of validating the vendored benchmark.
- They do not cover Terminal-Bench behavior.
- They do not cover `view-scores/server.py`.
- They do not cover `scripts/check-models.sh` or `scripts/run-matrix.sh`.
- There is no pytest collection config. `mamba run -n coding-eval python -m pytest -q` from repo root collects vendored benchmark tests and fails with 267 collection errors. Only `python -m pytest -q tests` passes.

Impact: the headline "12 unit tests" does not protect the harness's load-bearing behavior.

## Medium-Severity Gaps

### 12. `run-matrix.sh` does not run the planned matrix safely

File: `scripts/run-matrix.sh:16-30`, `scripts/run-matrix.sh:65-75`

The default matrix contains only one model instead of `configs/models.yaml`. `--models` and `--adapters` only consume one shell word, while `RESULTS.md:105-109` documents multiple words. The script builds a command string and executes it with `eval`, which is unnecessary and brittle for model IDs, paths, and future arguments.

### 13. Score semantics are inconsistent for repeated trials

Files:
- `view-scores/server.py:134-149`
- `view-scores/server.py:214-224`

The summary counts raw trials as independent samples. The task detail view groups trials by task and marks a task passed if any trial passed. Those are different metrics. For `k=3`, the viewer needs a deliberate definition such as per-attempt pass rate, per-task majority, or pass@k, and the confidence interval should match that definition.

### 14. Suite task discovery ignores `--vendor-dir`

Files:
- `harness/runner.py:45`, `harness/runner.py:190-191`
- `harness/suites/aider_polyglot.py:31-35`
- `harness/suites/terminal_bench.py:27-31`

`materialize_task()` receives `vendor_dir`, but `get_task_ids()` does not. Both suites hardcode `vendor/...` relative to the current working directory. Passing `--vendor-dir` can materialize from one location after discovering tasks from another.

### 15. Verifier output drops important diagnostics

File: `harness/suites/aider_polyglot.py:118-135`

Only stdout is stored in `grader_output`; stderr is discarded. Many test runners put failures, stack traces, and build errors on stderr. This will make failed runs hard to diagnose and may hide compiler/test-runner failures.

## Verification Commands Run

```bash
git status -sb
git log --oneline -n 8
mamba run -n coding-eval python -m pytest -q
mamba run -n coding-eval python -m pytest -q tests
pi --help
little-coder --help
pi -m test/model --offline --no-session --print hi
little-coder -m test/model --offline --no-session --print hi
harbor run --help
bash scripts/check-models.sh
mamba run -n coding-eval python -c "from harness.suites.terminal_bench import TerminalBenchSuite; print(len(TerminalBenchSuite().get_task_ids()))"
mamba run -n coding-eval python -c "from harness.suites.aider_polyglot import AiderPolyglotSuite; print(AiderPolyglotSuite().get_task_ids())"
```

Observed:
- `python -m pytest -q` from repo root fails by collecting `vendor/` tests.
- `python -m pytest -q tests` passes: `12 passed in 0.02s`.
- `pi` version is `0.79.7`.
- both `pi -m ...` and `little-coder -m ...` fail with `Unknown option: -m`.
- `TerminalBenchSuite().get_task_ids()` returns `0`.
- `AiderPolyglotSuite().get_task_ids()` returns only `['python/hello']`.
- `scripts/check-models.sh` skips all seven configured models but reports total zero.

## Recommended Remediation Order

1. Fix adapter process launching first: open stderr files correctly, use `--model`, pass the prompt in the way `pi --print` actually expects, stop swallowing exceptions, and add one integration test with a fake executable instead of a mocked `subprocess.run`.
2. Define a path encoding for model IDs and task IDs, then update runner and viewer together. Add a viewer test using a model ID and task ID that both contain `/`.
3. Replace the toy Aider Polyglot implementation with the real `polyglot-benchmark` layout or use the vendored Terminal-Bench Aider adapter to generate tasks.
4. Rebuild Terminal-Bench support around Harbor's current CLI: `--agent`, custom agent import path if needed, `--model`, `--n-attempts/-k`, proper jobs output parsing, and the documented dataset path/version.
5. Add pytest config to ignore `vendor/`, then make bare `pytest` the expected test command.
6. Make `check-models.sh` or runner-level reachability checks fail closed when no configured model can be pinged.
7. Only after those are fixed, revisit P13/P14/P15. The current `RESULTS.md` is a template, not a results write-up.
