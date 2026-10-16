"""NIS2 Art. 21 and CRA Annex I — the crosswalks, and what they may not say.

The two European texts oblige different parties, and neither obliges this
product: NIS2 obliges *entities* (the plant operator), the CRA obliges the
*manufacturer* of a product with digital elements. So a row may name the
iaiops mechanism whose output is relevant evidence for a measure, and must stop
there. The recurring defect in this repository is the flattering one — a row
that stretches a mechanism to cover a measure it does not touch — so most of
these tests pin the restraint, not the presence.
"""

from __future__ import annotations

import importlib
import json
import pathlib

import pytest

from iaiops.core.brain.compliance import CONTROLS, compliance_frameworks, compliance_mapping
from iaiops.core.brain.compliance_eu import (
    COVERAGE,
    CRA_ITEMS,
    EU_DISCLAIMER,
    MECHANISMS,
    NIS2_ITEMS,
    compliance_eu,
)

pytestmark = pytest.mark.unit

REPO = pathlib.Path(__file__).resolve().parent.parent
PILLARS = {c["pillar"] for c in CONTROLS}
ALL_ITEMS = NIS2_ITEMS + CRA_ITEMS


# ─── the texts are transcribed whole, in order ───────────────────────────────


def test_nis2_lists_article_21_2_a_to_j_in_order():
    refs = [i["ref"] for i in NIS2_ITEMS]
    assert refs == [f"NIS2 Art. 21(2)({letter})" for letter in "abcdefghij"]


def test_cra_lists_annex_i_part_i_and_part_ii_in_order():
    refs = [i["ref"] for i in CRA_ITEMS]
    part1 = ["CRA Annex I Part I(1)"] + [f"CRA Annex I Part I(2)({c})" for c in "abcdefghijklm"]
    part2 = [f"CRA Annex I Part II({n})" for n in range(1, 9)]
    assert refs == part1 + part2


def test_ids_are_unique_and_stable():
    ids = [i["id"] for i in ALL_ITEMS]
    assert len(ids) == len(set(ids))
    assert NIS2_ITEMS[0]["id"] == "nis2-21-2-a"
    assert CRA_ITEMS[0]["id"] == "cra-i-1-1"
    assert CRA_ITEMS[-1]["id"] == "cra-i-2-8"


def test_every_item_has_the_full_shape():
    for item in ALL_ITEMS:
        for key in ("id", "ref", "measure", "coverage", "iaiops", "gap", "pillars", "mechanisms"):
            assert key in item, f"{item['id']} lacks {key}"
        assert item["coverage"] in COVERAGE, item["id"]
        assert item["measure"].strip()
        assert item["iaiops"].strip()


# ─── the restraint ───────────────────────────────────────────────────────────


@pytest.mark.parametrize("letter", ["b", "c", "d", "g"])
def test_organisational_nis2_measures_say_so_and_cite_nothing(letter):
    """Incident handling, continuity, supply chain, training: the plant's job."""
    item = next(i for i in NIS2_ITEMS if i["ref"].endswith(f"({letter})"))
    assert item["coverage"] == "organisational"
    assert "product provides no evidence" in item["iaiops"]


def test_organisational_rows_carry_no_mechanism_and_no_pillar():
    """An organisational row with a mechanism attached is a stretched claim.

    E9 attaches site evidence through ``pillars``; a pillar on an organisational
    row would print runtime evidence under a measure the product never touches.
    """
    for item in ALL_ITEMS:
        if item["coverage"] == "organisational":
            assert item["mechanisms"] == (), item["id"]
            assert item["pillars"] == (), item["id"]


def test_product_evidence_rows_name_a_mechanism_and_what_is_left():
    for item in ALL_ITEMS:
        if item["coverage"] == "product_evidence":
            assert item["mechanisms"], f"{item['id']} claims evidence from nothing"
            assert item["gap"].strip(), f"{item['id']} claims evidence with no remainder"


def test_gap_rows_cite_no_mechanism():
    """'gap' means the product could speak to it and does not — so nothing to cite."""
    for item in ALL_ITEMS:
        if item["coverage"] == "gap":
            assert item["mechanisms"] == (), item["id"]
            assert item["gap"].strip(), item["id"]


def test_human_resources_security_is_named_organisational_inside_21_2_i():
    item = next(i for i in NIS2_ITEMS if i["ref"].endswith("(i)"))
    assert "human resources security" in item["gap"].lower()
    assert "organisational" in item["gap"].lower()


def test_no_mfa_is_said_plainly():
    item = next(i for i in NIS2_ITEMS if i["ref"].endswith("(j)"))
    assert item["coverage"] == "gap"
    assert "multi-factor" in item["gap"].lower()


def test_logging_row_says_the_opt_out_is_narrow():
    """CRA I(2)(l) asks for an opt-out; ours covers reads only, and says so."""
    item = next(i for i in CRA_ITEMS if i["ref"].endswith("Part I(2)(l)"))
    assert item["coverage"] == "product_evidence"
    assert "audit_opt_out" in item["mechanisms"]
    assert "cannot be opted out" in item["gap"] and "待核实" in item["gap"]


def test_the_disclosure_policy_is_cited_and_says_it_is_untested():
    """II(5)/(6) rest on SECURITY.md — which must exist, and be called unexercised."""
    assert (REPO / "SECURITY.md").is_file()
    for ref in ("Part II(4)", "Part II(5)", "Part II(6)"):
        item = next(i for i in CRA_ITEMS if i["ref"].endswith(ref))
        assert "security_policy" in item["mechanisms"], ref
    assert "not yet exercised" in MECHANISMS["security_policy"]["fact"]


def test_sbom_row_says_what_the_sbom_describes():
    item = next(i for i in CRA_ITEMS if i["ref"].endswith("Part II(1)"))
    assert "sbom" in item["mechanisms"]
    assert "not an individual install" in item["gap"]
    assert "待核实" in item["gap"]


def test_the_dependency_scan_has_no_silent_ignores():
    """Every ignored advisory needs a reason written next to it."""
    lines = (REPO / ".github/pip-audit-ignore.txt").read_text(encoding="utf-8").splitlines()
    for line in lines:
        if line.strip() and not line.lstrip().startswith("#"):
            advisory, _, reason = line.strip().partition(" ")
            assert reason.strip(), f"{advisory} is ignored without a reason"


def test_nothing_claims_compliance_or_certification():
    text = json.dumps(ALL_ITEMS, ensure_ascii=False).lower()
    for claim in (
        "compliant",
        "complies",
        "certified",
        "conformity is",
        "satisfies",
        "fulfils",
        "meets the requirement",
        "已认证",
        "通过认证",
    ):
        assert claim not in text, f"the EU crosswalk says {claim!r}"


def test_disclaimer_names_who_each_text_obliges():
    assert "entities" in EU_DISCLAIMER and "NIS2" in EU_DISCLAIMER
    assert "manufacturer" in EU_DISCLAIMER and "CRA" in EU_DISCLAIMER
    assert "not a certification" in EU_DISCLAIMER.lower()
    assert "not legal advice" in EU_DISCLAIMER.lower()


def test_cra_scope_for_this_product_is_left_open():
    """Whether free MIT software is in CRA scope is not ours to settle here."""
    out = compliance_eu("cra")
    assert "待核实" in out["scope"]


# ─── every cited mechanism exists in code ────────────────────────────────────


def _resolve(anchor: str) -> bool:
    kind, _, target = anchor.partition(":")
    if kind == "py":
        module, _, attr = target.partition(":")
        obj = importlib.import_module(module)
        for part in attr.split("."):
            obj = getattr(obj, part)
        return obj is not None
    if kind == "file":
        path, _, needle = target.partition("#")
        file = REPO / path
        return file.is_file() and (not needle or needle in file.read_text(encoding="utf-8"))
    raise AssertionError(f"unknown anchor kind in {anchor!r}")


def test_every_cited_mechanism_is_registered():
    cited = {m for item in ALL_ITEMS for m in item["mechanisms"]}
    assert cited <= set(MECHANISMS), cited - set(MECHANISMS)


@pytest.mark.parametrize("mechanism_id", sorted(MECHANISMS))
def test_every_mechanism_anchor_resolves(mechanism_id):
    """A mechanism the code does not contain is the stretch this file exists to stop."""
    mech = MECHANISMS[mechanism_id]
    assert mech["anchors"], mechanism_id
    for anchor in mech["anchors"]:
        assert _resolve(anchor), f"{mechanism_id}: {anchor} does not resolve"


def test_a_dangling_anchor_would_be_caught():
    """Mutation check on the guard itself."""
    with pytest.raises(AttributeError):
        _resolve("py:iaiops.core.governance.audit:AuditEngine.no_such_method")
    assert not _resolve("file:uv.lock#no-such-token-anywhere-in-the-lockfile")


def test_pillars_are_exact_control_strings():
    """E1/E9 key site evidence by these strings; a near-miss silently drops evidence."""
    for item in ALL_ITEMS:
        for pillar in item["pillars"]:
            assert pillar in PILLARS, f"{item['id']}: {pillar!r}"


# ─── selection and the shared crosswalk ──────────────────────────────────────


def test_compliance_eu_selects_one_framework():
    nis2 = compliance_eu("nis2")
    assert nis2["framework"]["id"] == "nis2"
    assert [i["id"] for i in nis2["items"]] == [i["id"] for i in NIS2_ITEMS]
    assert nis2["item_count"] == len(NIS2_ITEMS)
    assert sum(nis2["coverage_summary"].values()) == len(NIS2_ITEMS)
    assert nis2["disclaimer"] == EU_DISCLAIMER
    cra = compliance_eu("CRA")
    assert cra["framework"]["id"] == "cra"
    assert cra["item_count"] == len(CRA_ITEMS)


def test_compliance_eu_items_carry_the_mechanism_detail():
    item = compliance_eu("nis2")["items"][4]
    assert item["ref"].endswith("(e)")
    assert all("name" in m and "anchors" in m for m in item["mechanism_detail"])


def test_compliance_eu_rejects_unknown_framework():
    with pytest.raises(ValueError, match="nis2"):
        compliance_eu("gdpr")


def test_frameworks_declares_nis2_and_cra():
    ids = [f["id"] for f in compliance_frameworks()["frameworks"]]
    assert "nis2" in ids and "cra" in ids
    assert len(ids) == len(set(ids))


def test_pillar_crosswalk_columns_are_derived_from_the_items():
    """The per-pillar column is a reverse index, never a second hand-typed table."""
    for row in compliance_frameworks()["crosswalk"]:
        for fw, items in (("nis2", NIS2_ITEMS), ("cra", CRA_ITEMS)):
            expected = [i["ref"] for i in items if row["pillar"] in i["pillars"]]
            assert row[f"{fw}_refs"] == expected, (row["pillar"], fw)


def test_mapping_crosswalk_carries_the_eu_refs_too():
    for control in compliance_mapping()["controls"]:
        assert "nis2" in control["crosswalk"] and "cra" in control["crosswalk"]


def test_compliance_frameworks_framework_parameter():
    assert compliance_frameworks("nis2")["framework"]["id"] == "nis2"
    assert compliance_frameworks("cra")["item_count"] == len(CRA_ITEMS)
    assert "crosswalk" in compliance_frameworks(None)
    with pytest.raises(ValueError):
        compliance_frameworks("dengbao")


# ─── the facts, pinned to the behaviour they describe ────────────────────────
# An anchor proves a name exists; these prove the sentence about it is still
# true. Each one fails the day the default it describes is flipped.


def test_partial_evidence_rows_name_a_mechanism_and_what_is_missing():
    for item in ALL_ITEMS:
        if item["coverage"] == "partial_evidence":
            assert item["mechanisms"], item["id"]
            assert item["gap"].strip(), item["id"]


@pytest.mark.parametrize(
    "ref",
    [
        "CRA Annex I Part I(2)(c)",  # publishing releases is not an update mechanism
        "CRA Annex I Part II(2)",  # no remediation process
        "CRA Annex I Part II(7)",  # wheels unsigned
    ],
)
def test_rows_missing_their_central_requirement_are_not_full_evidence(ref):
    item = next(i for i in CRA_ITEMS if i["ref"] == ref)
    assert item["coverage"] != "product_evidence", ref


def test_the_removal_row_admits_it_does_not_shred():
    item = next(i for i in CRA_ITEMS if i["ref"].endswith("Part I(2)(m)"))
    assert "reset_command" in item["mechanisms"]
    assert "not shredded" in item["gap"]
    from iaiops.core.runtime.reset import ERASE_NOTE

    assert "not shredded" in ERASE_NOTE


def test_reset_is_not_an_mcp_tool(full_tool_registry):
    """An agent that can erase the audit trail is what the trail exists to prevent."""
    assert not [n for n in full_tool_registry if "reset" in n.lower()]


def test_the_crosswalk_is_not_cited_as_evidence_for_itself():
    assert "self_assessment" not in MECHANISMS


def test_mechanisms_are_read_only():
    with pytest.raises(TypeError):
        MECHANISMS["invented"] = {}  # type: ignore[index]


def test_every_mcp_write_tool_defaults_to_dry_run(full_tool_registry):
    import inspect

    high = {
        name: tool.fn
        for name, tool in full_tool_registry.items()
        if getattr(tool.fn, "_risk_level", "low") in ("high", "critical")
    }
    assert high
    for name, fn in high.items():
        params = inspect.signature(fn).parameters
        assert "dry_run" in params, f"{name} has no dry_run"
        assert params["dry_run"].default is True, f"{name} does not preview by default"


def test_audit_fail_open_is_what_the_fact_says():
    from iaiops.core.governance import decorators

    assert tuple(decorators._FAIL_CLOSED_RISK) == ("high", "critical")
    assert "unaudited" in MECHANISMS["audit_trail"]["fact"]


def test_rotation_numbers_match_the_fact():
    from iaiops.core.governance import audit

    assert audit._MAX_DB_SIZE_BYTES == 100 * 1024 * 1024
    assert audit._MAX_ARCHIVES == 5
    fact = MECHANISMS["audit_rotation"]["fact"]
    assert "100 MB" in fact and "5 most recent" in fact and "deleted" in fact


def test_breaker_numbers_and_opt_in_ceilings_match_the_fact(monkeypatch):
    from iaiops.core.governance import budget

    for env in ("OPCUA_MAX_TOOL_CALLS", "OPCUA_MAX_TOOL_SECONDS"):
        monkeypatch.delenv(env, raising=False)
    assert budget._DEFAULT_RUNAWAY_MAX == 25
    assert budget._DEFAULT_RUNAWAY_WINDOW_SEC == 120
    assert budget._env_int("OPCUA_MAX_TOOL_CALLS", None) is None  # off by default
    fact = MECHANISMS["budget_breaker"]["fact"]
    assert "25 times in 120 s" in fact and "off by default" in fact


def test_transport_defaults_match_the_fact(monkeypatch):
    from mcp_server.transport import TRANSPORT_ENV, resolve_transport

    monkeypatch.delenv(TRANSPORT_ENV, raising=False)
    assert resolve_transport(None) == "stdio"
    dockerfile = (REPO / "deploy/margo/Dockerfile").read_text(encoding="utf-8")
    assert "IAIOPS_MCP_TRANSPORT=stdio" in dockerfile
    package = (REPO / "deploy/margo/package.compose.yaml").read_text(encoding="utf-8")
    assert "IAIOPS_MCP_TRANSPORT:-streamable-http" in package
    assert "streamable-http on 0.0.0.0" in MECHANISMS["mcp_profiles"]["fact"]
    assert "IAIOPS_MCP_TOKEN:?" in package, "the package must refuse to deploy without a token"


def test_the_token_fact_matches_the_refusal():
    from mcp_server.http_auth import MIN_TOKEN_LENGTH, require_token_for_bind
    from mcp_server.transport import TransportError

    with pytest.raises(TransportError):
        require_token_for_bind("0.0.0.0", None)
    assert f"at least {MIN_TOKEN_LENGTH} characters" in MECHANISMS["http_bearer_auth"]["fact"]


def test_plaintext_env_fallback_is_admitted():
    from iaiops.core.runtime import config

    assert config.ENV_FILE.name == ".env"
    assert "plaintext" in MECHANISMS["secret_store"]["fact"]


def test_pypi_signing_is_not_claimed_before_a_release_carries_it():
    """The workflow exists; a signed wheel on PyPI does not yet. Say both."""
    fact = MECHANISMS["signed_images"]["fact"]
    assert "Trusted Publishing" in fact
    assert "no signature or attestation" in fact and "待核实" in fact


def test_cra_wording_was_checked_against_the_regulation_text():
    out = compliance_eu("cra")
    assert "02024R2847" in out["source"]
    assert "Art. 3(22)" in out["scope"] and "NOT yet assessed" in out["scope"]


_FLATTERY = (
    "compliant",
    "complies",
    "certified",
    "satisfies",
    "fulfils",
    "meets",
    "ensures",
    "guarantee",
    "fully covered",
    "addressed",
    "cannot ship",
    "已认证",
    "通过认证",
)


def _our_words() -> str:
    """Everything we wrote ourselves — the measure text paraphrases the law."""
    rows = [{k: v for k, v in i.items() if k != "measure"} for i in ALL_ITEMS]
    meta = [compliance_eu(fw)["framework"] for fw in ("nis2", "cra")]
    facts = [dict(m) for m in MECHANISMS.values()]
    return json.dumps([rows, meta, facts], ensure_ascii=False).lower()


@pytest.mark.parametrize("word", _FLATTERY)
def test_no_flattering_word_anywhere_we_wrote(word):
    assert word not in _our_words(), word
