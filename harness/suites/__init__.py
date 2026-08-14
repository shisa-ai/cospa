"""
Suite registry — load suites by name.
"""

from harness.suites.aider_polyglot import AiderPolyglotSuite
from harness.suites.terminal_bench import TerminalBenchSuite
from harness.suites.swe_atlas import SweAtlasPilotSuite
from harness.suites.bigcodebench import BigCodeBenchHardInstructSuite

SUITES = {
    "aider_polyglot": AiderPolyglotSuite,
    "terminal_bench": TerminalBenchSuite,
    "swe_atlas_pilot12": SweAtlasPilotSuite,
    "bigcodebench_hard_instruct": BigCodeBenchHardInstructSuite,
}


def load_suite(name: str):
    """Load a suite by name."""
    if name not in SUITES:
        raise ValueError(f"Unknown suite: {name}. Available: {list(SUITES.keys())}")
    return SUITES[name]()
