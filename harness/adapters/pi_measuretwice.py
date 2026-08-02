"""Harbor-only Measure Twice adapter labels for recovery experiments.

Terminal-Bench execution is owned by Harbor. These labels exist so the outer
runner can retain distinct strategy identities without pretending that a host
Pi invocation reproduces the container boundary.
"""

from __future__ import annotations


class _PiMeasureTwiceHarborOnlyAdapter:
    name = "pi_measuretwice"
    version = "measuretwice-harbor-v1"
    uses_workspace_sandbox = False

    def run(self, *args, **kwargs):
        raise RuntimeError(
            f"{self.name} is Harbor-only and must be used with terminal_bench"
        )


class PiMeasureTwiceCheckSameAdapter(_PiMeasureTwiceHarborOnlyAdapter):
    name = "pi_measuretwice_check_same"


class PiMeasureTwiceCheckCrossAdapter(_PiMeasureTwiceHarborOnlyAdapter):
    name = "pi_measuretwice_check_cross"


class PiMeasureTwiceRepairSameAdapter(_PiMeasureTwiceHarborOnlyAdapter):
    name = "pi_measuretwice_repair_same"


class PiMeasureTwiceRepairCrossAdapter(_PiMeasureTwiceHarborOnlyAdapter):
    name = "pi_measuretwice_repair_cross"
