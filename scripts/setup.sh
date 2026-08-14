#!/usr/bin/env bash
# setup.sh — Verify and install cospa dependencies.
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

# ── 3. Verify cospa mamba env ────────────────────────────────────────────
echo ""
echo "── Checking cospa mamba env ──"
if command -v mamba &>/dev/null; then
    if mamba run -n cospa python --version 2>/dev/null; then
        PY_VER=$(mamba run -n cospa python --version 2>/dev/null | grep -oP '\d+\.\d+')
        if [[ "$PY_VER" == "3.12" ]]; then
            log_ok "cospa env found with python=$PY_VER"
        else
            log_warn "cospa env found with python=$PY_VER (expected 3.12)"
        fi
    else
        log_err "cospa mamba env not found."
        echo "  Create it with: mamba create -n cospa python=3.12"
        exit 1
    fi
elif command -v conda &>/dev/null; then
    if conda run -n cospa python --version 2>/dev/null; then
        PY_VER=$(conda run -n cospa python --version 2>/dev/null | grep -oP '\d+\.\d+')
        if [[ "$PY_VER" == "3.12" ]]; then
            log_ok "cospa conda env found with python=$PY_VER"
        else
            log_warn "cospa env found with python=$PY_VER (expected 3.12)"
        fi
    else
        log_err "cospa conda env not found."
        echo "  Create it with: conda create -n cospa python=3.12"
        exit 1
    fi
else
    log_err "Neither mamba nor conda found in PATH."
    exit 1
fi

# ── 4. Install pinned Harbor ─────────────────────────────────────────────
echo ""
echo "── Checking Harbor ──"
HARBOR_VERSION="0.16.1"
HARBOR_ACTUAL_VERSION=""
if command -v harbor &>/dev/null; then
    HARBOR_ACTUAL_VERSION=$(harbor --version 2>/dev/null || true)
fi
if [[ "$HARBOR_ACTUAL_VERSION" != "$HARBOR_VERSION" ]]; then
    if [[ -n "$HARBOR_ACTUAL_VERSION" ]]; then
        log_warn "harbor $HARBOR_ACTUAL_VERSION is incompatible; installing pinned $HARBOR_VERSION..."
    else
        log_warn "harbor not found. Installing pinned $HARBOR_VERSION via uv..."
    fi
    if command -v uv &>/dev/null; then
        env -u UV_EXCLUDE_NEWER uv tool install --force "harbor==$HARBOR_VERSION"
    else
        log_err "uv not found. Install uv first, then: uv tool install harbor==$HARBOR_VERSION"
        exit 1
    fi
    HARBOR_ACTUAL_VERSION=$(harbor --version 2>/dev/null || true)
fi
if [[ "$HARBOR_ACTUAL_VERSION" != "$HARBOR_VERSION" ]]; then
    log_err "Harbor version mismatch: expected $HARBOR_VERSION, got ${HARBOR_ACTUAL_VERSION:-missing}"
    exit 1
fi
log_ok "harbor found: $HARBOR_ACTUAL_VERSION"

# ── 5. Clone Terminal-Bench Core 0.1.1 ──────────────────────────────────
echo ""
echo "── Checking Terminal-Bench Core 0.1.1 ──"
TB_DIR="$VENDOR_DIR/terminal-bench"
TB_REPO="https://github.com/harbor-framework/terminal-bench-1.git"
TB_COMMIT="91e10457b5410f16c44364da1a34cb6de8c488a5"
if [[ -d "$TB_DIR/.git" ]]; then
    log_ok "Terminal-Bench already cloned at $TB_DIR"
else
    log_warn "Cloning Terminal-Bench for the pinned Core 0.1.1 dataset..."
    mkdir -p "$VENDOR_DIR"
    git clone "$TB_REPO" "$TB_DIR"
    log_ok "Terminal-Bench cloned to $TB_DIR"
fi

cd "$TB_DIR"
git fetch origin "$TB_COMMIT"
git checkout --detach "$TB_COMMIT"
TB_ACTUAL_COMMIT=$(git rev-parse HEAD)
cd "$PROJECT_DIR"
if [[ "$TB_ACTUAL_COMMIT" != "$TB_COMMIT" ]]; then
    log_err "Terminal-Bench checkout mismatch: expected $TB_COMMIT, got $TB_ACTUAL_COMMIT"
    exit 1
fi
log_ok "Terminal-Bench pinned to Core 0.1.1 ($TB_COMMIT)"

# ── 6. Clone SWE Atlas pilot dataset ─────────────────────────────────────
echo ""
echo "── Checking SWE Atlas pilot ──"
SWE_ATLAS_DIR="$VENDOR_DIR/swe-atlas"
SWE_ATLAS_REPO="https://github.com/scaleapi/SWE-Atlas.git"
SWE_ATLAS_COMMIT="2cac47d64a9123d915b8f6f6f53763391920f574"
if [[ -d "$SWE_ATLAS_DIR/.git" ]]; then
    log_ok "SWE Atlas already cloned at $SWE_ATLAS_DIR"
else
    log_warn "Cloning SWE Atlas for the pinned 12-task pilot..."
    mkdir -p "$VENDOR_DIR"
    git clone "$SWE_ATLAS_REPO" "$SWE_ATLAS_DIR"
    log_ok "SWE Atlas cloned to $SWE_ATLAS_DIR"
fi

cd "$SWE_ATLAS_DIR"
git fetch origin "$SWE_ATLAS_COMMIT"
git checkout --detach "$SWE_ATLAS_COMMIT"
SWE_ATLAS_ACTUAL_COMMIT=$(git rev-parse HEAD)
cd "$PROJECT_DIR"
if [[ "$SWE_ATLAS_ACTUAL_COMMIT" != "$SWE_ATLAS_COMMIT" ]]; then
    log_err "SWE Atlas checkout mismatch: expected $SWE_ATLAS_COMMIT, got $SWE_ATLAS_ACTUAL_COMMIT"
    exit 1
fi
log_ok "SWE Atlas pinned for pilot12 ($SWE_ATLAS_COMMIT)"

# ── 7. Clone Aider Polyglot dataset ──────────────────────────────────────
echo ""
echo "── Checking Aider Polyglot dataset ──"
POLY_DIR="$VENDOR_DIR/polyglot-benchmark"
POLY_REPO="https://github.com/Aider-AI/polyglot-benchmark.git"
POLY_COMMIT="7e0611e77b54e2dea774cdc0aa00cf9f7ed6144f"
if [[ -d "$POLY_DIR/.git" ]]; then
    log_ok "Aider Polyglot dataset already cloned at $POLY_DIR"
else
    log_warn "Cloning the pinned Aider Polyglot source corpus..."
    mkdir -p "$VENDOR_DIR"
    # Real benchmark: Exercism-sourced exercises across python/go/rust/cpp/
    # java/javascript. Do NOT silently fall back to a placeholder — a missing
    # dataset is a setup failure, not a quiet success.
    if ! git clone "$POLY_REPO" "$POLY_DIR"; then
        log_err "Failed to clone polyglot-benchmark. The dataset is required."
        log_err "  If you are offline, vendor it manually into: $POLY_DIR"
        rm -rf "$POLY_DIR"
        exit 1
    fi
    log_ok "Aider Polyglot dataset at $POLY_DIR"
fi

cd "$POLY_DIR"
git fetch origin "$POLY_COMMIT"
git checkout --detach "$POLY_COMMIT"
POLY_ACTUAL_COMMIT=$(git rev-parse HEAD)
cd "$PROJECT_DIR"
if [[ "$POLY_ACTUAL_COMMIT" != "$POLY_COMMIT" ]]; then
    log_err "Aider Polyglot checkout mismatch: expected $POLY_COMMIT, got $POLY_ACTUAL_COMMIT"
    exit 1
fi
log_ok "Aider Polyglot pinned to source commit ($POLY_COMMIT)"

# ── Done ──────────────────────────────────────────────────────────────────
echo ""
echo "── Setup complete ──"
echo "  Pi:     $PI_VERSION"
echo "  Little: $LITTLE_CODER_VERSION"
echo "  Python: $PY_VER (in cospa env)"
echo "  Harbor: $(harbor --version 2>/dev/null || echo 'installed')"
echo "  TB:     $TB_DIR"
echo "  SWE Atlas: $SWE_ATLAS_DIR"
echo "  Polyglot: $POLY_DIR"
echo ""
echo "Next: bash scripts/check-models.sh"
