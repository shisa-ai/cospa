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

# Parse args
while [[ $# -gt 0 ]]; do
    case $1 in
        --models)
            # Accept multiple models as separate arguments or comma-separated
            if [[ $# -ge 2 ]]; then
                IFS=',' read -ra MODES <<< "$2"
                MODELS=("${MODES[@]}")
                shift 2
            else
                echo "Error: --models requires an argument"
                exit 1
            fi
            ;;
        --adapters)
            if [[ $# -ge 2 ]]; then
                IFS=',' read -ra ADAPTERS <<< "$2"
                shift 2
            else
                echo "Error: --adapters requires an argument"
                exit 1
            fi
            ;;
        --k)
            K=$2
            shift 2
            ;;
        --problems)
            PROBLEMS=$2
            shift 2
            ;;
        --suite)
            SUITE=$2
            shift 2
            ;;
        --models-file)
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

# Run each model x adapter combination
for MODEL in "${MODELS[@]}"; do
    for ADAPTER in "${ADAPTERS[@]}"; do
        echo "── Model: $MODEL, Adapter: $ADAPTER ──"

        # Use proper quoting instead of eval
        mamba run -n coding-eval python "$PROJECT_DIR/harness/runner.py" \
            --suite "$SUITE" \
            --adapter "$ADAPTER" \
            --model "$MODEL" \
            --k "$K"

        if [[ -n "$PROBLEMS" ]]; then
            mamba run -n coding-eval python "$PROJECT_DIR/harness/runner.py" \
                --suite "$SUITE" \
                --adapter "$ADAPTER" \
                --model "$MODEL" \
                --k "$K" \
                --problems "$PROBLEMS"
        fi

        echo ""
    done
done

echo "── Matrix complete ──"
