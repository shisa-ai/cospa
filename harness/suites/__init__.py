"""
Suite registry — load suites by name.
"""

from harness.suites.aider_polyglot import AiderPolyglotSuite
from harness.suites.terminal_bench import TerminalBenchSuite

SUITES = {
    "aider_polyglot": AiderPolyglotSuite,
    "terminal_bench": TerminalBenchSuite,
}


def load_suite(name: str):
    """Load a suite by name."""
    if name not in SUITES:
        raise ValueError(f"Unknown suite: {name}. Available: {list(SUITES.keys())}")
    return SUITES[name]()
