#!/usr/bin/env python
"""Summarize per-run cost from trial manifests (RUN-MANAGEMENT P5).

Scans the given directories (default: results/runs) for manifest.json files,
prices each trial from models.yaml prices x pi usage (using runtime
manifest.cost when present, re-deriving for historical manifests), and writes
cost-summary.json into each scanned directory.

Usage:
    python scripts/summarize-costs.py [DIR ...] [--out NAME]
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from harness.cost_summary import aggregate, iter_manifests, write_summary


def main(argv=None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    out_name = "cost-summary.json"
    if "--out" in args:
        idx = args.index("--out")
        if idx + 1 >= len(args):
            print("Error: --out requires a filename", file=sys.stderr)
            return 2
        out_name = args.pop(idx + 1)
        args.pop(idx)
    roots = [Path(a) for a in args] or [PROJECT_ROOT / "results" / "runs"]

    grand_total = 0.0
    grand_priced = 0
    grand_unpriced = 0
    for root in roots:
        manifests = iter_manifests(root)
        summary = aggregate(manifests)
        path = write_summary(root, summary, name=out_name)
        print(f"{root}: {summary['total_trials']} trials, "
              f"{summary['priced_trials']} priced, "
              f"${summary['total_usd']:.4f} -> {path}")
        grand_total += summary["total_usd"]
        grand_priced += summary["priced_trials"]
        grand_unpriced += summary["unpriced_trials"]

    print(f"TOTAL: ${grand_total:.4f} "
          f"({grand_priced} priced / {grand_unpriced} unpriced trials)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
