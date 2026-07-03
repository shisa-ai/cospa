#!/usr/bin/env bash
# Run all shell-based script tests under tests/scripts/.
#
# These cover scripts that can't easily be exercised from pytest
# (check-models.sh, run-matrix.sh).

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"

FAIL=0
for t in "$SCRIPT_DIR"/test_*.sh; do
    [[ -f "$t" ]] || continue
    echo ""
    bash "$t" || FAIL=1
done

exit $FAIL
