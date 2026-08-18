#!/usr/bin/env bash
# run-matrix.sh — Run the full eval matrix.
#
# Usage:
#   bash scripts/run-matrix.sh [--models ...] [--adapters ...] [--k 3] [--problems 225] [--run-id ...] [--thinking high] [--force]
#
# Example:
#   bash scripts/run-matrix.sh --models local/ornith-1.0-35b --adapters pi_vanilla --k 1 --problems 5 --thinking high
#
# Run-id naming (docs/RUN-MANAGEMENT.md): pass --run-id in the canonical
#   <model>-<suite>[-<adapter>]-<effort>-c<concurrency>-<YYYYMMDD>T<HHMM>Z
# form (e.g. qwen38-fp8block-bcb-pareto60-high-c8-20260818T0415Z). When
# omitted, a conventional-prefixed id plus a unique pid is generated.
#
# Resume/checkpoint (RUN-MANAGEMENT P4): a per-run state file records each
# cell as pending/running/done/paused. Re-invoking with the SAME --run-id
# skips cells already done or paused (e.g. paused by the circuit breaker)
# so no budget is wasted; --force ignores the state and re-runs everything.
# The runner's own per-trial resume covers a cell interrupted mid-run.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# Canonical run-id construction (docs/RUN-MANAGEMENT.md naming convention).
source "$SCRIPT_DIR/run-id-lib.sh"

# Defaults
K=1
PROBLEMS=""
SUITE="aider_polyglot"
MODELS_FILE="$PROJECT_DIR/configs/models.yaml"
RUN_ID=""
THINKING=""
FORCE=0

# Cell state persistence: flat JSON keyed by "model|adapter" in a per-run
# state file. Helper bodies use plain python (not mamba) so they run in the
# script's shell test harness too.
_cell_state() {
    # $1=model $2=adapter -> prints "pending"/"running"/"done"/"paused"
    python3 - "$STATE_FILE" "$1" "$2" <<'PY'
import json, os, sys
path = sys.argv[1]
if not os.path.exists(path):
    sys.stdout.write("pending")
    sys.exit(0)
try:
    data = json.load(open(path))
except Exception:
    sys.stdout.write("pending")
    sys.exit(0)
sys.stdout.write(data.get("cells", {}).get(f"{sys.argv[2]}|{sys.argv[3]}", "pending"))
PY
}

_set_cell_state() {
    # $1=state $2=model $3=adapter
    mkdir -p "$PROJECT_DIR/results/runs"
    python3 - "$STATE_FILE" "$1" "$2" "$3" <<'PY'
import json, os, sys
path, state, model, adapter = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
data = {}
if os.path.exists(path):
    try:
        data = json.load(open(path))
    except Exception:
        data = {}
data.setdefault("cells", {})[f"{model}|{adapter}"] = state
tmp = path + ".tmp"
with open(tmp, "w") as f:
    json.dump(data, f, indent=2, sort_keys=True)
os.replace(tmp, path)
PY
}


# Initialize arrays empty so `${#ARR[@]}` is safe under `set -u` before the
# user provides --models/--adapters.
MODELS=()
ADAPTERS=()

require_value() {
    local option="$1"
    if [[ $# -lt 2 || -z "$2" || "$2" == --* ]]; then
        echo "Error: $option requires an argument"
        exit 1
    fi
}

require_positive_integer() {
    local option="$1"
    local value="$2"
    if [[ ! "$value" =~ ^[1-9][0-9]*$ ]]; then
        echo "Error: $option must be a positive integer"
        exit 1
    fi
}

# Parse args
while [[ $# -gt 0 ]]; do
    case $1 in
        --models)
            # Accept multiple models as separate arguments or comma-separated
            require_value "$1" "${2:-}"
            IFS=',' read -ra MODES <<< "$2"
            MODELS=("${MODES[@]}")
            shift 2
            ;;
        --adapters)
            require_value "$1" "${2:-}"
            IFS=',' read -ra ADAPTERS <<< "$2"
            shift 2
            ;;
        --k)
            require_value "$1" "${2:-}"
            require_positive_integer "$1" "$2"
            K=$2
            shift 2
            ;;
        --problems)
            require_value "$1" "${2:-}"
            require_positive_integer "$1" "$2"
            PROBLEMS=$2
            shift 2
            ;;
        --suite)
            require_value "$1" "${2:-}"
            SUITE=$2
            shift 2
            ;;
        --models-file)
            require_value "$1" "${2:-}"
            MODELS_FILE=$2
            shift 2
            ;;
        --run-id)
            require_value "$1" "${2:-}"
            RUN_ID=$2
            shift 2
            ;;
        --thinking)
            require_value "$1" "${2:-}"
            THINKING=$2
            shift 2
            ;;
        --force)
            FORCE=1
            shift
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

# Load default adapters if not specified
if [[ ${#ADAPTERS[@]} -eq 0 ]]; then
    ADAPTERS=("pi_vanilla" "pi_devstack" "little_coder")
fi

# Load models from file if not specified via --models
if [[ ${#MODELS[@]} -eq 0 ]]; then
    if [[ -f "$MODELS_FILE" ]]; then
        mapfile -t MODELS < <(grep '^\s*- id:' "$MODELS_FILE" | sed 's/.*- id:\s*//')
    else
        echo "Error: No models specified and $MODELS_FILE not found"
        exit 1
    fi
fi

# Generate a conventional run-id (docs/RUN-MANAGEMENT.md) when none was
# passed. Single-model cells get <model>-<suite>[-<adapter>]-<effort>-c<K>-<date>;
# multi-model matrices fall back to a unique timestamp id rather than naming
# one model. Explicit --run-id is always honored (and required to resume).
if [[ -z "$RUN_ID" ]]; then
    if [[ ${#MODELS[@]} -eq 1 ]]; then
        # Conventional prefix + pid: unique so a no-run-id invocation always
        # runs fresh (explicit --run-id is what makes a run resumable).
        RUN_ID="$(make_run_id "${MODELS[0]}" "$SUITE" "$THINKING" "$K" "${ADAPTERS[@]}")-$$"
    else
        RUN_ID="$(date -u +%Y%m%dT%H%M%S.%NZ)-$$"
    fi
fi

# Resolve the per-run state file after --run-id is finalized.
STATE_FILE="$PROJECT_DIR/results/runs/.matrix-${RUN_ID}.json"

echo "── Running matrix ──"
echo "  Models: ${MODELS[*]}"
echo "  Adapters: ${ADAPTERS[*]}"
echo "  K: $K"
echo "  Problems: ${PROBLEMS:-all}"
echo "  Suite: $SUITE"
echo "  Run ID: $RUN_ID"
echo "  Thinking: ${THINKING:-default}"
echo ""

# Run each model x adapter combination exactly once. If --problems is set,
# forward it; otherwise run the full suite. (Previously the script ran the
# full suite once AND then ran the --problems subset — a double-run.)
PROBLEMS_ARG=()
if [[ -n "$PROBLEMS" ]]; then
    PROBLEMS_ARG=(--problems "$PROBLEMS")
fi
THINKING_ARG=()
if [[ -n "$THINKING" ]]; then
    THINKING_ARG=(--thinking "$THINKING")
fi

for MODEL in "${MODELS[@]}"; do
    for ADAPTER in "${ADAPTERS[@]}"; do
        STATE=pending
        if [[ "$FORCE" -eq 0 ]]; then
            STATE=$(_cell_state "$MODEL" "$ADAPTER")
        fi
        if [[ "$STATE" == "done" || "$STATE" == "paused" ]]; then
            echo "  ↻ skip $MODEL / $ADAPTER (state: $STATE)"
            continue
        fi
        echo "── Model: $MODEL, Adapter: $ADAPTER ──"
        _set_cell_state "running" "$MODEL" "$ADAPTER"

        set +e
        mamba run -n coding-eval python "$PROJECT_DIR/harness/runner.py" \
            --suite "$SUITE" \
            --adapter "$ADAPTER" \
            --model "$MODEL" \
            --k "$K" \
            --run-id "$RUN_ID" \
            "${THINKING_ARG[@]}" \
            "${PROBLEMS_ARG[@]}"
        rc=$?
        set -e

        case $rc in
            0)
                _set_cell_state "done" "$MODEL" "$ADAPTER"
                echo "  ✓ complete"
                ;;
            3)
                # Circuit breaker tripped (RUN-MANAGEMENT P1): pause the cell.
                _set_cell_state "paused" "$MODEL" "$ADAPTER"
                echo "  ⚠ paused (circuit breaker); skipped on future resumes"
                ;;
            *)
                # Abort the matrix: a cell failing outside 0/3 (e.g. model
                # unreachable) should not burn the remaining budget.
                _set_cell_state "running" "$MODEL" "$ADAPTER"
                echo "  ✗ cell failed (exit $rc)" >&2
                exit "$rc"
                ;;
        esac

        echo ""
    done
done

echo "── Matrix complete ──"
