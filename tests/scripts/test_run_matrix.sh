#!/usr/bin/env bash
# Tests for scripts/run-matrix.sh.
#
# Reproduces ORNITH-CODER-REVIEW.md follow-up audit item F:
#   1. With no args, `${#ADAPTERS[@]}` under `set -u` crashes with
#      "ADAPTERS: unbound variable" before ADAPTERS is initialized.
#   2. The --problems branch double-runs: once without --problems (full suite)
#      and once with --problems N.
#
# We replace the runner with a no-op recorder so we can count invocations.

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
source "$SCRIPT_DIR/lib.sh"

echo "── test_run_matrix.sh ──"

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

# Fake project: copy run-matrix.sh and configs/, stub the runner.
PROJ="$TMP/proj"
mkdir -p "$PROJ/scripts" "$PROJ/configs" "$PROJ/harness"
cp "$PROJECT_DIR/scripts/run-matrix.sh" "$PROJ/scripts/run-matrix.sh"
cat > "$PROJ/configs/models.yaml" <<'EOF'
models:
  - id: fake/model-one
EOF

# Stub runner.py: record each invocation's argv to a log, exit 0.
cat > "$PROJ/harness/runner.py" <<'EOF'
import sys, os
LOG = os.environ.get("RUNNER_LOG", "/tmp/run-matrix-runner.log")
with open(LOG, "a") as f:
    f.write(" ".join(sys.argv[1:]) + "\n")
EOF

RUNNER_LOG="$TMP/runner.log"
export RUNNER_LOG="$RUNNER_LOG"
rm -f "$RUNNER_LOG"

# Patch the script to call `python harness/runner.py` from our fake project
# instead of `mamba run -n coding-eval python $PROJECT_DIR/harness/runner.py`.
# We do this by setting PROJECT_DIR inside the script via an env shim.
#
# Easier: copy the script and sed-replace the mamba invocation with our stub.
sed -i \
    -e "s|^PROJECT_DIR=.*|PROJECT_DIR=\"$PROJ\"|" \
    -e 's|mamba run -n coding-eval python "$PROJECT_DIR/harness/runner.py"|python "$PROJECT_DIR/harness/runner.py"|g' \
    "$PROJ/scripts/run-matrix.sh"

# Test 1: no args must not crash; must invoke runner once per (model x adapter)
rm -f "$RUNNER_LOG"
OUT=$(bash "$PROJ/scripts/run-matrix.sh" 2>&1)
RC=$?
assert_exit 0 "$RC" "no-args invocation exits 0 (no unbound variable)"
assert_not_contains "unbound variable" "$OUT" "no 'unbound variable' error"
# Default adapters are pi_vanilla, pi_devstack, little_coder (3) x 1 model = 3 runs
N_RUNS=$(wc -l < "$RUNNER_LOG" 2>/dev/null || echo 0)
if [[ "$N_RUNS" -eq 3 ]]; then
    echo "  ✓ default matrix runs 3 cells (1 model x 3 adapters)"
    PASS=$((PASS + 1))
else
    echo "  ✗ default matrix runs 3 cells (got $N_RUNS runs)"
    FAIL=$((FAIL + 1))
fi
RUN_ID_COUNT=$(grep -c -- "--run-id" "$RUNNER_LOG" 2>/dev/null || echo 0)
if [[ "$RUN_ID_COUNT" -eq 3 ]]; then
    echo "  ✓ default matrix forwards a run id to every cell"
    PASS=$((PASS + 1))
else
    echo "  ✗ default matrix forwards a run id to every cell (got $RUN_ID_COUNT)"
    FAIL=$((FAIL + 1))
fi

# Test 2: --problems must NOT double-run each cell
rm -f "$RUNNER_LOG"
OUT=$(bash "$PROJ/scripts/run-matrix.sh" --models fake/model-one --adapters pi_vanilla --problems 5 2>&1)
RC=$?
assert_exit 0 "$RC" "--problems invocation exits 0"
N_RUNS=$(wc -l < "$RUNNER_LOG" 2>/dev/null || echo 0)
if [[ "$N_RUNS" -eq 1 ]]; then
    echo "  ✓ --problems runs each cell exactly once"
    PASS=$((PASS + 1))
else
    echo "  ✗ --problems runs each cell exactly once (got $N_RUNS runs — double-run bug)"
    FAIL=$((FAIL + 1))
fi
# The single run must carry --problems 5
if grep -q -- "--problems 5" "$RUNNER_LOG"; then
    echo "  ✓ --problems 5 forwarded to runner"
    PASS=$((PASS + 1))
else
    echo "  ✗ --problems 5 forwarded to runner (log: $(cat "$RUNNER_LOG"))"
    FAIL=$((FAIL + 1))
fi

# Test 2b: explicit --run-id must be forwarded exactly
rm -f "$RUNNER_LOG"
OUT=$(bash "$PROJ/scripts/run-matrix.sh" --models fake/model-one --adapters pi_vanilla --run-id matrix-a 2>&1)
RC=$?
assert_exit 0 "$RC" "--run-id invocation exits 0"
assert_contains "--run-id matrix-a" "$(cat "$RUNNER_LOG")" "--run-id forwarded to runner"

# Test 2c: explicit --thinking must be forwarded exactly
rm -f "$RUNNER_LOG"
OUT=$(bash "$PROJ/scripts/run-matrix.sh" --models fake/model-one --adapters pi_vanilla --thinking high 2>&1)
RC=$?
assert_exit 0 "$RC" "--thinking invocation exits 0"
assert_contains "--thinking high" "$(cat "$RUNNER_LOG")" "--thinking forwarded to runner"

# Test 3: options that require values must fail cleanly, not via set -u
OUT=$(bash "$PROJ/scripts/run-matrix.sh" --k 2>&1)
RC=$?
assert_exit 1 "$RC" "--k without value exits nonzero"
assert_contains "Error: --k requires an argument" "$OUT" "--k missing value has clear error"
assert_not_contains "unbound variable" "$OUT" "--k missing value avoids shell unbound-variable error"

# Test 4: numeric options must be positive integers
OUT=$(bash "$PROJ/scripts/run-matrix.sh" --models fake/model-one --adapters pi_vanilla --k 0 2>&1)
RC=$?
assert_exit 1 "$RC" "--k 0 exits nonzero"
assert_contains "Error: --k must be a positive integer" "$OUT" "--k 0 has clear error"

OUT=$(bash "$PROJ/scripts/run-matrix.sh" --models fake/model-one --adapters pi_vanilla --problems -1 2>&1)
RC=$?
assert_exit 1 "$RC" "--problems -1 exits nonzero"
assert_contains "Error: --problems must be a positive integer" "$OUT" "--problems -1 has clear error"

summary
