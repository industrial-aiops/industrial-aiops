"""Executable evidence that the analysis is reproducible without a model.

The static guarantee (nothing in the analysis layers *can* import a model) lives
in ``tests/test_brain_is_llm_free.py``. This package is the executed one: a
pinned dataset, a named suite of computations over it, and a signable record of
their digests — the form a validation team needs in order to write "remove the
model, block the network, re-run, compare the hash" into a protocol.
"""

from iaiops.core.verify.determinism import (
    VERDICT_NOT_REPRODUCIBLE,
    VERDICT_REPRODUCIBLE,
    NetworkBlockedError,
    canonical_bytes,
    dataset_digest,
    digest,
    model_modules_loaded,
    no_network,
    run_determinism_check,
    run_suite,
    suite_digest,
)
from iaiops.core.verify.suite import CHECKS, Check, check_names

__all__ = [
    "CHECKS",
    "VERDICT_NOT_REPRODUCIBLE",
    "VERDICT_REPRODUCIBLE",
    "Check",
    "NetworkBlockedError",
    "canonical_bytes",
    "check_names",
    "dataset_digest",
    "digest",
    "model_modules_loaded",
    "no_network",
    "run_determinism_check",
    "run_suite",
    "suite_digest",
]
