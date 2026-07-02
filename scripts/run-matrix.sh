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
MODELS=("nvidia/nemotron-3-ultra-550b-a55b")
ADAPTERS=("pi_vanilla" "pi_devstack" "little_coder")
K=1
PROBLEMS=""
SUITE="aider_polyglot"

# Parse args
while [[ $# -gt 0 ]]; do
    case $1 in
        --models)
            MODELS=($2)
            shift 2
            ;;
        --adapters)
            ADAPTERS=($2)
            shift 2
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
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

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

        CMD="mamba run -n coding-eval python $PROJECT_DIR/harness/runner.py"
        CMD+=" --suite $SUITE"
        CMD+=" --adapter $ADAPTER"
        CMD+=" --model $MODEL"
        CMD+=" --k $K"

        if [[ -n "$PROBLEMS" ]]; then
            CMD+=" --problems $PROBLEMS"
        fi

        eval $CMD
        echo ""
    done
done

echo "── Matrix complete ──"
