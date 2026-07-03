#!/usr/bin/env bash
# Test harness for shell scripts: run a script with controlled inputs and
# assert on exit code / stdout. Sourced by test_scripts.sh cases.
#
# Usage:
#   assert_exit <expected> <actual>
#   assert_contains <needle> <haystack>

set -u

PASS=0
FAIL=0

assert_exit() {
    local expected="$1" actual="$2" label="$3"
    if [[ "$expected" == "$actual" ]]; then
        echo "  ✓ $label (exit=$actual)"
        PASS=$((PASS + 1))
    else
        echo "  ✗ $label (expected exit=$expected, got $actual)"
        FAIL=$((FAIL + 1))
    fi
}

assert_contains() {
    local needle="$1" haystack="$2" label="$3"
    if grep -qF "$needle" <<<"$haystack"; then
        echo "  ✓ $label"
        PASS=$((PASS + 1))
    else
        echo "  ✗ $label (missing: '$needle')"
        echo "    output: ${haystack:0:200}"
        FAIL=$((FAIL + 1))
    fi
}

assert_not_contains() {
    local needle="$1" haystack="$2" label="$3"
    if grep -qF "$needle" <<<"$haystack"; then
        echo "  ✗ $label (unexpected: '$needle')"
        echo "    output: ${haystack:0:200}"
        FAIL=$((FAIL + 1))
    else
        echo "  ✓ $label"
        PASS=$((PASS + 1))
    fi
}

summary() {
    echo ""
    echo "  PASS: $PASS  FAIL: $FAIL"
    if [[ "$FAIL" -gt 0 ]]; then
        exit 1
    fi
}
