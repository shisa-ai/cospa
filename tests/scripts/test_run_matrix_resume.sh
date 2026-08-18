#!/usr/bin/env bash
# Tests for run-matrix.sh self-resume / checkpoint (RUN-MANAGEMENT P4).
#
# A per-run state file records each cell as done/paused. Re-invoking with the
# same --run-id must skip done/paused cells (no runner invocation), while
# --force re-runs everything.

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
source "$SCRIPT_DIR/lib.sh"

echo "── test_run_matrix_resume.sh ──"

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

PROJ="$TMP/proj"
mkdir -p "$PROJ/scripts" "$PROJ/configs" "$PROJ/harness"
cp "$PROJECT_DIR/scripts/run-matrix.sh" "$PROJ/scripts/run-matrix.sh"
cp "$PROJECT_DIR/scripts/run-id-lib.sh" "$PROJ/scripts/run-id-lib.sh"
cat > "$PROJ/configs/models.yaml" <<'EOF'
models:
  - id: fake/model-one
EOF

# Stub runner: log argv, exit 3 when the cell matches PAUSE_MODEL/PAUSE_ADAPTER.
cat > "$PROJ/harness/runner.py" <<'EOF'
import os, sys
LOG = os.environ.get("RUNNER_LOG", "/tmp/run-matrix-resume.log")
argv = sys.argv[1:]
with open(LOG, "a") as f:
    f.write(" ".join(argv) + "\n")
model = adapter = None
for i, a in enumerate(argv):
    if a == "--model":
        model = argv[i + 1]
    if a == "--adapter":
        adapter = argv[i + 1]
if model == os.environ.get("PAUSE_MODEL") and adapter == os.environ.get("PAUSE_ADAPTER"):
    sys.exit(3)
sys.exit(0)
EOF

sed -i \
    -e "s|^PROJECT_DIR=.*|PROJECT_DIR=\"$PROJ\"|" \
    -e 's|mamba run -n coding-eval python "$PROJECT_DIR/harness/runner.py"|python "$PROJECT_DIR/harness/runner.py"|g' \
    "$PROJ/scripts/run-matrix.sh"

RUNNER_LOG="$TMP/runner.log"
export RUNNER_LOG="$RUNNER_LOG"
export PAUSE_MODEL="fake/model-one"
export PAUSE_ADAPTER="pi_vanilla"
rm -f "$RUNNER_LOG"

# First run: 2 cells (pi_vanilla exits 3 -> paused; pi_devstack exits 0 -> done).
OUT=$(bash "$PROJ/scripts/run-matrix.sh" \
    --models fake/model-one --adapters pi_vanilla,pi_devstack --run-id resume-a 2>&1)
RC=$?
assert_exit 0 "$RC" "first matrix run exits 0"
N_RUNS=$(wc -l < "$RUNNER_LOG")
if [[ "$N_RUNS" -eq 2 ]]; then
    echo "  ✓ first run invokes both cells"
    PASS=$((PASS + 1))
else
    echo "  ✗ first run invokes both cells (got $N_RUNS)"
    FAIL=$((FAIL + 1))
fi
assert_contains "paused (circuit breaker)" "$OUT" "paused cell reported"

STATE_FILE="$PROJ/results/runs/.matrix-resume-a.json"
if [[ -f "$STATE_FILE" ]]; then
    echo "  ✓ state file written for run-id"
    PASS=$((PASS + 1))
else
    echo "  ✗ state file written for run-id"
    FAIL=$((FAIL + 1))
fi
if grep -q '"fake/model-one|pi_vanilla": "paused"' "$STATE_FILE" \
    && grep -q '"fake/model-one|pi_devstack": "done"' "$STATE_FILE"; then
    echo "  ✓ state file records paused + done"
    PASS=$((PASS + 1))
else
    echo "  ✗ state file records paused + done (got: $(cat "$STATE_FILE"))"
    FAIL=$((FAIL + 1))
fi

# Resume with the same run-id: both cells skipped, no new invocations.
BEFORE=$(wc -l < "$RUNNER_LOG")
OUT=$(bash "$PROJ/scripts/run-matrix.sh" \
    --models fake/model-one --adapters pi_vanilla,pi_devstack --run-id resume-a 2>&1)
RC=$?
assert_exit 0 "$RC" "resume exits 0"
AFTER=$(wc -l < "$RUNNER_LOG")
if [[ "$AFTER" -eq "$BEFORE" ]]; then
    echo "  ✓ resume skips done+paused cells (no runner invocations)"
    PASS=$((PASS + 1))
else
    echo "  ✗ resume skips done+paused cells (invocations grew $BEFORE -> $AFTER)"
    FAIL=$((FAIL + 1))
fi
assert_contains "skip fake/model-one / pi_vanilla (state: paused)" "$OUT" "paused cell skipped on resume"
assert_contains "skip fake/model-one / pi_devstack (state: done)" "$OUT" "done cell skipped on resume"

# --force ignores state and re-runs everything.
BEFORE=$(wc -l < "$RUNNER_LOG")
OUT=$(bash "$PROJ/scripts/run-matrix.sh" \
    --models fake/model-one --adapters pi_vanilla,pi_devstack --run-id resume-a --force 2>&1)
RC=$?
assert_exit 0 "$RC" "--force run exits 0"
AFTER=$(wc -l < "$RUNNER_LOG")
if [[ "$AFTER" -eq $((BEFORE + 2)) ]]; then
    echo "  ✓ --force re-runs all cells"
    PASS=$((PASS + 1))
else
    echo "  ✗ --force re-runs all cells (invocations grew $BEFORE -> $AFTER)"
    FAIL=$((FAIL + 1))
fi

# A different run-id starts fresh (pending state, no skips).
BEFORE=$(wc -l < "$RUNNER_LOG")
OUT=$(bash "$PROJ/scripts/run-matrix.sh" \
    --models fake/model-one --adapters pi_vanilla,pi_devstack --run-id resume-b 2>&1)
RC=$?
assert_exit 0 "$RC" "fresh run-id exits 0"
AFTER=$(wc -l < "$RUNNER_LOG")
if [[ "$AFTER" -eq $((BEFORE + 2)) ]]; then
    echo "  ✓ a different run-id starts fresh"
    PASS=$((PASS + 1))
else
    echo "  ✗ a different run-id starts fresh (invocations grew $BEFORE -> $AFTER)"
    FAIL=$((FAIL + 1))
fi

summary
