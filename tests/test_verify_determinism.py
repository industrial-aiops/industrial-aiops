"""The executed half of "remove the model, block the network, the output is the same".

``tests/test_brain_is_llm_free.py`` scans the analysis layers and proves nothing
*can* reach a model. That proof is static, and the sentence people repeat about
this product — same data in, byte-identical output, no model, no network — was
written in its docstring and run nowhere. :mod:`iaiops.core.verify` runs it.

These tests guard the runner, not the numbers. A digest that moves because the
brain legitimately improved is not a regression, and pinning the suite digest
here would turn every honest change into a red build. What must not move is the
machinery: the arms have to actually disagree when something is nondeterministic,
the network really has to be blocked, the encoder must refuse what it cannot
canonicalize, and the reproducible half of the record must not contain the
timestamp of the run.

The dataset digest IS pinned — that input is meant to be frozen, and a change to
it without a REVISION bump would silently make every previously signed record
describe a different computation.
"""

from __future__ import annotations

import json
import socket
import sys

import pytest

from iaiops.core.verify import dataset as ds
from iaiops.core.verify import determinism as dt
from iaiops.core.verify.suite import CHECKS, Check, check_names

pytestmark = pytest.mark.unit

#: The pinned input. If you changed the dataset on purpose, bump
#: ``dataset.REVISION`` and update this — that pair is what lets a record signed
#: last quarter be read as "a different input", not as a failed comparison.
EXPECTED_DATASET_DIGEST = "a11f221a47fe40413542ca5553b90b10a5b04d1e8deaa32cbe84d1495b222bc6"
EXPECTED_DATASET_REVISION = 1

#: Analyses the record must keep covering. Adding a check is free; removing one
#: narrows the guarantee without changing a single line of prose about it.
REQUIRED_CHECKS = frozenset(
    {
        "availability",
        "production",
        "losses",
        "alarm_load",
        "control_chart",
        "conservative_baseline",
        "root_cause",
    }
)


# ─── the pinned input ────────────────────────────────────────────────────────


def test_the_reference_dataset_is_pinned():
    assert ds.REVISION == EXPECTED_DATASET_REVISION
    assert dt.dataset_digest() == EXPECTED_DATASET_DIGEST, (
        "The reference dataset changed. If that was deliberate, bump "
        "dataset.REVISION and update EXPECTED_DATASET_DIGEST here — every record "
        "signed against the old revision computed over different input."
    )


def test_the_dataset_builds_without_a_clock_or_a_file():
    """Two constructions in the same process must be identical."""
    assert dt.canonical_bytes(ds.dataset()) == dt.canonical_bytes(ds.dataset())


# ─── the suite ───────────────────────────────────────────────────────────────


def test_the_suite_still_covers_every_required_analysis():
    missing = REQUIRED_CHECKS - set(check_names())
    assert not missing, (
        f"the determinism record would silently stop covering {sorted(missing)} — "
        "narrowing the guarantee is the one change nobody notices"
    )


def test_check_names_are_unique():
    names = check_names()
    assert len(names) == len(set(names))


def test_every_check_produces_a_substantive_result():
    """A check that quietly started refusing would still hash — and prove nothing."""
    for check in CHECKS:
        out = check.fn()
        assert isinstance(out, dict) and out, f"{check.name} produced nothing"
        assert not out.get("error"), f"{check.name} errored: {out.get('error')}"


def test_running_the_suite_twice_gives_the_same_digests():
    assert dt.run_suite() == dt.run_suite()


# ─── the guard must fire ─────────────────────────────────────────────────────


class _Counter:
    """A stand-in for a computation whose answer drifts between runs."""

    def __init__(self) -> None:
        self.n = 0

    def __call__(self) -> dict:
        self.n += 1
        return {"answer": self.n}


def test_a_nondeterministic_check_is_caught(monkeypatch):
    """The whole point: if a result drifts, the verdict must say so."""
    drifting = Check("drifting", "a computation that does not settle", _Counter())
    monkeypatch.setattr(dt, "CHECKS", (drifting,))

    record = dt.run_determinism_check(subprocesses=False)

    assert record["result"]["verdict"] == dt.VERDICT_NOT_REPRODUCIBLE
    assert record["result"]["arms_disagreeing"], "the arms agreed on a drifting check"


def test_a_model_module_pulled_in_by_the_run_is_caught(monkeypatch):
    """The runtime complement to the static import scan."""

    def _imports_a_model() -> dict:
        sys.modules["anthropic"] = object()
        return {"ok": True}

    monkeypatch.setattr(
        dt, "CHECKS", (Check("greedy", "a check that reaches for a model", _imports_a_model),)
    )
    try:
        record = dt.run_determinism_check(subprocesses=False)
    finally:
        sys.modules.pop("anthropic", None)

    assert record["result"]["verdict"] == dt.VERDICT_NOT_REPRODUCIBLE
    assert "anthropic" in record["result"]["model_modules_loaded_by_the_run"]


def test_a_model_module_already_loaded_does_not_condemn_the_run(monkeypatch):
    """The bug this replaced: asking the wrong question fires on the real deployment.

    An MCP server process legitimately holds ``iaiops.core.llm`` — the opt-in
    narration tool lives there. A check that reported "not reproducible" because
    a model library existed *somewhere in the process* would fail on exactly the
    deployment the claim is about, and would say the analysis touched a model
    when it had not. Only what the suite itself pulls in can decide the verdict.
    """
    monkeypatch.setitem(sys.modules, "openai", object())

    record = dt.run_determinism_check(subprocesses=False)

    assert record["result"]["verdict"] == dt.VERDICT_REPRODUCIBLE
    assert record["result"]["model_modules_loaded_by_the_run"] == []
    # Recorded rather than hidden — a reader can see what was in the process.
    assert "openai" in record["context"]["model_modules_already_loaded"]


def test_a_clean_run_is_reproducible():
    record = dt.run_determinism_check(subprocesses=False)
    assert record["result"]["verdict"] == dt.VERDICT_REPRODUCIBLE
    assert record["result"]["model_modules_loaded_by_the_run"] == []
    assert all(arm["matches_first_arm"] for arm in record["result"]["arms"])


def test_a_model_loaded_in_a_fresh_interpreter_condemns_the_run(monkeypatch):
    """The subprocess arms' absolute claim has to reach the verdict, not just the record.

    Reporting a fact next to a verdict that ignores it is the shape of a green
    check that guarantees nothing — caught by mutation: deleting the line that
    folds the subprocess claim into the verdict left every test passing.
    """

    def _fake_arm(seed: str) -> dict:
        checks = dt.run_suite()
        return {
            "arm": f"subprocess (PYTHONHASHSEED={seed}, IAIOPS_NO_EGRESS=1)",
            "suite_digest": dt.suite_digest(checks),
            "checks": checks,
            "model_modules_loaded": ["transformers"],
        }

    monkeypatch.setattr(dt, "_subprocess_arm", _fake_arm)
    record = dt.run_determinism_check(subprocesses=True)

    assert record["result"]["verdict"] == dt.VERDICT_NOT_REPRODUCIBLE
    assert "transformers" in record["result"]["model_modules_loaded_by_the_run"]


def test_the_fresh_interpreter_arms_carry_the_absolute_claim():
    """In a subprocess nothing else ran, so "no model loaded at all" is meaningful."""
    record = dt.run_determinism_check(subprocesses=True)
    subs = [a for a in record["result"]["arms"] if a["arm"].startswith("subprocess")]
    assert subs
    for arm in subs:
        assert arm.get("model_modules_loaded") == [], (
            f"{arm['arm']} ended up holding {arm.get('model_modules_loaded')} — "
            "a fresh interpreter running only the suite must hold none"
        )


# ─── the network really is blocked ───────────────────────────────────────────


def test_no_network_blocks_every_socket_entry_point():
    with dt.no_network():
        for call in (
            lambda: socket.socket(),
            lambda: socket.create_connection(("127.0.0.1", 9)),
            lambda: socket.getaddrinfo("localhost", 80),
        ):
            with pytest.raises(dt.NetworkBlockedError):
                call()


def test_no_network_restores_the_real_socket_api():
    original = socket.socket
    with dt.no_network():
        pass
    assert socket.socket is original


def test_no_network_restores_even_when_the_block_raises():
    original = socket.getaddrinfo
    with pytest.raises(RuntimeError), dt.no_network():
        raise RuntimeError("boom")
    assert socket.getaddrinfo is original


def test_the_suite_runs_with_the_network_blocked():
    """Not a claim about the checks — the runner installs the block itself."""
    seen: list[bool] = []

    def _peek() -> dict:
        seen.append(socket.socket is not _real)
        return {"ok": True}

    _real = socket.socket
    import iaiops.core.verify.determinism as module

    original_checks = module.CHECKS
    module.CHECKS = (Check("peek", "observes the network block", _peek),)
    try:
        module.run_suite()
    finally:
        module.CHECKS = original_checks
    assert seen == [True], "run_suite did not install no_network() around the checks"


# ─── the canonical encoding ──────────────────────────────────────────────────


def test_canonical_encoding_ignores_key_insertion_order():
    assert dt.canonical_bytes({"b": 1, "a": 2}) == dt.canonical_bytes({"a": 2, "b": 1})


def test_canonical_encoding_refuses_a_type_it_cannot_represent():
    """``default=str`` would have hashed a memory address and blamed the product."""
    with pytest.raises(TypeError, match="no canonical encoding"):
        dt.canonical_bytes({"thing": object()})


def test_canonical_encoding_refuses_nan():
    """NaN is not JSON, and a digest over ``NaN`` would compare equal to nothing."""
    with pytest.raises(ValueError):
        dt.canonical_bytes({"x": float("nan")})


# ─── the record ──────────────────────────────────────────────────────────────


def test_the_record_keeps_the_run_context_out_of_the_signed_result():
    """Someone will diff two records. The halves have to be separable."""
    record = dt.run_determinism_check(subprocesses=False)
    result_text = dt.canonical_bytes(record["result"]).decode("utf-8")

    assert "generated_at" in record["context"]
    assert "generated_at" not in result_text
    assert record["context"]["generated_at"] not in result_text
    assert record["context"]["platform"] not in result_text


def test_the_record_names_every_check_it_covers():
    record = dt.run_determinism_check(subprocesses=False)
    named = {c["name"] for c in record["result"]["checks"]}
    assert named == set(check_names())
    assert all(c["covers"] for c in record["result"]["checks"])


def test_the_record_is_json_serialisable():
    record = dt.run_determinism_check(subprocesses=False)
    assert json.loads(json.dumps(record))


# ─── the fresh-interpreter arms ──────────────────────────────────────────────


def test_the_subprocess_arms_agree_with_this_process():
    """The arm that catches iteration order leaking into a result."""
    record = dt.run_determinism_check(subprocesses=True)
    arms = record["result"]["arms"]

    subprocess_arms = [a for a in arms if a["arm"].startswith("subprocess")]
    assert len(subprocess_arms) == len(dt.SUBPROCESS_SEEDS)
    for arm in subprocess_arms:
        assert "error" not in arm, f"{arm['arm']} failed: {arm.get('error')}"
        assert arm["matches_first_arm"], f"{arm['arm']} disagreed"


def test_the_subprocess_seeds_are_actually_different():
    """Two runs at the same hash seed would agree for the wrong reason."""
    assert len(set(dt.SUBPROCESS_SEEDS)) == len(dt.SUBPROCESS_SEEDS) >= 2
