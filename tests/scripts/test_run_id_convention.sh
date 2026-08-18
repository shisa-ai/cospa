#!/usr/bin/env bash
# Tests for the canonical run-id convention (docs/RUN-MANAGEMENT.md):
#
#   <model-slug>-<suite-slug>[-<adapter-slug>]-<effort>-c<concurrency>-<YYYYMMDD>T<HHMM>Z
#
#   1. make_run_id emits the canonical form for a known model+suite.
#   2. run-matrix.sh's auto-generated run-id (single model) follows it.
#   3. Adapter slugs: pi_vanilla omitted, pi_devstack included.
#   4. Unknown ids fall back to a derived slug; multi-model falls back to a
#      unique timestamp id (not a single-model conventional id).

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
source "$SCRIPT_DIR/lib.sh"
source "$PROJECT_DIR/scripts/run-id-lib.sh"

echo "── test_run_id_convention.sh ──"

# Test 1: make_run_id canonical form (known model + suite).
RID=$(make_run_id local/qwen3.8-27b-fp8-block bigcodebench_hard_agentic_pareto60 high 8 pi_vanilla)
if [[ "$RID" =~ ^qwen38-fp8block-bcb-pareto60-high-c8-[0-9]{8}T[0-9]{4}Z$ ]]; then
    echo "  ✓ make_run_id canonical form: $RID"
    PASS=$((PASS + 1))
else
    echo "  ✗ make_run_id canonical form (got: '$RID')"
    FAIL=$((FAIL + 1))
fi

# Test 2: effort omitted when thinking is unset.
RID=$(make_run_id local/qwen3.8-27b-fp8-block bigcodebench_hard_agentic_pareto60 "" 8 pi_vanilla)
if [[ "$RID" =~ ^qwen38-fp8block-bcb-pareto60-c8-[0-9]{8}T[0-9]{4}Z$ ]]; then
    echo "  ✓ effort omitted when unset: $RID"
    PASS=$((PASS + 1))
else
    echo "  ✗ effort omitted when unset (got: '$RID')"
    FAIL=$((FAIL + 1))
fi

# Test 3: non-default adapter included (pi_devstack), unknown model derived.
RID=$(make_run_id local/qwen3.8-27b-fp8-block bigcodebench_hard_agentic_hermetic143 xhigh 2 pi_devstack)
if [[ "$RID" =~ ^qwen38-fp8block-bcb-agentic-hermetic143-pi_devstack-xhigh-c2-[0-9]{8}T[0-9]{4}Z$ ]]; then
    echo "  ✓ adapter slug included for pi_devstack: $RID"
    PASS=$((PASS + 1))
else
    echo "  ✗ adapter slug included for pi_devstack (got: '$RID')"
    FAIL=$((FAIL + 1))
fi

# Test 4: run-matrix.sh auto-generated run-id follows the convention for a
# single model; multi-model falls back to a unique timestamp id.
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
cat > "$PROJ/harness/runner.py" <<'EOF'
import sys, os
LOG = os.environ.get("RUNNER_LOG", "/tmp/run-id-runner.log")
with open(LOG, "a") as f:
    f.write(" ".join(sys.argv[1:]) + "\n")
EOF
sed -i \
    -e "s|^PROJECT_DIR=.*|PROJECT_DIR=\"$PROJ\"|" \
    -e 's|mamba run -n coding-eval python "$PROJECT_DIR/harness/runner.py"|python "$PROJECT_DIR/harness/runner.py"|g' \
    "$PROJ/scripts/run-matrix.sh"

RUNNER_LOG="$TMP/runner.log"
export RUNNER_LOG="$RUNNER_LOG"

# 4a: single model, single adapter -> conventional run-id forwarded.
rm -f "$RUNNER_LOG"
OUT=$(bash "$PROJ/scripts/run-matrix.sh" \
    --models local/qwen3.8-27b-fp8-block --adapters pi_vanilla \
    --suite bigcodebench_hard_agentic_pareto60 --thinking high --k 8 2>&1)
RC=$?
assert_exit 0 "$RC" "single-model run-matrix exits 0"
RID_FWD=$(grep -oE -- "--run-id [^ ]+" "$RUNNER_LOG" | head -1 | awk '{print $2}')
if [[ "$RID_FWD" =~ ^qwen38-fp8block-bcb-pareto60-high-c8-[0-9]{8}T[0-9]{4}Z-[0-9]+$ ]]; then
    echo "  ✓ run-matrix auto run-id is conventional: $RID_FWD"
    PASS=$((PASS + 1))
else
    echo "  ✗ run-matrix auto run-id is conventional (got: '$RID_FWD')"
    FAIL=$((FAIL + 1))
fi

# 4b: multiple models -> still a unique run-id, but not a single-model id.
rm -f "$RUNNER_LOG"
OUT=$(bash "$PROJ/scripts/run-matrix.sh" \
    --models local/qwen3.8-27b-fp8-block,fake/model-one --adapters pi_vanilla \
    --suite bigcodebench_hard_agentic_pareto60 --thinking high --k 8 2>&1)
RC=$?
assert_exit 0 "$RC" "multi-model run-matrix exits 0"
RID_FWD=$(grep -oE -- "--run-id [^ ]+" "$RUNNER_LOG" | head -1 | awk '{print $2}')
if [[ -n "$RID_FWD" && "$RID_FWD" != "qwen38-fp8block-bcb-pareto60-high-c8-"* ]]; then
    echo "  ✓ multi-model falls back to a unique id: $RID_FWD"
    PASS=$((PASS + 1))
else
    echo "  ✗ multi-model falls back to a unique id (got: '$RID_FWD')"
    FAIL=$((FAIL + 1))
fi

summary
