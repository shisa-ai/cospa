#!/usr/bin/env bash
# run-matrix.sh — Run the full eval matrix.
#
# Usage:
#   bash scripts/run-matrix.sh [--models ...] [--adapters ...] [--k 3] [--problems 225]
#
# Example:
#   bash scripts/run-matrix.sh --models nvidia/nemotron-3-ultra-550b-a55b --adapters pi_vanilla --k 1 --problems 5

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# Defaults
K=1
PROBLEMS=""
SUITE="aider_polyglot"
MODELS_FILE="$PROJECT_DIR/configs/models.yaml"

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

echo "── Running matrix ──"
echo "  Models: ${MODELS[*]}"
echo "  Adapters: ${ADAPTERS[*]}"
echo "  K: $K"
echo "  Problems: ${PROBLEMS:-all}"
echo "  Suite: $SUITE"
echo ""

# Run each model x adapter combination exactly once. If --problems is set,
# forward it; otherwise run the full suite. (Previously the script ran the
# full suite once AND then ran the --problems subset — a double-run.)
PROBLEMS_ARG=()
if [[ -n "$PROBLEMS" ]]; then
    PROBLEMS_ARG=(--problems "$PROBLEMS")
fi

for MODEL in "${MODELS[@]}"; do
    for ADAPTER in "${ADAPTERS[@]}"; do
        echo "── Model: $MODEL, Adapter: $ADAPTER ──"

        mamba run -n coding-eval python "$PROJECT_DIR/harness/runner.py" \
            --suite "$SUITE" \
            --adapter "$ADAPTER" \
            --model "$MODEL" \
            --k "$K" \
            "${PROBLEMS_ARG[@]}"

        echo ""
    done
done

echo "── Matrix complete ──"
