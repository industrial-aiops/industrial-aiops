"""The GxP column, and the sentence it is not allowed to become.

The pharma buyer is the most sensitive audience there is to a compliance claim:
"we comply with Part 11", said by a vendor, gets the vendor removed from the
evaluation. Compliance under Annex 11 / Part 11 is a property of the customer's
*validated system*, never of a component inside it. So the mapping may say which
clause a piece of evidence is relevant to, and must stop there.
"""

from __future__ import annotations

import json

import pytest

from iaiops.core.brain.compliance import CONTROLS, GXP_DISCLAIMER, compliance_frameworks

pytestmark = pytest.mark.unit


def test_gxp_is_a_declared_framework():
    ids = [f["id"] for f in compliance_frameworks()["frameworks"]]
    assert "gxp" in ids
    assert len(ids) == len(set(ids))


def test_every_pillar_carries_a_gxp_clause():
    """A 待核实 here would be honest but useless — the mapping is the deliverable."""
    rows = compliance_frameworks()["crosswalk"]
    assert len(rows) == len(CONTROLS)
    missing = [r["pillar"] for r in rows if r["gxp"] == "待核实"]
    assert not missing, f"pillars with no GxP mapping: {missing}"


def test_the_clauses_name_real_documents():
    text = json.dumps(compliance_frameworks()["crosswalk"], ensure_ascii=False)
    for token in ("Annex 11", "Part 11", "ALCOA+", "Annex 22"):
        assert token in text, f"the GxP column never mentions {token}"


def test_the_existing_columns_are_untouched():
    """Adding a column must not disturb the three that shipped."""
    rows = compliance_frameworks()["crosswalk"]
    for row in rows:
        for key in ("gjzn", "dengbao", "iec62443", "iaiops_status"):
            assert row.get(key), f"{key} went missing from {row['pillar']}"


# ─── the restraint ───────────────────────────────────────────────────────────


def test_the_disclaimer_is_carried_with_the_table():
    out = compliance_frameworks()
    assert out["gxp_disclaimer"] == GXP_DISCLAIMER
    assert "不是符合性声明" in GXP_DISCLAIMER
    assert "由贵厂 QA 判定" in GXP_DISCLAIMER
    assert "不能替代 CSV" in GXP_DISCLAIMER


def test_nothing_claims_compliance_or_certification():
    out = compliance_frameworks()
    table = json.dumps(out["crosswalk"], ensure_ascii=False)
    for claim in ("符合 Part 11", "compliant with", "certified", "已认证", "通过认证"):
        assert claim not in table, f"the crosswalk claims {claim!r}"
    assert "非认证" in out["note"]


def test_the_note_still_says_the_whole_table_is_not_a_certification():
    assert "非认证" in compliance_frameworks()["note"]
