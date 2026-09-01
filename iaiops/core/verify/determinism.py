"""Run the reference suite and prove the outputs are reproducible.

`tests/test_brain_is_llm_free.py` scans the analysis layers for any import that
could reach a language model, and an empty result is its guarantee. That test is
static: it proves nothing *can* call a model. It does not run anything, and the
sentence people actually repeat about this product — remove the model, pull the
network, run the same data again and the output is byte-identical — was written
in that test's docstring and executed nowhere.

For most audiences that gap does not matter. For the one audience this check
exists for it is the whole thing: a validation team is being asked to write that
sentence into an IQ/OQ protocol as a test case, and a test case needs an
execution record with a number on it. "Our analysis is deterministic" is not
evidence. ``sha256 = 9f2c…`` computed twice under two different interpreter hash
seeds, with the socket API raising, is.

So this module does the run:

* every check in :mod:`iaiops.core.verify.suite` over the pinned
  :mod:`iaiops.core.verify.dataset`, canonically encoded and digested;
* repeated in-process, and again in fresh subprocesses under two fixed and
  different ``PYTHONHASHSEED`` values — the arm that catches a set or dict
  iteration order leaking into a result, which a single run never can;
* with :func:`no_network` installed, so a computation that reached for a socket
  fails loudly instead of quietly succeeding on a machine that happened to be
  online;
* and with ``sys.modules`` checked afterwards for any model library, which is the
  runtime complement to the static import scan.

The record it returns separates ``result`` (reproducible, the part to sign) from
``context`` (when and where this run happened, expected to differ). Two records
of two good runs are NOT byte-identical, and someone will diff them — so the two
halves are named rather than mixed.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import socket
import subprocess  # nosec B404 — re-runs this interpreter on a fixed argv; see _subprocess_arm
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import asdict, is_dataclass
from datetime import UTC, date, datetime
from typing import Any

from iaiops.core.verify import dataset as ds
from iaiops.core.verify.suite import CHECKS

#: Import prefixes that would mean a model was loaded in this process. Kept in
#: step with ``tests/test_brain_is_llm_free.FORBIDDEN_PREFIXES`` — that test
#: proves nothing can import them, this proves nothing did.
MODEL_MODULE_PREFIXES: tuple[str, ...] = (
    "iaiops.core.llm",
    "openai",
    "anthropic",
    "ollama",
    "transformers",
    "llama_cpp",
    "langchain",
)

#: Fixed, different interpreter hash seeds for the subprocess arms. Two runs at
#: the same seed would agree even if a set's iteration order reached a result.
SUBPROCESS_SEEDS: tuple[str, ...] = ("0", "12345")

#: How many times the suite runs inside this process (catches stateful caches).
IN_PROCESS_RUNS = 2

#: Seconds a subprocess arm may take before it is treated as a failure.
SUBPROCESS_TIMEOUT_S = 120.0

VERDICT_REPRODUCIBLE = "reproducible"
VERDICT_NOT_REPRODUCIBLE = "not_reproducible"


class NetworkBlockedError(RuntimeError):
    """Raised when a computation under :func:`no_network` reaches for a socket."""


def _encodable(value: Any) -> Any:
    """Convert the few non-JSON types the brain returns; refuse the rest.

    Deliberately not ``default=str``: the repr of an unexpected object can carry
    its memory address, and an address makes the digest differ every run — which
    would read as "not reproducible" when the truth is "this encoder did not know
    what it was looking at". Naming the type is the more useful failure.
    """
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    raise TypeError(
        f"{type(value).__name__} has no canonical encoding, so its digest would "
        "not be meaningful. Convert it in the check that produced it."
    )


def canonical_bytes(value: Any) -> bytes:
    """The one canonical encoding a digest is taken over."""
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
        default=_encodable,
    ).encode("utf-8")


def digest(value: Any) -> str:
    """SHA-256 of the canonical encoding of ``value``."""
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


@contextmanager
def no_network() -> Iterator[None]:
    """Make every socket call raise for the duration of the block.

    Patches the module attributes rather than the OS, so it proves the code under
    it did not *try* — which is the claim being made. Restored unconditionally.
    """
    saved = {name: getattr(socket, name) for name in ("socket", "create_connection")}
    saved_getaddrinfo = socket.getaddrinfo

    def _refuse(*_args: Any, **_kwargs: Any) -> Any:
        raise NetworkBlockedError(
            "A computation in the determinism suite reached for the network. "
            "Every check must be pure — no device, no store, no host lookup."
        )

    socket.socket = _refuse  # type: ignore[assignment]
    socket.create_connection = _refuse  # type: ignore[assignment]
    socket.getaddrinfo = _refuse  # type: ignore[assignment]
    try:
        yield
    finally:
        socket.getaddrinfo = saved_getaddrinfo  # type: ignore[assignment]
        for name, value in saved.items():
            setattr(socket, name, value)


def dataset_digest() -> str:
    """Digest of the pinned input, so the record names what was computed over."""
    return digest(ds.dataset())


def run_suite() -> dict[str, str]:
    """Run every check once under :func:`no_network`; ``{check name: digest}``."""
    with no_network():
        return {check.name: digest(check.fn()) for check in CHECKS}


def suite_digest(per_check: dict[str, str]) -> str:
    """The single number that summarises a whole run."""
    return digest({"dataset": dataset_digest(), "checks": per_check})


def model_modules_loaded() -> list[str]:
    """Model libraries present in ``sys.modules`` right now."""
    return sorted(name for name in sys.modules if name.startswith(MODEL_MODULE_PREFIXES))


def _models_loaded_by(run: Callable[[], Any]) -> tuple[Any, list[str]]:
    """Run ``run``, and report which model modules IT caused to be imported.

    "No model library is loaded in this process" is the wrong question, and asking
    it was a bug: a long-lived MCP server legitimately has ``iaiops.core.llm``
    loaded, because the opt-in narration tool lives there. A check that called
    that not-reproducible would fire on exactly the deployment the claim is about,
    and the honest answer — the analysis path did not touch a model — would read
    as a failure.

    The question that means something is whether running the suite *pulled one
    in*. Modules already present are recorded rather than judged; the absolute
    form of the claim is made where it is true, in the fresh-interpreter arms.
    """
    before = set(model_modules_loaded())
    out = run()
    return out, sorted(set(model_modules_loaded()) - before)


def _arm_result(arm: str, per_check: dict[str, str]) -> dict[str, Any]:
    return {"arm": arm, "suite_digest": suite_digest(per_check), "checks": per_check}


def _subprocess_arm(seed: str) -> dict[str, Any]:
    """Run the suite in a fresh interpreter at a fixed hash seed."""
    env = {
        **os.environ,
        "PYTHONHASHSEED": seed,
        # The claim under test is that this needs nothing off-box; say so to
        # every part of the product that reads it.
        "IAIOPS_NO_EGRESS": "1",
    }
    arm = f"subprocess (PYTHONHASHSEED={seed}, IAIOPS_NO_EGRESS=1)"
    try:
        proc = subprocess.run(  # nosec B603 — fixed argv, shell=False, no interpolation
            [sys.executable, "-m", "iaiops.core.verify"],
            capture_output=True,
            text=True,
            timeout=SUBPROCESS_TIMEOUT_S,
            check=False,
            shell=False,
            env=env,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {"arm": arm, "error": f"could not start: {exc}"}
    if proc.returncode != 0:
        return {"arm": arm, "error": (proc.stderr or "").strip()[:500] or "non-zero exit"}
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        return {"arm": arm, "error": f"unreadable output: {exc}"}
    result = _arm_result(arm, payload["checks"])
    # A fresh interpreter imported only what the suite needed, so here the
    # absolute form of the claim is the one that holds.
    result["model_modules_loaded"] = list(payload.get("model_modules_loaded", []))
    return result


def run_determinism_check(*, subprocesses: bool = True) -> dict[str, Any]:
    """Run every arm and build the signable record."""
    already_loaded = model_modules_loaded()
    arms: list[dict[str, Any]] = []
    pulled_in: set[str] = set()
    for i in range(IN_PROCESS_RUNS):
        checks, newly = _models_loaded_by(run_suite)
        pulled_in.update(newly)
        arms.append(_arm_result(f"in-process #{i + 1}", checks))
    if subprocesses:
        arms.extend(_subprocess_arm(seed) for seed in SUBPROCESS_SEEDS)

    reference = arms[0]["suite_digest"]
    for arm in arms:
        arm["matches_first_arm"] = arm.get("suite_digest") == reference
    disagreeing = [a["arm"] for a in arms if not a["matches_first_arm"]]
    # A fresh interpreter that ended up holding a model library imported it to run
    # the suite — there is nothing else in that process.
    for arm in arms:
        pulled_in.update(arm.get("model_modules_loaded") or ())
    loaded_by_the_run = sorted(pulled_in)

    verdict = (
        VERDICT_REPRODUCIBLE
        if not disagreeing and not loaded_by_the_run
        else VERDICT_NOT_REPRODUCIBLE
    )
    return {
        "check": "determinism",
        "result": {
            "verdict": verdict,
            "suite_digest": reference,
            "dataset": {"name": ds.NAME, "revision": ds.REVISION, "digest": dataset_digest()},
            "checks": [
                {"name": c.name, "covers": c.covers, "digest": arms[0]["checks"][c.name]}
                for c in CHECKS
            ],
            "arms": [{k: v for k, v in arm.items() if k != "checks"} for arm in arms],
            "arms_disagreeing": disagreeing,
            "model_modules_loaded_by_the_run": loaded_by_the_run,
            "network": "blocked — socket/create_connection/getaddrinfo raise during every check",
        },
        "context": _context(already_loaded),
        "note": (
            "`result` is what a validation record signs: same input, same digests, "
            "every run. `context` records when and where this run happened and is "
            "expected to differ between runs — do not diff two whole records."
        ),
    }


def _context(already_loaded: list[str]) -> dict[str, Any]:
    from iaiops import __version__

    return {
        "iaiops_version": __version__,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "generated_at": datetime.now(tz=UTC).isoformat(timespec="seconds"),
        "in_process_runs": IN_PROCESS_RUNS,
        # Recorded, not judged: an MCP server process legitimately holds
        # ``iaiops.core.llm`` for the opt-in narration tool. What the verdict
        # turns on is whether the SUITE pulled one in — see _models_loaded_by.
        "model_modules_already_loaded": already_loaded,
        "subprocess_seeds": list(SUBPROCESS_SEEDS),
    }


__all__ = [
    "IN_PROCESS_RUNS",
    "MODEL_MODULE_PREFIXES",
    "SUBPROCESS_SEEDS",
    "VERDICT_NOT_REPRODUCIBLE",
    "VERDICT_REPRODUCIBLE",
    "NetworkBlockedError",
    "canonical_bytes",
    "dataset_digest",
    "digest",
    "model_modules_loaded",
    "no_network",
    "run_determinism_check",
    "run_suite",
    "suite_digest",
]
