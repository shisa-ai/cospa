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

# Authenticated provider pings must include the provider apiKey from
# ~/.pi/agent/models.json. Without it, OpenAI-compatible endpoints return 401
# even when the model is alive.
AUTH_PROJ="$TMP/auth-proj"
mkdir -p "$AUTH_PROJ/scripts" "$AUTH_PROJ/configs"
cp "$PROJECT_DIR/scripts/check-models.sh" "$AUTH_PROJ/scripts/check-models.sh"
cat > "$AUTH_PROJ/configs/models.yaml" <<'EOF'
models:
  - id: fake/model-one
EOF

AUTH_HOME="$TMP/auth-home"
mkdir -p "$AUTH_HOME/.pi/agent"
cat > "$AUTH_HOME/.pi/agent/models.json" <<'EOF'
{
  "providers": {
    "fake": {
      "baseUrl": "http://fake-provider.test/v1",
      "apiKey": "test-key",
      "models": [{"id": "fake/model-one"}]
    }
  }
}
EOF

BIN="$TMP/bin"
mkdir -p "$BIN"
cat > "$BIN/curl" <<'EOF'
#!/usr/bin/env bash
args="$(printf '%s\n' "$@")"
if grep -qF "Authorization: Bearer test-key" <<<"$args" \
    && grep -qF '"model": "fake/model-one"' <<<"$args"; then
    printf '200'
else
    printf '401'
fi
EOF
chmod +x "$BIN/curl"

AUTH_OUT=$(HOME="$AUTH_HOME" PATH="$BIN:$PATH" bash "$AUTH_PROJ/scripts/check-models.sh" 2>&1)
AUTH_RC=$?

assert_exit 0 "$AUTH_RC" "authenticated model ping exits zero"
assert_contains "✓ ALIVE" "$AUTH_OUT" "authenticated model marked alive"
assert_contains "Alive:   1" "$AUTH_OUT" "authenticated model counted alive"
assert_not_contains "test-key" "$AUTH_OUT" "api key is not printed"

summary
