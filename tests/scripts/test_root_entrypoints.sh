#!/usr/bin/env bash
# Tests for root-level run/view convenience entrypoints.

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
source "$SCRIPT_DIR/lib.sh"

echo "── test_root_entrypoints.sh ──"

if [[ -x "$PROJECT_DIR/run" ]]; then
    echo "  ✓ ./run is executable"
    PASS=$((PASS + 1))
else
    echo "  ✗ ./run is executable"
    FAIL=$((FAIL + 1))
fi

OUT=$("$PROJECT_DIR/run" --help 2>&1)
RC=$?
assert_exit 0 "$RC" "./run --help exits 0"
assert_contains "Usage: ./run" "$OUT" "./run help shows root command"
assert_contains "scripts/run-matrix.sh" "$OUT" "./run help names underlying matrix runner"

OUT=$("$PROJECT_DIR/run" 2>&1)
RC=$?
assert_exit 0 "$RC" "./run with no args exits 0"
assert_contains "Usage: ./run" "$OUT" "./run with no args shows help instead of starting a matrix"

if [[ -x "$PROJECT_DIR/view" ]]; then
    echo "  ✓ ./view is executable"
    PASS=$((PASS + 1))
else
    echo "  ✗ ./view is executable"
    FAIL=$((FAIL + 1))
fi

OUT=$("$PROJECT_DIR/view" --help 2>&1)
RC=$?
assert_exit 0 "$RC" "./view --help exits 0"
assert_contains "table" "$OUT" "./view help includes terminal table mode"
assert_contains "serve" "$OUT" "./view help includes web server mode"

summary
