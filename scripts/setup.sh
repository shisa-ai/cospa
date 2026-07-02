#!/usr/bin/env bash
# setup.sh — Verify and install coding-eval dependencies.
#
# Does NOT touch models or providers. Model setup is a separate concern.
#
# Usage:
#   bash scripts/setup.sh
#
# Exits non-zero if any check fails.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
VENDOR_DIR="$PROJECT_DIR/vendor"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_ok() { echo -e "${GREEN}✓${NC} $1"; }
log_warn() { echo -e "${YELLOW}⚠${NC} $1"; }
log_err() { echo -e "${RED}✗${NC} $1"; }

# ── 1. Verify pi ──────────────────────────────────────────────────────────
echo "── Checking pi ──"
if command -v pi &>/dev/null; then
    PI_VERSION=$(pi --version 2>/dev/null || echo "unknown")
    log_ok "pi found: $PI_VERSION"
else
    log_err "pi not found in PATH. Install with: npm install -g --ignore-scripts @earendil-works/pi-coding-agent"
    exit 1
fi

# ── 2. Verify coding-eval mamba env ──────────────────────────────────────
echo ""
echo "── Checking coding-eval mamba env ──"
if command -v mamba &>/dev/null; then
    if mamba run -n coding-eval python --version 2>/dev/null; then
        PY_VER=$(mamba run -n coding-eval python --version 2>/dev/null | grep -oP '\d+\.\d+')
        if [[ "$PY_VER" == "3.12" ]]; then
            log_ok "coding-eval env found with python=$PY_VER"
        else
            log_warn "coding-eval env found with python=$PY_VER (expected 3.12)"
        fi
    else
        log_err "coding-eval mamba env not found."
        echo "  Create it with: mamba create -n coding-eval python=3.12"
        exit 1
    fi
elif command -v conda &>/dev/null; then
    if conda run -n coding-eval python --version 2>/dev/null; then
        PY_VER=$(conda run -n coding-eval python --version 2>/dev/null | grep -oP '\d+\.\d+')
        if [[ "$PY_VER" == "3.12" ]]; then
            log_ok "coding-eval conda env found with python=$PY_VER"
        else
            log_warn "coding-eval env found with python=$PY_VER (expected 3.12)"
        fi
    else
        log_err "coding-eval conda env not found."
        echo "  Create it with: conda create -n coding-eval python=3.12"
        exit 1
    fi
else
    log_err "Neither mamba nor conda found in PATH."
    exit 1
fi

# ── 3. Install Harbor ────────────────────────────────────────────────────
echo ""
echo "── Checking Harbor ──"
if command -v harbor &>/dev/null; then
    log_ok "harbor found: $(harbor --version 2>/dev/null || echo 'unknown')"
else
    log_warn "harbor not found. Installing via uv..."
    if command -v uv &>/dev/null; then
        uv tool install harbor
        log_ok "harbor installed"
    else
        log_err "uv not found. Install uv first, then: uv tool install harbor"
        exit 1
    fi
fi

# ── 4. Clone Terminal-Bench ──────────────────────────────────────────────
echo ""
echo "── Checking Terminal-Bench ──"
TB_DIR="$VENDOR_DIR/terminal-bench"
if [[ -d "$TB_DIR/.git" ]]; then
    log_ok "Terminal-Bench already cloned at $TB_DIR"
    # Pull latest
    cd "$TB_DIR"
    git pull --ff-only || log_warn "Could not pull latest (may be detached HEAD)"
    cd "$PROJECT_DIR"
else
    log_warn "Cloning Terminal-Bench (latest from harbor-framework)..."
    mkdir -p "$VENDOR_DIR"
    git clone https://github.com/harbor-framework/terminal-bench.git "$TB_DIR"
    log_ok "Terminal-Bench cloned to $TB_DIR"
fi

# ── 5. Clone Aider Polyglot dataset ──────────────────────────────────────
echo ""
echo "── Checking Aider Polyglot dataset ──"
POLY_DIR="$VENDOR_DIR/aider-polyglot"
if [[ -d "$POLY_DIR/.git" ]]; then
    log_ok "Aider Polyglot dataset already cloned at $POLY_DIR"
    cd "$POLY_DIR"
    git pull --ff-only || log_warn "Could not pull latest"
    cd "$PROJECT_DIR"
else
    log_warn "Cloning Aider Polyglot dataset..."
    mkdir -p "$VENDOR_DIR"
    # Use the public Exercism dataset — adjust URL if you have a private fork
    git clone https://github.com/Aider-AI/aider-polyglot.git "$POLY_DIR" 2>/dev/null || {
        log_warn "aider-polyglot repo not public; creating placeholder"
        mkdir -p "$POLY_DIR"
        echo "# Aider Polyglot dataset" > "$POLY_DIR/README.md"
    }
    log_ok "Aider Polyglot dataset at $POLY_DIR"
fi

# ── Done ──────────────────────────────────────────────────────────────────
echo ""
echo "── Setup complete ──"
echo "  Pi:     $PI_VERSION"
echo "  Python: $PY_VER (in coding-eval env)"
echo "  Harbor: $(harbor --version 2>/dev/null || echo 'installed')"
echo "  TB:     $TB_DIR"
echo "  Polyglot: $POLY_DIR"
echo ""
echo "Next: bash scripts/check-models.sh"
