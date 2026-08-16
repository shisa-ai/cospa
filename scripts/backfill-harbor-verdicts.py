#!/usr/bin/env python
"""Backfill Harbor agent-phase verdicts from job evidence (pre-deadline fix)."""

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from harness.backfill_harbor_verdicts import main


if __name__ == "__main__":
    raise SystemExit(main())
