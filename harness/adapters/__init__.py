"""
Adapter registry — load adapters by name.
"""

from harness.adapters.pi_vanilla import PiVanillaAdapter
from harness.adapters.pi_devstack import PiDevstackAdapter
from harness.adapters.pi_devstack_superpowers import PiDevstackSuperpowersAdapter
from harness.adapters.little_coder import LittleCoderAdapter
from harness.adapters.pi_superpowers import PiSuperpowersAdapter
from harness.adapters.little_coder_superpowers import LittleCoderSuperpowersAdapter

ADAPTERS = {
    "pi_vanilla": PiVanillaAdapter,
    "pi_devstack": PiDevstackAdapter,
    "pi_devstack_superpowers": PiDevstackSuperpowersAdapter,
    "little_coder": LittleCoderAdapter,
    "pi_superpowers": PiSuperpowersAdapter,
    "little_coder_superpowers": LittleCoderSuperpowersAdapter,
}


def load_adapter(name: str):
    """Load an adapter by name."""
    if name not in ADAPTERS:
        raise ValueError(f"Unknown adapter: {name}. Available: {list(ADAPTERS.keys())}")
    return ADAPTERS[name]()
