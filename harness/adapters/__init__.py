"""
Adapter registry — load adapters by name.
"""

from harness.adapters.pi_vanilla import PiVanillaAdapter
from harness.adapters.pi_devstack import PiDevstackAdapter
from harness.adapters.pi_devstack_superpowers import PiDevstackSuperpowersAdapter
from harness.adapters.little_coder import LittleCoderAdapter
from harness.adapters.pi_superpowers import PiSuperpowersAdapter
from harness.adapters.little_coder_superpowers import LittleCoderSuperpowersAdapter
from harness.adapters.bigcodebench_openai import BigCodeBenchOpenAIAdapter
from harness.adapters.pi_measuretwice import (
    PiMeasureTwiceCheckCrossAdapter,
    PiMeasureTwiceCheckSameAdapter,
    PiMeasureTwiceRepairCrossAdapter,
    PiMeasureTwiceRepairSameAdapter,
)

AGENTIC_ADAPTERS = {
    "pi_vanilla": PiVanillaAdapter,
    "pi_devstack": PiDevstackAdapter,
    "pi_devstack_superpowers": PiDevstackSuperpowersAdapter,
    "little_coder": LittleCoderAdapter,
    "pi_superpowers": PiSuperpowersAdapter,
    "little_coder_superpowers": LittleCoderSuperpowersAdapter,
    # Harbor-only recovery labels: they never run a host Pi invocation, so
    # they are excluded from the prompt-behavior agentic registry and are
    # resolved by terminal_bench through harness/harbor_agents.py instead.
}

HARBOR_ONLY_ADAPTERS = {
    "pi_measuretwice_check_same": PiMeasureTwiceCheckSameAdapter,
    "pi_measuretwice_check_cross": PiMeasureTwiceCheckCrossAdapter,
    "pi_measuretwice_repair_same": PiMeasureTwiceRepairSameAdapter,
    "pi_measuretwice_repair_cross": PiMeasureTwiceRepairCrossAdapter,
}

PROTOCOL_ADAPTERS = {
    "bigcodebench_openai": BigCodeBenchOpenAIAdapter,
}

ADAPTERS = {**AGENTIC_ADAPTERS, **PROTOCOL_ADAPTERS, **HARBOR_ONLY_ADAPTERS}


def load_adapter(name: str):
    """Load an adapter by name."""
    if name not in ADAPTERS:
        raise ValueError(f"Unknown adapter: {name}. Available: {list(ADAPTERS.keys())}")
    return ADAPTERS[name]()
