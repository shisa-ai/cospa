#!/usr/bin/env bash
# check-models.sh — Ping each model in models.yaml/models.json and report
# alive/dead + latency. Does NOT modify anything.
#
# Usage:
#   bash scripts/check-models.sh
#
# Reads from configs/models.yaml first, falls back to ~/.pi/agent/models.json.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# ── Read model IDs ─────────────────────────────────────────────────────────
MODELS_FILE="$PROJECT_DIR/configs/models.yaml"
if [[ ! -f "$MODELS_FILE" ]]; then
    MODELS_FILE="$HOME/.pi/agent/models.json"
fi

if [[ ! -f "$MODELS_FILE" ]]; then
    echo "✗ No models config found at:"
    echo "  - $PROJECT_DIR/configs/models.yaml"
    echo "  - $HOME/.pi/agent/models.json"
    exit 1
fi

echo "── Reading models from $MODELS_FILE ──"
echo ""

# Parse model IDs from YAML or JSON
if [[ "$MODELS_FILE" == *.yaml ]]; then
    # YAML: - id: provider/model-id
    mapfile -t MAPFILE < <(grep '^\s*- id:' "$MODELS_FILE" | sed 's/.*- id:\s*//')
else
    # JSON: array of {id: "provider/model-id"}
    mapfile -t MAPFILE < <(python3 -c "
import json, sys
with open('$MODELS_FILE') as f:
    data = json.load(f)
if isinstance(data, dict):
    for k, v in data.items():
        if isinstance(v, dict) and 'id' in v:
            print(v['id'])
        elif isinstance(v, str):
            print(v)
elif isinstance(data, list):
    for item in data:
        if isinstance(item, dict) and 'id' in item:
            print(item['id'])
        elif isinstance(item, str):
            print(item)
")
fi

# ── Ping each model ────────────────────────────────────────────────────────
echo "── Pinging models (1-token completion) ──"
echo ""

ALIVE=0
DEAD=0
SKIPPED=0
TIMEOUT=10  # seconds per model

# Parse --fail-on-dead flag
FAIL_ON_DEAD=false
for arg in "$@"; do
    if [[ "$arg" == "--fail-on-dead" ]]; then
        FAIL_ON_DEAD=true
    fi
done

for MODEL_ID in "${MAPFILE[@]}"; do
    # Extract provider and model name
    PROVIDER="${MODEL_ID%%/*}"
    MODEL_NAME="${MODEL_ID#*/}"

    # Try to find the provider config in models.json
    PROVIDER_BASE_URL=""
    PROVIDER_KEY=""
    PING_MODEL_NAME="$MODEL_NAME"
    if [[ -f "$HOME/.pi/agent/models.json" ]]; then
        # Extract base URL, API key, and the provider's actual model name.
        # The pi models.json uses camelCase keys (`baseUrl`, `apiKey`);
        # tolerate snake_case and optional env-var indirection too.
        PROVIDER_CFG=$(PROVIDER="$PROVIDER" MODEL_ID="$MODEL_ID" MODEL_NAME="$MODEL_NAME" python3 -c '
import json
import os
from pathlib import Path

models_json = Path.home() / ".pi" / "agent" / "models.json"
provider = os.environ["PROVIDER"]
model_id = os.environ["MODEL_ID"]
model_name = os.environ["MODEL_NAME"]

base_url = ""
api_key = ""
resolved_model = model_name

try:
    with models_json.open() as f:
        data = json.load(f)
    providers = data.get("providers", data) if isinstance(data, dict) else data
    cfg = providers.get(provider) if isinstance(providers, dict) else None
    if isinstance(cfg, dict):
        base_url = cfg.get("baseUrl") or cfg.get("base_url") or ""
        api_key = cfg.get("apiKey") or cfg.get("api_key") or ""
        env_name = (
            cfg.get("apiKeyEnv")
            or cfg.get("api_key_env")
            or cfg.get("apiKeyEnvVar")
            or cfg.get("api_key_env_var")
        )
        if env_name and os.environ.get(env_name):
            api_key = os.environ[env_name]

        provider_models = []
        for item in cfg.get("models", []):
            if isinstance(item, dict):
                value = item.get("id") or item.get("name")
            else:
                value = item
            if isinstance(value, str):
                provider_models.append(value)
        if model_id in provider_models:
            resolved_model = model_id
        elif model_name in provider_models:
            resolved_model = model_name
except Exception:
    pass

print(base_url)
print(api_key)
print(resolved_model)
' 2>/dev/null)
        if [[ -n "$PROVIDER_CFG" ]]; then
            PROVIDER_BASE_URL="$(sed -n '1p' <<<"$PROVIDER_CFG")"
            PROVIDER_KEY="$(sed -n '2p' <<<"$PROVIDER_CFG")"
            PING_MODEL_NAME="$(sed -n '3p' <<<"$PROVIDER_CFG")"
        fi
    fi

    # Default to OpenAI-compatible endpoint
    if [[ -z "$PROVIDER_BASE_URL" ]]; then
        # Try common local endpoints
        for url in "http://localhost:8000/v1" "http://localhost:8080/v1"; do
            MODELS_HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" \
                --max-time 2 "$url/models" 2>/dev/null || echo "000")
            if [[ "$MODELS_HTTP_CODE" == "200" ]]; then
                PROVIDER_BASE_URL="$url"
                break
            fi
        done
    fi

    if [[ -z "$PROVIDER_BASE_URL" ]]; then
        echo -e "  ${YELLOW}SKIP${NC} $MODEL_ID (no provider endpoint found)"
        # NOTE: `((SKIPPED++))` returns status 1 when the expression
        # evaluates to 0 (i.e. the first increment), which under `set -e`
        # would terminate the script. Use arithmetic assignment instead.
        SKIPPED=$((SKIPPED + 1))
        continue
    fi

    # Ping the model
    START=$(date +%s%N)
    CURL_HEADERS=("-H" "Content-Type: application/json")
    if [[ -n "$PROVIDER_KEY" ]]; then
        CURL_HEADERS+=("-H" "Authorization: Bearer $PROVIDER_KEY")
    fi

    HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" \
        --max-time "$TIMEOUT" \
        -X POST "$PROVIDER_BASE_URL/chat/completions" \
        "${CURL_HEADERS[@]}" \
        -d "{
            \"model\": \"$PING_MODEL_NAME\",
            \"messages\": [{\"role\": \"user\", \"content\": \"hi\"}],
            \"max_tokens\": 1
        }" 2>/dev/null || echo "000")
    END=$(date +%s%N)

    ELAPSED_MS=$(( (END - START) / 1000000 ))

    if [[ "$HTTP_CODE" == "200" ]]; then
        echo -e "  ${GREEN}✓ ALIVE${NC} $MODEL_ID — ${ELAPSED_MS}ms (HTTP $HTTP_CODE)"
        ALIVE=$((ALIVE + 1))
    else
        echo -e "  ${RED}✗ DEAD${NC}  $MODEL_ID — ${ELAPSED_MS}ms (HTTP $HTTP_CODE)"
        DEAD=$((DEAD + 1))
    fi
done

echo ""
echo "── Summary ──"
echo "  Alive:   $ALIVE"
echo "  Dead:    $DEAD"
echo "  Skipped: $SKIPPED"
echo "  Total:   $((ALIVE + DEAD + SKIPPED))"
echo ""

if [[ $DEAD -gt 0 ]]; then
    echo -e "${YELLOW}⚠ Some models are unreachable. Check provider endpoints.${NC}"
fi

# Fail closed when no model is reachable. This covers two cases that previously
# looked clean:
#   - every model DEAD (provider returned an error)
#   - every model SKIPPED (no provider endpoint could be resolved at all)
# In both situations the matrix cannot run, so we exit nonzero regardless of
# the --fail-on-dead flag unless the user explicitly opted out.
if [[ $ALIVE -eq 0 ]]; then
    echo -e "${RED}✗ FAIL: No models are alive (alive=0, dead=$DEAD, skipped=$SKIPPED).${NC}"
    if [[ "$FAIL_ON_DEAD" == "true" || "$SKIPPED" -eq 0 ]]; then
        exit 1
    fi
    # Even with all-skipped and no --fail-on-dead, an all-skipped matrix is
    # almost certainly a configuration error; surface it as a failure.
    if [[ "$SKIPPED" -gt 0 ]]; then
        exit 1
    fi
fi

exit 0
