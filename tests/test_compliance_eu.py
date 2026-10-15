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


def test_logging_row_admits_there_is_no_opt_out():
    """CRA I(2)(l) asks for an opt-out; the audit trail deliberately has none."""
    item = next(i for i in CRA_ITEMS if i["ref"].endswith("Part I(2)(l)"))
    assert item["coverage"] == "product_evidence"
    assert "no opt-out mechanism" in item["gap"].lower()


def test_no_vulnerability_disclosure_policy_is_admitted():
    for ref in ("Part II(5)", "Part II(6)"):
        item = next(i for i in CRA_ITEMS if i["ref"].endswith(ref))
        assert item["coverage"] == "gap", ref


def test_sbom_absence_is_admitted():
    item = next(i for i in CRA_ITEMS if i["ref"].endswith("Part II(1)"))
    assert item["gap"].lower().startswith("no sbom")


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
