"""
Suite registry — load suites by name.
"""

from harness.suites.aider_polyglot import AiderPolyglotSuite
from harness.suites.terminal_bench import TerminalBenchSuite
from harness.suites.swe_atlas import SweAtlasPilotSuite
from harness.suites.bigcodebench import (
    BigCodeBenchHardAgenticHermeticSuite,
    BigCodeBenchHardAgenticPareto60Suite,
    BigCodeBenchHardAgenticSuite,
    BigCodeBenchHardInstructHermeticSuite,
    BigCodeBenchHardInstructSuite,
)
from harness.suites.swe_polybench import SwePolyBenchVerifiedSuite
from harness.suites.multi_swe_bench import MultiSweBenchFlashHermeticSuite

SUITES = {
    "aider_polyglot": AiderPolyglotSuite,
    "terminal_bench": TerminalBenchSuite,
    "swe_atlas_pilot12": SweAtlasPilotSuite,
    "bigcodebench_hard_instruct": BigCodeBenchHardInstructSuite,
    "bigcodebench_hard_instruct_hermetic143": BigCodeBenchHardInstructHermeticSuite,
    "bigcodebench_hard_agentic": BigCodeBenchHardAgenticSuite,
    "bigcodebench_hard_agentic_hermetic143": BigCodeBenchHardAgenticHermeticSuite,
    "bigcodebench_hard_agentic_pareto60": BigCodeBenchHardAgenticPareto60Suite,
    "swe_polybench_verified": SwePolyBenchVerifiedSuite,
    "multi_swe_bench_flash_hermetic25": MultiSweBenchFlashHermeticSuite,
}


def load_suite(name: str):
    """Load a suite by name."""
    if name not in SUITES:
        raise ValueError(f"Unknown suite: {name}. Available: {list(SUITES.keys())}")
    return SUITES[name]()
