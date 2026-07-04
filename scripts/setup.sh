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

# ── 2. Verify/install little-coder ───────────────────────────────────────
echo ""
echo "── Checking little-coder ──"
if command -v little-coder &>/dev/null; then
    LITTLE_CODER_VERSION=$(little-coder --version 2>/dev/null || echo "unknown")
    log_ok "little-coder found: $LITTLE_CODER_VERSION"
else
    log_warn "little-coder not found. Installing via npm..."
    if command -v npm &>/dev/null; then
        npm install -g little-coder
        if command -v little-coder &>/dev/null; then
            LITTLE_CODER_VERSION=$(little-coder --version 2>/dev/null || echo "unknown")
            log_ok "little-coder installed: $LITTLE_CODER_VERSION"
        else
            log_err "npm completed, but little-coder is still not in PATH."
            exit 1
        fi
    else
        log_err "npm not found. Install Node/npm first, then: npm install -g little-coder"
        exit 1
    fi
fi

if ! little-coder --list-models &>/dev/null; then
    log_warn "little-coder is installed, but --list-models failed. Check ~/.pi/agent/models.json."
fi

# ── 3. Verify coding-eval mamba env ──────────────────────────────────────
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

# ── 4. Install Harbor ────────────────────────────────────────────────────
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

# ── 5. Clone Terminal-Bench ──────────────────────────────────────────────
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

# ── 6. Clone Aider Polyglot dataset ──────────────────────────────────────
echo ""
echo "── Checking Aider Polyglot dataset ──"
POLY_DIR="$VENDOR_DIR/polyglot-benchmark"
if [[ -d "$POLY_DIR/.git" ]]; then
    log_ok "Aider Polyglot dataset already cloned at $POLY_DIR"
    cd "$POLY_DIR"
    git pull --ff-only || log_warn "Could not pull latest"
    cd "$PROJECT_DIR"
else
    log_warn "Cloning Aider Polyglot dataset (polyglot-benchmark)..."
    mkdir -p "$VENDOR_DIR"
    # Real benchmark: Exercism-sourced exercises across python/go/rust/cpp/
    # java/javascript. Do NOT silently fall back to a placeholder — a missing
    # dataset is a setup failure, not a quiet success.
    if ! git clone https://github.com/Aider-AI/polyglot-benchmark.git "$POLY_DIR"; then
        log_err "Failed to clone polyglot-benchmark. The dataset is required."
        log_err "  If you are offline, vendor it manually into: $POLY_DIR"
        rm -rf "$POLY_DIR"
        exit 1
    fi
    log_ok "Aider Polyglot dataset at $POLY_DIR"
fi

# ── Done ──────────────────────────────────────────────────────────────────
echo ""
echo "── Setup complete ──"
echo "  Pi:     $PI_VERSION"
echo "  Little: $LITTLE_CODER_VERSION"
echo "  Python: $PY_VER (in coding-eval env)"
echo "  Harbor: $(harbor --version 2>/dev/null || echo 'installed')"
echo "  TB:     $TB_DIR"
echo "  Polyglot: $POLY_DIR"
echo ""
echo "Next: bash scripts/check-models.sh"
