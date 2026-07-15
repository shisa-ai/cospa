# Candidate Models for 2× RTX PRO 6000 (192 GB VRAM)

Research notes (2026-07-15) on open-weight models that fit in **2× 96 GB
(192 GB total)** and might outperform **Ornith-1.0-35B** on agentic coding
benchmarks. All repo sizes measured via the HF API (`usedStorage`); quant
compositions verified by reading **safetensors headers only** (HTTP range
requests — no weight downloads).

Caveats that apply throughout:

- All scores are **vendor self-reported** unless noted; scaffolds differ
  (OpenHands vs Terminus-2 vs Claude Code) and can swing results by points.
- Terminal-Bench versions are inconsistent across cards (2.0 vs 2.1) —
  cross-model TB comparisons are approximate.
- None of the community 4-bit quants publish quality deltas. Sanity-eval
  with cospa before trusting any of them at Ornith-beating levels.

## Baseline: Ornith-1.0-35B

[deepreinforce-ai/Ornith-1.0-35B](https://huggingface.co/deepreinforce-ai/Ornith-1.0-35B)
— 35B MoE (post-trained on Qwen 3.5), BF16 ≈ 70 GB, 256K context.
**Fits on a single 96 GB GPU** with huge KV headroom (could run 2 replicas).

| Benchmark | Score | Harness |
| --- | --- | --- |
| SWE-bench Verified | 75.6 | OpenHands |
| SWE-bench Pro (public) | 50.4 | OpenHands |
| SWE-bench Multilingual | 69.3 | OpenHands |
| Terminal-Bench 2.1 | 64.2 (62.8 w/ Claude Code scaffold) | Terminus-2 |

## Benchmark comparison (self-reported)

| Model | Arch | SWE-V | SWE-Pro | SWE-ML | Terminal-Bench |
| --- | --- | --- | --- | --- | --- |
| Ornith-1.0-35B | 35B MoE | 75.6 | 50.4 | 69.3 | **64.2** (2.1) |
| MiMo-V2.5 | 310B-A15B | n/pub (Pro: 78.9) | **56.1** | — | **65.8** (2.0) |
| MiniMax M2.7 | ~230B MoE | 78.0 | 56.2 | **76.5** | 57.0 (2.0) |
| DeepSeek V4 Flash | 284B-A13B | **79.0** | — | — | 56.9 (2.0) |
| Hy3 (ruled out) | 295B-A21B | 78.0 | 57.9 | — | n/pub |

Reading: MiMo-V2.5 is the only one that (roughly) matches/beats Ornith on
Terminal-Bench; M2.7 and V4 Flash beat it on SWE-bench-style tasks but
trail ~7 pts on terminal work. Nothing dominates Ornith outright.

## VRAM budget model

- Total: 192 GB (2× 96 GB, tensor-parallel TP=2).
- Reserve **~8–10 GB** for CUDA context, activations / workspace, TP
  comm buffers, and serving-framework overhead (≈4–5 GB per GPU).
- vLLM default `--gpu-memory-utilization 0.9` caps usable at **172.8 GB**;
  the tight fits below require raising it to 0.95 (182.4 GB) or higher.
- KV budget ≈ `192 − weights − 9` GB. KV cache assumed **FP8**.

Per-token KV cost (from each model's `config.json`, FP8 = 1 byte/elem):

| Model | Attention | KV elems/token | KV @ FP8 | 128K ctx costs |
| --- | --- | --- | --- | --- |
| MiniMax M2.7 | 62 layers, all full GQA, 8 KV heads × 128 | 62 × 2×8×128 = 126,976 | ~124 KB/tok | ~16.2 GB |
| DeepSeek V4 Flash | 43 layers, MLA-style (1 latent "head", 512 + 64 rope) + DSA (`index_topk` 512, `sliding_window` 128) | 43 × 576 = 24,768 | ~24 KB/tok | ~3.2 GB |
| MiMo-V2.5 | 48 layers, hybrid SWA(128)/global, 4 KV heads, qk 192 / v 128 | ≤ 48 × (4×192 + 4×128) = 61,440 (all-global upper bound; global-layer share not in config — interleave ratio unpublished) | ≤ 60 KB/tok; ~30 KB if 1:1 interleave | ~7.7 GB worst case, ~4 GB @ 1:1 |
| Hy3 | 80 layers, all full GQA, 8 KV heads × 128 | 80 × 2×8×128 = 163,840 | ~160 KB/tok | ~21 GB |

## MiMo-V2.5 (Xiaomi, 310B-A15B)

[XiaomiMiMo/MiMo-V2.5](https://huggingface.co/XiaomiMiMo/MiMo-V2.5) —
sparse MoE, 48 layers (1 dense + 47 MoE), 256 experts top-8, hybrid
SWA/global attention, 1M context, native FP8, multimodal (729M ViT +
261M audio towers). Native repo: **315.7 GB** — needs 4-bit to fit.

Quant repos (headers verified 2026-07-15):

| Repo | Size | Experts | Attention | Other |
| --- | --- | --- | --- | --- |
| [chriswritescode/MiMo-V2.5-DFlash-MXFP4A16](https://huggingface.co/chriswritescode/MiMo-V2.5-DFlash-MXFP4A16) | **176.6 GB** | U8 160.9 GB (MXFP4 packed, E8M0 scales embedded) | BF16 4.5 + FP8 2.9 GB | MTP FP8, vision/audio BF16 |
| [mitomtuna/MiMo-V2.5-0703-NVFP4](https://huggingface.co/mitomtuna/MiMo-V2.5-0703-NVFP4) | 183.5 GB | U8 151.4 + FP8 scales 18.9 GB | FP8 2.9 + BF16 3.8 GB | MTP FP8, vision/audio BF16 |
| [shadowlilac/MiMo-V2.5-NVFP4](https://huggingface.co/shadowlilac/MiMo-V2.5-NVFP4) | 187.2 GB | U8 151.4 + FP8 scales 18.9 GB | all BF16 (9.5 GB) | MTP BF16 |

Size floor check: ~303B routed-expert params → 151.4 GB packed FP4 +
18.9 GB FP8 block scales (÷16, NVFP4) or ~9.5 GB E8M0 (÷32, MXFP4).
**~176–184 GB is the honest floor for 4-bit MiMo-V2.5** without pruning.

Fit @ 192 GB (MXFP4 176.6 GB): ~6 GB KV after overhead → **~100K tokens
worst-case, ~200K if 1:1 interleave** — workable for single-stream agentic
use, no batch headroom. NVFP4 repos (183.5–187.2 GB): ~0–4 GB KV —
marginal to unusable. Requires `--gpu-memory-utilization ≥ 0.97`.

### ⚠️ INVALID: gaber/* repos — do not use

[gaber/MiMo-V2.5-NVFP4-Experts](https://huggingface.co/gaber/MiMo-V2.5-NVFP4-Experts)
(133.8 GB) and
[gaber/MiMo-V2.5-NVFP4-DFlash](https://huggingface.co/gaber/MiMo-V2.5-NVFP4-DFlash)
(136.7 GB) look attractively small but are **broken, non-functional
uploads** (verified from safetensors headers, 2026-07-15):

- **Zero FP4 tensors** — every tensor is BF16 despite the "NVFP4" name.
- It is a TensorRT Model-Optimizer **fake-quant intermediate** checkpoint:
  BF16 weights + `*_quantizer._amax` calibration scalars (62,442 of them),
  captured *before* FP4 packing/export.
- **Truncated:** all 47 MoE layers carry `_amax` scalars, but only ~10
  layers have actual expert weights (2,580 / 12,032 expert slots). ~75%
  of expert weights are missing from the single 133.8 GB shard.
- `config.json` has no `quantization_config`.

## MiniMax M2.7 (~230B MoE)

[MiniMaxAI/MiniMax-M2.7](https://huggingface.co/MiniMaxAI/MiniMax-M2.7)
(BF16, 230.1 GB) — 62 layers all-full-attention GQA, 256 experts top-8,
205K context. Official NVIDIA quant:
[nvidia/MiniMax-M2.7-NVFP4](https://huggingface.co/nvidia/MiniMax-M2.7-NVFP4)
= **139.9 GB** (size-consistent with a real NVFP4 of ~230B: ~115 GB packed
+ ~7 GB scales + BF16 remainder).

Fit @ 192 GB: 192 − 139.9 − 9 ≈ **43 GB KV** → ~350K tokens aggregate
@ FP8 KV. Full 205K context single-stream, or ~2–5 concurrent agentic
requests. The **most practical strong candidate** — official quant,
comfortable margins. Note all-global attention makes KV the priciest per
token here (~124 KB/tok), but the weight headroom absorbs it.

## DeepSeek V4 Flash (284B-A13B)

[deepseek-ai/DeepSeek-V4-Flash](https://huggingface.co/deepseek-ai/DeepSeek-V4-Flash)
— native repo **159.6 GB** (fits without third-party quants), MLA-style
compressed KV + DSA sparse attention, 1M context, MIT license.
[nvidia/DeepSeek-V4-Flash-NVFP4](https://huggingface.co/nvidia/DeepSeek-V4-Flash-NVFP4)
is *larger* (175.7 GB — likely includes MTP weights / different tensor
retention; verify headers before preferring it).

Fit @ 192 GB (native): 192 − 159.6 − 9 ≈ **23 GB KV** at only ~24 KB/tok
→ ~950K tokens aggregate. Long-context and batch-friendly despite the
tighter weight fit. A13B = fastest decode of the group.

## Ruled out

| Model | Why |
| --- | --- |
| [tencent/Hy3](https://huggingface.co/tencent/Hy3) 295B-A21B | Great scores (SWE-V 78, SWE-Pro 57.9) but 4-bit quants are 180.9–186.1 GB **and** all-global attention costs ~160 KB/tok KV → no room for agentic context. |
| [nvidia/MiniMax-M3-NVFP4](https://huggingface.co/nvidia/MiniMax-M3-NVFP4) | 250.1 GB — does not fit. |
| [sparkarena/Minimax-M3-v0-NVFP4-REAP25](https://huggingface.co/sparkarena/Minimax-M3-v0-NVFP4-REAP25) | 187.0 GB — marginal fit, expert-pruned with no published post-prune benchmark scores. |
| gaber/MiMo-V2.5-* | Broken uploads — see warning above. |

## Recommendation

1. **MiniMax M2.7 NVFP4 (139.9 GB)** — best practicality/score balance;
   official quant, real KV headroom. Beats Ornith on all SWE-bench axes;
   loses ~7 pts on Terminal-Bench.
2. **DeepSeek V4 Flash (159.6 GB native)** — best SWE-V (79.0), huge
   context, fastest decode; same TB weakness.
3. **MiMo-V2.5 MXFP4 (176.6 GB)** — only candidate to edge Ornith on
   Terminal-Bench (65.8 TB2.0 vs 64.2 TB2.1), but the fit is tight
   (~6 GB KV) and the quant is community/unvalidated.
4. **Ornith-1.0-35B** remains the value baseline: single GPU, top TB
   score, room for 2 replicas or high batch on this rig.
