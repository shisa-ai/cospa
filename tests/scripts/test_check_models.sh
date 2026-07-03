#!/usr/bin/env bash
# Tests for scripts/check-models.sh.
#
# Reproduces ORNITH-CODER-REVIEW.md follow-up audit item E:
#   1. ((SKIPPED++)) returns 1 when SKIPPED==0, exiting under `set -e`.
#   2. Script fails closed only when ALIVE==0 && DEAD>0, so an all-skipped
#      matrix looks clean.
#
# We build a fake project layout with a models.yaml whose providers cannot
# resolve (so every model is SKIPPED) and assert the script completes and
# exits nonzero.

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
source "$SCRIPT_DIR/lib.sh"

echo "── test_check_models.sh ──"

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

# Build a fake project: <tmp>/proj/{scripts/check-models.sh, configs/models.yaml}
PROJ="$TMP/proj"
mkdir -p "$PROJ/scripts" "$PROJ/configs"
cp "$PROJECT_DIR/scripts/check-models.sh" "$PROJ/scripts/check-models.sh"
cat > "$PROJ/configs/models.yaml" <<'EOF'
models:
  - id: fake/provider-one
  - id: fake/provider-two
  - id: fake/provider-three
EOF

# Use an empty HOME so the real ~/.pi/agent/models.json isn't read.
mkdir -p "$TMP/empty-home"

OUT=$(HOME="$TMP/empty-home" bash "$PROJ/scripts/check-models.sh" 2>&1)
RC=$?

# Bug #1: with `set -e`, `((SKIPPED++))` exits on the first SKIP because the
# arithmetic expression evaluates to 0. The script must instead count all 3.
assert_contains "provider-one" "$OUT" "first model pinged"
assert_contains "provider-two" "$OUT" "second model pinged"
assert_contains "provider-three" "$OUT" "third model pinged"
assert_contains "Skipped: 3" "$OUT" "all 3 models counted as skipped"
# Bug #2: must fail closed when no model is alive (all skipped == not runnable)
assert_exit 1 "$RC" "exit nonzero when no models are alive"

summary
