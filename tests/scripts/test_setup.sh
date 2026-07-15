#!/usr/bin/env bash
# Tests for scripts/setup.sh dependency checks.

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
source "$SCRIPT_DIR/lib.sh"

echo "── test_setup.sh ──"

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

PROJ="$TMP/proj"
BIN="$TMP/bin"
mkdir -p "$PROJ/scripts" "$PROJ/vendor/terminal-bench/.git" \
    "$PROJ/vendor/swe-atlas/.git" "$PROJ/vendor/polyglot-benchmark/.git" "$BIN"
cp "$PROJECT_DIR/scripts/setup.sh" "$PROJ/scripts/setup.sh"

cat > "$BIN/pi" <<'EOF'
#!/usr/bin/env bash
if [[ "${1:-}" == "--version" ]]; then
    echo "0.80.3"
fi
EOF

cat > "$BIN/mamba" <<'EOF'
#!/usr/bin/env bash
if [[ "$*" == "run -n coding-eval python --version" ]]; then
    echo "Python 3.12.13"
    exit 0
fi
echo "unexpected mamba args: $*" >&2
exit 1
EOF

cat > "$BIN/harbor" <<'EOF'
#!/usr/bin/env bash
if [[ "${1:-}" == "--version" ]]; then
    echo "0.16.1"
fi
EOF

cat > "$BIN/git" <<'EOF'
#!/usr/bin/env bash
echo "$PWD|$*" >> "$GIT_LOG"
if [[ "$*" == "rev-parse HEAD" ]]; then
    if [[ "$PWD" == */swe-atlas ]]; then
        echo "2cac47d64a9123d915b8f6f6f53763391920f574"
    else
        echo "91e10457b5410f16c44364da1a34cb6de8c488a5"
    fi
fi
exit 0
EOF

cat > "$BIN/npm" <<'EOF'
#!/usr/bin/env bash
echo "$*" >> "$NPM_LOG"
if [[ "$*" == "install -g little-coder" ]]; then
    cat > "$(dirname "$0")/little-coder" <<'LC'
#!/usr/bin/env bash
if [[ "${1:-}" == "--version" ]]; then
    echo "0.79.10"
elif [[ "${1:-}" == "--list-models" ]]; then
    echo "provider model"
fi
LC
    chmod +x "$(dirname "$0")/little-coder"
fi
EOF

chmod +x "$BIN/pi" "$BIN/mamba" "$BIN/harbor" "$BIN/git" "$BIN/npm"

NPM_LOG="$TMP/npm.log"
GIT_LOG="$TMP/git.log"
export NPM_LOG GIT_LOG
TEST_PATH="$BIN:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
OUT=$(PATH="$TEST_PATH" bash "$PROJ/scripts/setup.sh" 2>&1)
RC=$?

assert_exit 0 "$RC" "setup exits 0 when npm can install missing little-coder"
assert_contains "install -g little-coder" "$(cat "$NPM_LOG" 2>/dev/null || true)" \
    "setup installs little-coder when missing"
assert_contains "little-coder installed" "$OUT" "setup reports little-coder installation"
assert_contains "fetch origin 91e10457b5410f16c44364da1a34cb6de8c488a5" \
    "$(cat "$GIT_LOG")" "setup fetches the immutable Terminal-Bench Core 0.1.1 commit"
assert_contains "checkout --detach 91e10457b5410f16c44364da1a34cb6de8c488a5" \
    "$(cat "$GIT_LOG")" "setup checks out Terminal-Bench Core 0.1.1 detached"
assert_not_contains "$PROJ/vendor/terminal-bench|pull --ff-only" "$(cat "$GIT_LOG")" \
    "setup does not advance Terminal-Bench to mutable head"
assert_contains "fetch origin 2cac47d64a9123d915b8f6f6f53763391920f574" \
    "$(cat "$GIT_LOG")" "setup fetches the immutable SWE Atlas pilot commit"
assert_contains "checkout --detach 2cac47d64a9123d915b8f6f6f53763391920f574" \
    "$(cat "$GIT_LOG")" "setup checks out SWE Atlas detached"
assert_not_contains "$PROJ/vendor/swe-atlas|pull --ff-only" "$(cat "$GIT_LOG")" \
    "setup does not advance SWE Atlas to mutable head"

summary
