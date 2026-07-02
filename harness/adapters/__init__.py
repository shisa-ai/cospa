"""
Adapter registry — load adapters by name.
"""

from harness.adapters.pi_vanilla import PiVanillaAdapter
from harness.adapters.pi_devstack import PiDevstackAdapter
from harness.adapters.little_coder import LittleCoderAdapter

ADAPTERS = {
    "pi_vanilla": PiVanillaAdapter,
    "pi_devstack": PiDevstackAdapter,
    "little_coder": LittleCoderAdapter,
}


def load_adapter(name: str):
    """Load an adapter by name."""
    if name not in ADAPTERS:
        raise ValueError(f"Unknown adapter: {name}. Available: {list(ADAPTERS.keys())}")
    return ADAPTERS[name]()
