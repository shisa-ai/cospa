# Candidate Models for RTX PRO 6000 Rigs (96 GB / 192 GB / 288 GB)

Research notes (2026-07-15) on open-weight models that fit on 1–3×
RTX PRO 6000 Blackwell (96 GB GDDR7, ~1.79 TB/s each, **PCIe Gen5 — no
NVLink**) and might outperform **Ornith-1.0-35B** on agentic coding
benchmarks. All repo sizes measured from HF API file trees; quant
compositions verified by reading **safetensors headers only** (HTTP range
requests — no weight downloads); architecture numbers from each repo's
`config.json`.

Caveats that apply throughout:

- All scores are **vendor self-reported**; scaffolds differ (OpenHands vs
  Terminus-2 vs Claude Code) and can swing results by points.
- Terminal-Bench versions are inconsistent across cards (2.0 vs 2.1) —
  cross-model TB comparisons are approximate.
- No community 4-bit quant publishes quality deltas. Sanity-eval with
  cospa before trusting any of them at Ornith-beating levels.
- Speed figures below are **bandwidth-model estimates**, not measurements.

## Baseline: Ornith-1.0-35B

[deepreinforce-ai/Ornith-1.0-35B](https://huggingface.co/deepreinforce-ai/Ornith-1.0-35B)
— Qwen3.5-MoE lineage (`qwen3_5_moe_text`), 35B total, 40 layers,
256 experts top-8 (`moe_intermediate` 512 → ~1B routed params active;
total active ~2–3B), **hybrid linear attention: 30 linear + 10 full
layers**, 2 KV heads × 256 on the full layers, 262K context.
BF16 = 70.2 GB → **fits one 96 GB GPU**.

KV cost is almost nil: only 10 full-attention layers cache KV
(≈ 10 KB/token FP8); the 30 linear layers carry O(1) state. This is why
it is "monstrous": near-linear prefill, tiny KV, ~6–7 GB of weight reads
per decoded token.

| Benchmark | Score | Harness |
| --- | --- | --- |
| SWE-bench Verified | 75.6 | OpenHands |
| SWE-bench Pro (public) | 50.4 | OpenHands |
| SWE-bench Multilingual | 69.3 | OpenHands |
| Terminal-Bench 2.1 | 64.2 (62.8 w/ Claude Code scaffold) | Terminus-2 |

## Benchmark comparison (self-reported)

| Model | Arch | SWE-V | SWE-Pro | SWE-ML | Terminal-Bench |
| --- | --- | --- | --- | --- | --- |
| Ornith-1.0-35B | 35B MoE (act ~3B) | 75.6 | 50.4 | 69.3 | **64.2** (2.1) |
| MiMo-V2.5 | 310B-A15B | n/pub (Pro: 78.9) | **56.1** | — | **65.8** (2.0) |
| MiniMax M2.7 | 230B-A10B | 78.0 | 56.2 | **76.5** | 57.0 (2.0) |
| DeepSeek V4 Flash | 284B-A13B | **79.0** | — | — | 56.9 (2.0) |
| Hy3 (see analysis) | 295B-A21B | 78.0 | 57.9 | — | n/pub |

Reading: MiMo-V2.5 is the only one that (roughly) matches/beats Ornith on
Terminal-Bench; M2.7 and V4 Flash beat it on SWE-bench-style tasks but
trail ~7 pts on terminal work. Nothing dominates Ornith outright.

## Architecture / speed-relevant properties

| Property | Ornith-1.0-35B | MiniMax M2.7 | DS V4 Flash | MiMo-V2.5 | Hy3 |
| --- | --- | --- | --- | --- | --- |
| Total / active params | 35B / ~3B | 230B / ~10B | 284B / 13B | 310B / 15B | 295B / 21B |
| Layers | 40 | 62 | 43 | 48 | 80 (+MTP) |
| Attention | **hybrid linear** (30 lin + 10 full), 2 KV × 256 | **all full** GQA, 8 KV × 128 | **MLA latent** (512+64) + DSA top-512 + SWA-128 | **hybrid** SWA-128/global, 4 KV, qk 192 / v 128 | all full GQA, 8 KV × 128 |
| KV @ FP8 per token | ~10 KB (+ linear state) | ~124 KB | ~24 KB | ≤ 60 KB (interleave ratio unpublished) | ~160 KB |
| 128K ctx KV | ~1.3 GB | ~16.2 GB | ~3.2 GB | ≤ 7.7 GB | ~21 GB |
| MTP / draft | none | base has `num_mtp_modules: 3`, **stripped from nvidia NVFP4 repo** | 1 nextn layer, **included** (3.8 GB) | 3-layer MTP (~1.2 GB) included; separate DFlash draft repos | 1 MTP layer (3.8B) |
| Context cap | 262K | 205K | 1M | 1M | 256K |

MTP/draft implications: self-speculative decode typically gives
**1.5–2.5× decode throughput on code** (high acceptance rates). DS V4
Flash and MiMo-V2.5 ship usable MTP/draft weights in the repos below;
**M2.7 loses this** unless the MTP modules are pulled from the BF16 repo
and quantized separately. Ornith has none — its speed comes from raw
active-param efficiency instead.

## Decode speed model (estimates, not measurements)

Batch-1 decode is memory-bandwidth-bound: tok/s ≈ MBU × aggregate BW /
bytes-read-per-token. Bytes/token computed from the *actual stored
dtypes* in each quant repo (headers): all-active tensors (attention,
dense MLP, routers, lm_head row-major read) + `active/total ×` expert
bytes. Assumptions: FP32-stored tensors load as BF16 at runtime; MBU
45–60% for TP2 over PCIe (no NVLink — allreduce per layer hurts;
single-GPU Ornith gets 55–70%).

| Model (repo) | GPUs | Bytes/token | Theor. max | Est. tok/s (MBU band) | w/ MTP/spec (×1.5–2) |
| --- | --- | --- | --- | --- | --- |
| Ornith BF16 | 1 | ~6.5 GB | ~275 | **150–190** | n/a |
| M2.7 NVFP4 | 2 | ~10.7 GB (attn 5.5 BF16 + experts 3.95 + head 1.2) | ~335 | **150–200** | unavailable (MTP stripped) |
| DS V4 Flash native | 2 | ~11.3 GB (attn 5.5 FP8 + shared 1.1 + routed 3.5 + head/dense 1.2) | ~317 | **140–190** | **210–380** |
| MiMo MXFP4 | 2 | ~17.2 GB (attn 7.4 + dense/router 3.5 + experts 5.0 + head 1.3) | ~208 | **95–125** | **140–250** |

Notes:
- MiMo pays for BF16-stored attention (4.5 GB) — a requant with FP8
  attention (like mitomtuna's) drops it to ~14.8 GB/tok (~110–145 tok/s).
- Prefill (compute-bound, long-context): DS V4 Flash fastest (DSA top-512
  ⇒ near-linear), Ornith next (30/40 linear layers), MiMo mid (SWA
  majority), **M2.7 slowest** (62 full-attention layers, O(n²)).
- Ornith on this rig can also run **2 independent replicas** (one per
  GPU) — 2× trial throughput for cospa-style parallel runs, no TP tax.

## VRAM budgets: utilization × GPU count

Usable = N × 96 GB × utilization. **0.95 is the realistic ceiling**:
CUDA-graph capture, NCCL/TP buffers, attention workspace, and allocator
fragmentation need the last ~5%; 0.90 is the safe default, 0.92 usually
fine, ≥ 0.95 often requires shrinking graph capture sizes or
`--enforce-eager`.

| Utilization | 1× (96 GB) | 2× (192 GB) | 3× (288 GB) |
| --- | --- | --- | --- |
| 0.90 | 86.4 | 172.8 | 259.2 |
| 0.92 | 88.3 | 176.6 | 265.0 |
| 0.95 | 91.2 | 182.4 | 273.6 |

### Fit matrix (weights vs usable; leftover = KV + activations)

| Model / repo | Weights | 1×0.90 | 2×0.90 | 2×0.92 | 2×0.95 | 3×0.90 | 3×0.95 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Ornith BF16 | 70.2 | ✅ +16.2 | ✅ (or 2 replicas) | — | — | — | — |
| M2.7 NVFP4 | 139.9 | ✗ | ✅ +32.9 | ✅ +36.7 | ✅ +42.5 | ✅ +119 | ✅ |
| DS V4 Flash native | 159.6 | ✗ | ✅ +13.2 | ✅ +17.0 | ✅ +22.8 | ✅ +99.6 | ✅ |
| MiMo MXFP4 | 176.6 | ✗ | ❌ −3.8 | ⚠️ ±0 | ✅ +5.8 | ✅ +82.6 | ✅ |
| MiMo NVFP4 (mitomtuna) | 183.5 | ✗ | ❌ | ❌ | ❌ −1.1 | ✅ +75.7 | ✅ |
| Hy3 MXFP4 (INCModel2) | 164.2 | ✗ | ✅ +8.6 | ✅ +12.4 | ✅ +18.2 | ✅ +95.0 | ✅ |
| Hy3 NVFP4 (0xSero) | 169.6 | ✗ | ⚠️ +3.2 | ✅ +7.0 | ✅ +12.8 | ✅ +89.6 | ✅ |
| Hy3 NVFP4 (kodelow) | 180.9 | ✗ | ❌ | ❌ | ⚠️ +1.5 | ✅ +78.3 | ✅ +92.7 |
| MiniMax M3 NVFP4 | 250.1 | ✗ | ✗ | ✗ | ✗ | ⚠️ +9.1 | ✅ +23.5 |
| M3 REAP25 | 187.0 | ✗ | ❌ | ❌ | ❌ | ✅ +72.2 | ✅ |

KV context these leftovers buy (FP8 KV, minus ~2–3 GB activations):
M2.7 @2×0.90 → ~30 GB ≈ 240K tokens aggregate (full 205K single-stream);
DS V4 Flash @2×0.90 → ~10 GB ≈ **420K tokens** (MLA is that cheap);
MiMo MXFP4 @2×0.95 → ~3–6 GB ≈ 50–200K depending on the global-layer
share. MiMo on 2 GPUs is single-stream-only and graph-capture-constrained.

### 3-GPU notes

A third GPU (288 GB) unlocks Hy3, MiMo NVFP4, M3-REAP25 comfortably and
M3 NVFP4 marginally — but **TP=3 has divisibility problems**: MiMo/Hy3
have 64 Q-heads (64 % 3 ≠ 0), M2.7's 8 KV heads must replicate, MLA
latent replicates per rank. Options: pipeline-parallel (PP=3), expert
parallel, or repos repacked for TP3 —
[mitomtuna/MiMo-V2.5-0703-NVFP4-TP3](https://huggingface.co/mitomtuna/MiMo-V2.5-0703-NVFP4-TP3)
exists precisely for this. Expect worse scaling than 2-GPU TP either way
(PCIe, odd sharding).

## MiMo-V2.5 (Xiaomi, 310B-A15B)

[XiaomiMiMo/MiMo-V2.5](https://huggingface.co/XiaomiMiMo/MiMo-V2.5) —
sparse MoE, 48 layers (1 dense + 47 MoE), 256 experts top-8, hybrid
SWA/global attention, 1M context, native FP8, multimodal (729M ViT +
261M audio towers). Native repo: **315.7 GB** — needs 4-bit to fit.

Quant repos (headers verified 2026-07-15):

| Repo | Size | Experts | Attention | Other |
| --- | --- | --- | --- | --- |
| [chriswritescode/MiMo-V2.5-DFlash-MXFP4A16](https://huggingface.co/chriswritescode/MiMo-V2.5-DFlash-MXFP4A16) | **176.6 GB** | U8 160.9 GB (MXFP4, E8M0 scales embedded) | BF16 4.5 + FP8 2.9 GB | MTP FP8, vision/audio BF16 |
| [mitomtuna/MiMo-V2.5-0703-NVFP4](https://huggingface.co/mitomtuna/MiMo-V2.5-0703-NVFP4) | 183.5 GB | U8 151.4 + FP8 scales 18.9 GB | FP8 2.9 + BF16 3.8 GB | MTP FP8, vision/audio BF16 |
| [shadowlilac/MiMo-V2.5-NVFP4](https://huggingface.co/shadowlilac/MiMo-V2.5-NVFP4) | 187.2 GB | U8 151.4 + FP8 scales 18.9 GB | all BF16 (9.5 GB) | MTP BF16 |

Size floor: ~303B routed-expert params → 151.4 GB packed FP4 + block
scales (÷16 FP8 = 18.9 GB NVFP4; ÷32 E8M0 ≈ 9.5 GB MXFP4).
**~176–184 GB is the honest floor for 4-bit MiMo-V2.5** without pruning.
On 2 GPUs only the MXFP4 repo fits, and only at 0.95 utilization.

### ⚠️ INVALID: gaber/* repos — do not use

[gaber/MiMo-V2.5-NVFP4-Experts](https://huggingface.co/gaber/MiMo-V2.5-NVFP4-Experts)
(133.8 GB) and
[gaber/MiMo-V2.5-NVFP4-DFlash](https://huggingface.co/gaber/MiMo-V2.5-NVFP4-DFlash)
(136.7 GB) look attractively small but are **broken, non-functional
uploads** (verified from safetensors headers, 2026-07-15):

- **Zero FP4 tensors** — every tensor is BF16 despite the "NVFP4" name.
- TensorRT Model-Optimizer **fake-quant intermediate**: BF16 weights +
  `*_quantizer._amax` calibration scalars (62,442), captured *before*
  FP4 packing/export.
- **Truncated:** all 47 MoE layers carry `_amax` scalars but only ~10
  layers have actual expert weights (2,580 / 12,032 expert slots) —
  ~75% of expert weights missing from the single 133.8 GB shard.
- `config.json` has no `quantization_config`.

### llama.cpp / GGUF route for MiMo-V2.5

[AesSedai/MiMo-V2.5-GGUF](https://huggingface.co/AesSedai/MiMo-V2.5-GGUF)
(imatrix quants, includes vision mmproj):

| Quant | Size | BPW | PPL increase vs base | KLD | 2-GPU fit |
| --- | --- | --- | --- | --- | --- |
| IQ3_S | 106.31 GiB (114.2 GB) | 2.95 | +8.12% | 0.0924 | Easy, but substantial quality risk |
| **IQ4_XS** | **137.75 GiB (147.9 GB)** | **3.82** | **+2.81%** | **0.0415** | **Comfortable; ~54 GiB raw headroom** |
| Q4_K_M | 177.68 GiB (190.8 GB) | 4.93 | +1.45% | 0.0206 | Tight; only ~14 GiB raw headroom |
| Q5_K_M | 213.39 GiB (229.1 GB) | 5.92 | +0.37% | 0.0148 | Does not fit |
| Q8_0 | 306.66 GiB (329.3 GB) | 8.50 | +0.12% | 0.0120 | Does not fit |

The repo's measured perplexity/KLD results make **IQ4_XS the practical
2-GPU choice**. Q4_K_M may technically fit if both cards expose nearly
their full nominal 96 GiB, but its ~14 GiB total margin must also hold KV,
CUDA workspaces, and llama.cpp overhead; at 160K context, q8_0 KV alone
can consume up to ~5 GB. That is a tight squeeze for a relatively modest
quality improvement over IQ4_XS. Check the cards' actual free MiB before
attempting it.

llama.cpp sidesteps the two things that hurt MiMo elsewhere: no TP
divisibility constraints (layer/row split across any GPU count) and no
utilization-fraction games. With q8_0 KV (halves MiMo's ≤60 KB/tok to
≤30 KB), 160K context costs ≤ 5 GB — hence the `-c 160000` in this
field-tested Strix Halo invocation
([r/StrixHalo comment](https://www.reddit.com/r/StrixHalo/comments/1twtprv/comment/oprze80/)):

```bash
llama-server -m models/AesSedai/MiMo-V2.5-GGUF/MiMo-V2.5-IQ3_S-00001-of-00004.gguf \
  --mmproj models/mmproj/mmproj-MiMo-V2.5-Q8_0.gguf \
  -fa 1 --no-mmap -c 160000 --cache-type-k q8_0 --cache-type-v q8_0 \
  -cram 5140 --ctx-checkpoints 128 --temp 0.6 --top-p 0.95 --top-k 20 \
  --min-p 0.01 --jinja --fit off --parallel 1 -b 8192 -ub 2048 \
  --reasoning-budget 3000 \
  --reasoning-budget-message 'Thinking budget exceeded, answer now' \
  --repeat-penalty 1.05 --repeat-last-n 128
```

Flags worth stealing for agentic serving: `--ctx-checkpoints` + `-cram`
(hybrid-attention state checkpoints in host RAM → cheap prompt-prefix
reuse across agent turns, important because SWA/linear layers can't
rewind like plain KV); `--reasoning-budget 3000` (hard cap on thinking
tokens — directly attacks reasoning-model latency in agent loops);
q8_0 KV both directions. Trade-offs on our rig: llama.cpp MoE decode
won't match vLLM NVFP4 kernels on Blackwell (ballpark 70–110 tok/s for
IQ3_S single-stream on 2× PRO 6000, layer-split), no MTP/DFlash support,
and IQ3_S (2.95 bpw, +8.12% PPL in the repo's measurement) is well
below the NVFP4 quality point — eval before trusting. **IQ4_XS on 2 GPUs**
is the more defensible GGUF configuration; use a third GPU only if choosing
Q5_K_M or if extra runtime/context headroom matters more than utilization.

## DFlash speculative decoding on Blackwell (template)

[AEON-7/Qwen3.6-35B-A3B-heretic-NVFP4-DFlash](https://github.com/AEON-7/Qwen3.6-35B-A3B-heretic-NVFP4-DFlash)
is a working reference for the vLLM DFlash path on Blackwell-class
hardware: Qwen3.6-35B-A3B NVFP4 (~22 GB) + z-lab's 905 MB 8-layer DFlash
drafter, `num_speculative_tokens: 11`, served with
`--speculative-config '{"method":"dflash",...}'` on vLLM v0.23.

Reported on a **GB10 DGX Spark (sm_121a, ~273 GB/s unified memory)**:
91.7 tok/s single-stream on coding, 120+ on math/reasoning, 40–58% draft
acceptance holding at 16–32K context, ~740 tok/s aggregate at c=64.
Getting ~92 tok/s coding from a ~273 GB/s box implies an effective ~4×
uplift from acceptance — on a PRO 6000 (1.79 TB/s, 6.5× the bandwidth)
the same recipe should land in the **several-hundred-tok/s** range
single-stream for an A3B-class model.

Caveats / relevance to us:
- The published Docker image is **built for sm_121a only** — it will not
  run on PRO 6000 (sm_120) without rebuilding vLLM; the recipe, not the
  image, is what transfers. It also carries the prefix-cache-safe DFlash
  fix (vLLM PR #41703) that matters for agent loops.
- Direct application: the MiMo-V2.5 DFlash quants above use the same
  vLLM `method: dflash` path — this repo is evidence the path works.
- Ornith angle: Ornith-1.0-35B is Qwen3.5-MoE lineage with a nearly
  identical shape to Qwen3.6-35B-A3B; if a z-lab-style drafter exists or
  can be trained for it, Ornith's ~150–190 tok/s could plausibly double,
  compounding the "2 replicas" advantage.

## MiniMax M2.7 (230B-A10B)

[MiniMaxAI/MiniMax-M2.7](https://huggingface.co/MiniMaxAI/MiniMax-M2.7)
(BF16, 230.1 GB) — 62 layers **all full attention** (`attn_type_list`
all-1), GQA 8 KV × 128, 256 experts top-8 (`intermediate` 1536), 205K
context, 3 MTP modules. Official quant:
[nvidia/MiniMax-M2.7-NVFP4](https://huggingface.co/nvidia/MiniMax-M2.7-NVFP4)
= **139.9 GB**: experts U8 112.3 + FP8 scales 14.0 GB, attention stored
F32 10.9 GB (loads BF16), embed/head BF16 2.5 GB. **No MTP tensors — the
NVFP4 repo strips them**, so no self-speculative decode from this repo.

Best all-around 2-GPU citizen: biggest KV headroom, best SWE-ML score.
Weaknesses: priciest KV per token (~124 KB), O(n²) prefill at long
context, no spec decode, 205K cap.

## DeepSeek V4 Flash (284B-A13B)

[deepseek-ai/DeepSeek-V4-Flash](https://huggingface.co/deepseek-ai/DeepSeek-V4-Flash)
— **natively ~4-bit**: the official repo ships I8-packed FP4 experts
(138.5 GB) + E8M0 block-32 scales (8.7 GB) — MXFP4-style — with FP8
attention/shared-expert and a quantized 1-layer MTP (3.8 GB), totaling
**159.6 GB**. No third-party quant needed; MIT license; 1M context via
MLA latent KV + DSA (top-512 indexer) + SWA-128.
[nvidia/DeepSeek-V4-Flash-NVFP4](https://huggingface.co/nvidia/DeepSeek-V4-Flash-NVFP4)
is the same content rescaled to NVFP4 (FP8 ÷16 scales → 168.5 GB) — the
native repo is strictly smaller with no known quality downside; prefer it.

Highest SWE-V (79.0), cheapest KV (~24 KB/tok → ~420K tokens even at
0.90 util), MTP included (est. 210–380 tok/s effective), fastest
long-context prefill. The best *speed × score* package of the group.

## Hy3 (Tencent, 295B-A21B) — the 3-GPU pick, and a 2-GPU dark horse

[tencent/Hy3](https://huggingface.co/tencent/Hy3) — `hy_v3`, 80 layers,
GQA 64 Q / 8 KV heads × 128, 192 routed experts top-8
(`moe_intermediate` 1536 → 290B routed params) + shared expert, 1 nextn
(MTP) layer, 262K context. Native BF16 = 597.6 GB;
[tencent/Hy3-FP8](https://huggingface.co/tencent/Hy3-FP8) = 299.9 GB
(doesn't fit even 3×0.95 = 273.6). Best scores of any candidate on
SWE-Pro (57.9); **no published Terminal-Bench score**.

### Parallelism / divisibility

| Scheme | Divisible? | Notes |
| --- | --- | --- |
| TP=2 | ✅ 64/2 Q, 8/2 KV, 192/2 experts, 1536/2 FFN | standard vLLM path |
| **TP=3** | ❌ **64 Q-heads % 3 ≠ 0** | vLLM/SGLang reject at startup; KV heads (8) would also replicate |
| PP=3 | ✅ 80 layers → 27/27/26 | works today (`-tp 1 -pp 3`); single-stream decode capped at ~1-GPU bandwidth, but no allreduce tax and batching fills the pipeline |
| EP across 3 | 192 % 3 = 0 ✓ but attention is still TP-bound | doesn't rescue TP=3 |
| llama.cpp layer split | ✅ any GPU count | GGUFs exist incl. Tencent's own [AngelSlim/Hy3-GGUF](https://huggingface.co/AngelSlim/Hy3-GGUF); slower MoE decode, fallback only |
| TP=4 | ✅ all dims | if a 4th GPU ever appears, Hy3 is clean |

So on 3 GPUs the realistic serving mode is **PP=3**, not TP=3. The
alternative use of a 3rd GPU: run Hy3 TP=2 with a small repo (below) and
give GPU 3 to a second model (e.g. an Ornith replica) for cospa matrix
throughput.

### Available quants (headers verified 2026-07-15; all legit, full expert coverage)

| Repo | Size | Experts | Attention | Dense/shared | Risk notes |
| --- | --- | --- | --- | --- | --- |
| [INCModel2/Hy3-MXFP4-Mixed-CT-AutoRound-Preview](https://huggingface.co/INCModel2/Hy3-MXFP4-Mixed-CT-AutoRound-Preview) | **164.2** | MXFP4 154.0 | **FP8** 6.1 | FP8 | best balance: FP8 attention, AutoRound-calibrated, "Preview" |
| [0xSero/Hy3-299B-NVFP4](https://huggingface.co/0xSero/Hy3-299B-NVFP4) | 169.6 | NVFP4 145.0+18.1 | **FP4** 3.4 | FP4 | smallest NVFP4 but FP4 *attention* — highest quality risk |
| [cyankiwi/Hy3-AWQ-NVFP4](https://huggingface.co/cyankiwi/Hy3-AWQ-NVFP4) | 177.5 | NVFP4 + 7.2 BF16 kept | FP4 3.7 | BF16 | AWQ-selected BF16 experts |
| [kodelow/Hy3-NVFP4-W4A16](https://huggingface.co/kodelow/Hy3-NVFP4-W4A16) | 180.9 | NVFP4 145.0+18.1 | **BF16** 12.2 | BF16 | safest recipe, 3-GPU-only fit |
| [r0b0tlab/Hy3-295B-NVFP4](https://huggingface.co/r0b0tlab/Hy3-295B-NVFP4) / [mmangkad](https://huggingface.co/mmangkad/Hy3-NVFP4) | 186.1 | NVFP4 | BF16-ish | — | 3-GPU only |
| REAP-pruned ([sapidlabs 48e](https://huggingface.co/sapidlabs/Hy3-REAP-48e) 168.1, pipenetwork MLX) | 45–168 | pruned experts | — | — | no published post-prune scores; MLX ones are Mac-only |

MTP caveat: the base model's 1 nextn layer (3.8B) is not clearly present
in any of these quants (no distinct MTP tensors in headers) — assume **no
self-speculative decode** until verified;
[VictorEuler/Hy3-preview-mtp-drafter](https://huggingface.co/VictorEuler/Hy3-preview-mtp-drafter)
exists but targets Hy3-*preview*.

### KV and speed estimates

KV: ~160 KB/token FP8 (80 all-global layers) — the most expensive of any
candidate. Bytes/token (batch-1, from stored dtypes; routed active =
8/192 of expert bytes ≈ 6.4–7.0 GB):

| Repo | Bytes/token | 2× TP2 est. (45–60% MBU) | 3× PP3 est. (~1-GPU BW, 55–65%) |
| --- | --- | --- | --- |
| INCModel2 MXFP4 | ~15.6 GB | **103–138 tok/s** | 63–75 tok/s |
| 0xSero NVFP4 | ~12.2 GB | 132–176 tok/s | 80–96 tok/s |
| kodelow NVFP4 | ~23.4 GB | n/a (doesn't fit) | 42–50 tok/s |

Context budgets (FP8 KV, minus ~3 GB activations):
- **2× TP2, INCModel2 @0.92**: ~9.4 GB → ~58K tokens; @0.95 → ~94K.
  Single-stream agentic only, but *it does fit* — Hy3 on 192 GB is not
  dead, it just requires the smallest quant and modest context.
- **3× PP3, kodelow @0.90**: ~74 GB → ~460K tokens aggregate; full 256K
  single-stream with room for batch. This is the comfortable config.

Verdict: on 3 GPUs Hy3 is the score leader (SWE-V 78 / SWE-Pro 57.9) and
fits easily, but PP=3 caps single-stream decode at ~50–75 tok/s and the
missing TB score + missing MTP are open questions. On 2 GPUs the
INCModel2 MXFP4 repo makes it a legitimate dark horse at ~103–138 tok/s
with ~58–94K context — worth a cospa sanity eval against DS V4 Flash.

## Ruled out (at 2 GPUs)

| Model | Why |
| --- | --- |
| [nvidia/MiniMax-M3-NVFP4](https://huggingface.co/nvidia/MiniMax-M3-NVFP4) | 250.1 GB — 3 GPUs only, marginal at 0.90. |
| [sparkarena/Minimax-M3-v0-NVFP4-REAP25](https://huggingface.co/sparkarena/Minimax-M3-v0-NVFP4-REAP25) | 187.0 GB — over 2-GPU budget at any utilization; no published post-prune scores. |
| gaber/MiMo-V2.5-* | Broken uploads — see warning above. |

## Recommendation (2× PRO 6000)

1. **DeepSeek V4 Flash (native, 159.6 GB)** — best SWE-V, official
   4-bit weights, MTP spec decode, near-linear prefill, huge context at
   safe 0.90 utilization. Weakest claim: no published SWE-Pro/TB edge.
2. **MiniMax M2.7 NVFP4 (139.9 GB)** — most headroom, best SWE-ML;
   loses spec decode (stripped MTP) and pays O(n²) prefill + heavy KV.
3. **MiMo-V2.5 MXFP4 (176.6 GB)** — only candidate to edge Ornith on
   Terminal-Bench, but needs 0.95 utilization, is single-stream, ~95–125
   tok/s, and the quant is community/unvalidated.
4. **Hy3 MXFP4 (INCModel2, 164.2 GB)** — dark horse: best SWE-Pro
   (57.9), fits TP=2 at 0.90, ~103–138 tok/s, but only ~58–94K context
   and an unvalidated preview quant. See the Hy3 section.
5. **Ornith-1.0-35B** remains the value baseline: one GPU, top TB score,
   ~150–190 tok/s, near-nil KV cost — and 2 replicas on this rig doubles
   cospa trial throughput.

On 3 GPUs: **Hy3 (kodelow NVFP4, PP=3)** for max scores with the safest
quant recipe, accepting ~42–50 tok/s single-stream — or keep DS V4 Flash
on TP=2 and give GPU 3 to an Ornith replica for matrix throughput.
