#!/usr/bin/env bash
# run-id-lib.sh — canonical run-id construction (docs/RUN-MANAGEMENT.md).
#
# Convention:
#   <model-slug>-<suite-slug>[-<adapter-slug>]-<effort>-c<concurrency>-<YYYYMMDD>T<HHMM>Z
#   e.g. qwen38-fp8block-bcb-pareto60-high-c8-20260818T0415Z
#
# Rules:
#   * Effort is omitted when unset (no --thinking).
#   * Adapter slug is omitted for the default pi_vanilla, or when the cell
#     spans multiple adapters (a per-cell id cannot name one).
#   * Unknown model/suite ids fall back to a derived slug (provider prefix
#     stripped, lowercased, non-alphanumerics -> '-'); add a canonical entry
#     in model_slug()/suite_slug() for frequently used ids.
#   * Multi-model invocations return an empty string; the caller falls back
#     to a unique timestamp+pid id rather than naming a single model.
#
# Keep the slug catalogs in sync with docs/RUN-MANAGEMENT.md (source of
# truth for naming).

# slugify — derivation fallback for ids without a canonical slug.
slugify() {
    local s="$1"
    s="${s#*/}"                      # drop provider prefix (first path segment)
    s="$(printf '%s' "$s" | tr '[:upper:]' '[:lower:]')"
    s="$(printf '%s' "$s" | sed -E 's/[^a-z0-9]+/-/g' | sed -E 's/^-+|-+$//g')"
    printf '%s' "$s"
}

# model_slug <model_id> — canonical short slug for known models.
model_slug() {
    case "$1" in
        local/qwen3.8-27b)                 printf 'qwen38' ;;
        local/qwen3.8-27b-fp8-block)       printf 'qwen38-fp8block' ;;
        local/ornith-35b-fp8-block)        printf 'ornith35' ;;
        shisa/ornith-35b-fp8-block)        printf 'ornith35' ;;
        local/deepseek-v4-flash-0731)      printf 'ds4' ;;
        codex/gpt-5.3-codex-spark)         printf 'gpt53spark' ;;
        codex/gpt-5.5)                     printf 'gpt55' ;;
        codex/gpt-5.6-luna)                printf 'gpt56-luna' ;;
        codex/gpt-5.6-terra)               printf 'gpt56-terra' ;;
        codex/gpt-5.6-sol)                 printf 'gpt56-sol' ;;
        zai/glm-5.2)                       printf 'glm52' ;;
        zai/glm-5.3)                       printf 'glm53' ;;
        minimax/MiniMax-M3)                printf 'minimax-m3' ;;
        minimax/MiniMax-M2.7)              printf 'minimax-m2' ;;
        nvidia/nemotron-3-ultra-550b-a55b) printf 'nemotron' ;;
        aiand/qwen/qwen3.6-27b)            printf 'qwen36' ;;
        local-vllm/thinkingcap-qwen36-27b-fp8) printf 'thinkingcap-qwen36' ;;
        bonsai/Ternary-Bonsai-27B-Q2_0.gguf) printf 'bonsai' ;;
        *) slugify "$1" ;;
    esac
}

# suite_slug <suite_id> — canonical short slug for known suites.
suite_slug() {
    case "$1" in
        aider_polyglot)                          printf 'aider-polyglot' ;;
        terminal_bench)                          printf 'terminal' ;;
        terminal_bench_core_pilot8)              printf 'terminal-pilot8' ;;
        terminal_bench_core_pareto20)            printf 'terminal-pareto20' ;;
        swe_atlas_pilot12)                       printf 'swe-atlas-pilot12' ;;
        bigcodebench_hard_instruct)              printf 'bcb-instruct' ;;
        bigcodebench_hard_instruct_hermetic143)  printf 'bcb-instruct-hermetic143' ;;
        bigcodebench_hard_agentic)               printf 'bcb-agentic' ;;
        bigcodebench_hard_agentic_hermetic143)   printf 'bcb-agentic-hermetic143' ;;
        bigcodebench_hard_agentic_pareto60)      printf 'bcb-pareto60' ;;
        swe_polybench_verified)                  printf 'polybench' ;;
        swe_polybench_verified_balanced64)       printf 'polybench-balanced64' ;;
        multi_swe_bench_flash_hermetic25)        printf 'multiswe-hermetic25' ;;
        featurebench_lite_pilot6)                printf 'featurebench-pilot6' ;;
        featurebench_lite_pareto12)              printf 'featurebench-pareto12' ;;
        swe_explore_verified12)                  printf 'swe-explore-verified12' ;;
        *) slugify "$1" ;;
    esac
}

# make_run_id <model> <suite> <thinking> <k> <adapter...>
# Prints the conventional run-id, or an empty string when the caller passed
# multiple models (the caller must fall back to a unique timestamp id).
make_run_id() {
    local model="$1" suite="$2" thinking="$3" k="$4"
    shift 4
    local adapters=("$@")
    local n="${#adapters[@]}"
    local effort="" adapter=""
    if [[ -n "$thinking" ]]; then
        effort="-$thinking"
    fi
    if [[ "$n" -eq 1 && "${adapters[0]:-}" != "pi_vanilla" ]]; then
        adapter="-${adapters[0]}"
    fi
    printf '%s-%s%s%s-c%s-%s' \
        "$(model_slug "$model")" \
        "$(suite_slug "$suite")" \
        "$adapter" \
        "$effort" \
        "$k" \
        "$(date -u +%Y%m%dT%H%MZ)"
}
