# Process Improvements for Future Coding Passes

Written after the third audit of the Ornith coder-review pass. The third
audit found three real bugs (Terminal-Bench adapter collapse, `k`-overcount
in `run_trial`, Go scoring falsely failing) that a 64-test suite did not
catch. The pattern across all three is the same:

> **Tests validated the shape of the code against synthetic inputs, not the
> behavior of the code against real artifacts.**

This document captures the concrete process changes that would have caught
them. It is meant to be re-read before starting a fix pass.

---

## 1. Test against real vendored datasets, not only fixtures

**Symptom:** The Go scoring regex bug and the "polyglot not vendored" gap
both survived because tests used a `make_polyglot_problem` fixture that only
ever created Python problems. The Go regex was never exercised against real
`go test -v` output.

**Change:**

- Add a `@pytest.mark.requires_vendor` marker. Tests under it skip cleanly
  when `vendor/<dataset>` is absent but run in CI when it is present.
- Check in captured samples of each tool's real output
  (`tests/fixtures/go_test_v.txt`, `tests/fixtures/cargo_test.txt`,
  `tests/fixtures/pytest_v.txt`) and drive the language-specific scorers
  against them. One passing-sample and one failing-sample per language.
- Add a "discovery smoke" test that asserts `get_task_ids()` is non-empty
  when the vendor dir is populated, so an un-vendored dataset cannot
  silently pass as "fixed."

Fixtures are still valuable for unit-level edge cases, but they must
**augment** real-data tests, not replace them.

---

## 2. Boundary tests for loop semantics

**Symptom:** The `k`-overcount bug survived because only `k=1` was tested.
`main()` looped `k` in `1..args.k` and passed `k` as `n_attempts`, so
`--k 3` produced 1+2+3 = 6 attempts instead of 3 trials of 3.

**Change:** Any test that only exercises the default value of a numeric
parameter is a smell. For loops over user-controlled integers, test the
boundaries and assert on **total work done**, not just that one iteration
works:

```python
def test_k3_produces_three_trials_each_with_n_attempts_3():
    # assert len(trial_dirs) == 3
    # assert every harbor call had n_attempts == 3 (not 1, 2, 3)
```

Cheap review heuristic: "did we test the non-default value of every numeric
flag?" If not, write that test before claiming the feature works.

---

## 3. An ablation-equivalence invariant test

**Symptom:** All three pi variants (`pi_vanilla`, `pi_devstack`,
`pi_superpowers`) collapsed to the same Harbor `pi` agent, so a Terminal-Bench
matrix would measure the same command three times under different labels.

**Change:** Anywhere the design promises "N distinct configurations," add a
matrix-level invariant test that asserts they are actually distinct:

```python
def test_each_adapter_pair_produces_a_distinct_command():
    commands = {adapter: build_cmd(adapter, suite="terminal_bench")
                for adapter in ALL_ADAPTERS}
    assert len(set(map(tuple, commands.values()))) == len(commands)
```

This generalizes to models, suites, and any other axis the benchmark sweeps.

---

## 4. Run the thing once, for real, before claiming it works

**Symptom:** "Wired to Harbor" was shipped without running Harbor once, and
"Go scoring works" was shipped without running `go test` once.

**Change:** Before marking any feature "Fixed" in the review doc, tick off
a pre-merge checklist:

- [ ] Did at least one trial of each suite actually execute end-to-end
      (not mocked subprocess)?
- [ ] Did at least one trial of each **language** in a multi-language suite
      pass and fail?
- [ ] Is the vendored dataset present, or is the suite explicitly marked
      experimental in code and docs?

If Docker / Harbor / a model endpoint is not available in the dev
environment, mark the code `# experimental - not yet verified end-to-end`
and reflect that status in the review doc. Do not assert "Fixed" on the
strength of a mock-passing test alone.

---

## 5. Tighten the review-doc status vocabulary

**Symptom:** The Second Follow-up Audit said "Fixed" with a covering test,
but the test did not always cover the *claim* (it covered a related shape).

**Change:** The review doc's status column should carry an explicit evidence
type, not a bare "Fixed." Suggested vocabulary:

| Status | Meaning |
|---|---|
| `fixed (unit test)` | Covered by a mock/fixture test |
| `fixed (integration test)` | Covered by a test that runs the real code path |
| `fixed (end-to-end)` | Actually executed against the real tool / dataset |
| `wired (unverified)` | Code is in place but not yet executed end-to-end |
| `partial (see notes)` | Some cases fixed, others remain |

This makes it harder to accidentally upgrade a mock-passing test into a
"Fixed" claim.

---

## 6. Pre-commit gate that runs both test suites

**Symptom:** Shell-script tests (`check-models.sh`, `run-matrix.sh`) are
wired into pytest via `tests/test_scripts.py`, but nothing forces them to
run before a commit.

**Change:** Add a `make test` (or `just test`) target and a git pre-commit
hook that runs both:

```make
test:
	mamba run -n coding-eval python -m pytest -q
	bash tests/scripts/run_all.sh
```

```bash
# .git/hooks/pre-commit
make test || exit 1
```

This prevents regressions like the `check-models.sh` `((SKIPPED++))`
arithmetic-zero bug from being re-introduced in a haste commit.

---

## Meta-lesson

Mocks and fixtures exist for **speed and edge-case coverage**; they cannot
substitute for at least one real end-to-end run per code path. The third
audit's three blockers were all "shape-correct but behavior-wrong" bugs —
exactly the category that only real-artifact testing catches.

If only one change from this list is adopted, make it **#4**: run each
suite once against a real dataset and a real toolchain before claiming the
fix is green.
