# Reports index

Auto-generated from embedded aggregate markers. One section per model family; rows are unique (thinking, tasks) runs so effort rungs sit beside full-matrix rows. Regenerate with `scripts/generate-report.py --build-index <reports-dir>`.

## local/deepseek-v4-flash-0731

| Thinking | Tasks | Report | bigcodebench_hard_agentic_pareto60 | bigcodebench_hard_agentic_hermetic143 | bigcodebench_hard_instruct_hermetic143 | Micro | In | Cached | Out | Wall | Elapsed |
| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| off | 60 | [effort-sweep-pareto60.md](effort-sweep-pareto60.md) | 33.3 | - | - | 33.3% | 146K | 1.1M | 91K | 33m28s | 5m02s |
| low | 60 | [effort-sweep-pareto60.md](effort-sweep-pareto60.md) | 33.3 | - | - | 33.3% | 131K | 1.6M | 150K | 53m07s | 7m23s |
| high | 193 | [ds4-pareto-baseline-k1-and-stability32.md](ds4-pareto-baseline-k1-and-stability32.md) | 36.7 | - | - | 35.8% | 6.9M | 229.3M | 2.8M | 18h34m | 11h10m |
| high | 143 | [ds4-vanilla-high-matrix.md](ds4-vanilla-high-matrix.md) | - | 30.8 | - | 30.8% | 367K | 4.1M | 441K | 2h38m | 1h36m |
| high | 60 | [effort-sweep-pareto60.md](effort-sweep-pareto60.md) | 31.7 | - | - | 31.7% | 130K | 1.2M | 148K | 53m26s | 9m30s |
| xhigh | 60 | [effort-sweep-pareto60.md](effort-sweep-pareto60.md) | 40.0 | - | - | 40.0% | 219K | 3.8M | 341K | 1h55m | 17m16s |
| not_applicable | 143 | [ds4-pareto-baseline-k1-and-stability32.md](ds4-pareto-baseline-k1-and-stability32.md) | - | - | 11.9 | 11.9% | 28K | 0 | 140K | 41m56s | 7m10s |

## local/qwen3.8-27b

| Thinking | Tasks | Report | bigcodebench_hard_agentic_pareto60 | bigcodebench_hard_agentic_hermetic143 | bigcodebench_hard_instruct_hermetic143 | Micro | In | Cached | Out | Wall | Elapsed |
| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| off | 60 | [effort-sweep-pareto60.md](effort-sweep-pareto60.md) | 25.0 | - | - | 25.0% | 2.0M | 1.9M | 157K | 3h49m | 52m19s |
| low | 60 | [effort-sweep-pareto60.md](effort-sweep-pareto60.md) | 31.7 | - | - | 31.7% | 2.4M | 1.1M | 290K | 6h23m | 50m30s |
| medium | 60 | [effort-sweep-pareto60.md](effort-sweep-pareto60.md) | 31.7 | - | - | 31.7% | 1.8M | 892K | 216K | 5h04m | 40m44s |
| high | 60 | [effort-sweep-pareto60.md](effort-sweep-pareto60.md) | 33.3 | - | - | 33.3% | 8.9M | 885K | 877K | 23h19m | 3h02m |
| high | 336 | [qwen38-vanilla-high-matrix.md](qwen38-vanilla-high-matrix.md) | - | 29.4 | - | 30.1% | 20.9M | 459.5M | 7.9M | 64h45m | 15h21m |
| xhigh | 60 | [effort-sweep-pareto60.md](effort-sweep-pareto60.md) | 15.0 | - | - | 15.0% | 8.2M | 986K | 944K | 24h53m | 3h14m |
| not_applicable | 143 | [qwen38-vanilla-high-matrix.md](qwen38-vanilla-high-matrix.md) | - | - | 34.3 | 34.3% | 30K | 0 | 69K | 6m45s | 2m32s |

## codex/gpt-5.3-codex-spark

| Thinking | Tasks | Report | bigcodebench_hard_agentic_hermetic143 | Micro | In | Cached | Out | Wall | Elapsed |
| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| high | 336 | [gpt53spark-vanilla-high-matrix.md](gpt53spark-vanilla-high-matrix.md) | 32.9 | 30.4% | 18.6M | 490.7M | 5.9M | 18h33m | 43h44m |

## shisa/ornith-35b-fp8-block

| Thinking | Tasks | Report | bigcodebench_hard_agentic_hermetic143 | Micro | In | Cached | Out | Wall | Elapsed |
| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| high | 336 | [ornith35-vanilla-high-matrix.md](ornith35-vanilla-high-matrix.md) | 30.1 | 17.3% | 753K | 8.3M | 420K | 103h00m | 22h55m |

