"""Every fact carries where it came from, and the three sources never blur.

The knowledge base is what makes the product get better with use — relationships,
confirmed cases, learned weights. It is a RETENTION mechanism, not the entry
ticket (HLD D20): the product has to be useful on a site with an empty one.

Which makes provenance the load-bearing part rather than a nicety:

* ``declared``  — a human said so. Highest trust.
* ``derived``   — computed from data, and it must be able to show the evidence.
* ``suggested`` — a heuristic's guess. **Must not participate in reasoning until
  a human confirms it.**

A ``suggested`` fact used as if it were ``declared`` turns root-cause analysis
confidently wrong, which is worse than no answer at all — the same discipline
`readiness` holds in D16, applied to something that accumulates for years. Once
one unconfirmed guess is treated as fact, everything downstream inherits the
error and nothing marks where it entered.
"""

from __future__ import annotations

import json

import pytest

from iaiops.core.knowledge.model import (
    DECLARED,
    DERIVED,
    SUGGESTED,
    TRUST_ORDER,
    Fact,
    KnowledgeBase,
)

pytestmark = pytest.mark.unit


def fact(key="line1.upstream", value="mixer", source=DECLARED, **kw):
    return Fact(kind="relationship", key=key, value=value, source=source, **kw)


class TestProvenanceIsMandatory:
    def test_a_fact_cannot_exist_without_a_source(self):
        with pytest.raises(TypeError):
            Fact(kind="relationship", key="k", value="v")  # type: ignore[call-arg]

    def test_an_unknown_source_is_refused_with_the_vocabulary(self):
        with pytest.raises(ValueError) as excinfo:
            fact(source="probably")
        assert "declared" in str(excinfo.value)

    def test_trust_is_ordered_and_declared_wins(self):
        assert TRUST_ORDER.index(DECLARED) < TRUST_ORDER.index(DERIVED)
        assert TRUST_ORDER.index(DERIVED) < TRUST_ORDER.index(SUGGESTED)


class TestSuggestedCannotReason:
    def test_a_suggestion_is_not_usable(self):
        """The single rule the whole design rests on."""
        assert fact(source=SUGGESTED).usable is False

    def test_declared_and_derived_are_usable(self):
        assert fact(source=DECLARED).usable is True
        assert fact(source=DERIVED, evidence="co-occurred 9/10 stoppages").usable is True

    def test_confirming_a_suggestion_promotes_it_to_declared(self):
        """Promotion happens by a HUMAN confirming, and by nothing else."""
        confirmed = fact(source=SUGGESTED).confirmed_by("operator:zhang")
        assert confirmed.source == DECLARED
        assert confirmed.usable is True
        assert confirmed.confirmed_by_whom == "operator:zhang"

    def test_confirmation_keeps_what_was_originally_suggested(self):
        """So a later audit can ask "who agreed to this, and to what"."""
        confirmed = fact(source=SUGGESTED).confirmed_by("operator:zhang")
        assert confirmed.was == SUGGESTED

    def test_a_suggestion_cannot_promote_itself(self):
        with pytest.raises(ValueError, match="(?i)who"):
            fact(source=SUGGESTED).confirmed_by("")

    def test_only_usable_facts_are_returned_for_reasoning(self):
        kb = KnowledgeBase(site="plant-a").with_facts(
            fact(key="a", source=DECLARED),
            fact(key="b", source=DERIVED, evidence="from 400 samples"),
            fact(key="c", source=SUGGESTED),
        )
        assert {f.key for f in kb.usable()} == {"a", "b"}

    def test_suggestions_are_still_listed_for_a_human_to_review(self):
        """Withheld from reasoning, not hidden — they are the review queue."""
        kb = KnowledgeBase(site="plant-a").with_facts(fact(key="c", source=SUGGESTED))
        assert [f.key for f in kb.pending_review()] == ["c"]


class TestDerivedMustShowItsWork:
    def test_derived_without_evidence_is_refused(self):
        """A derived fact nobody can check is a suggestion wearing a better label."""
        with pytest.raises(ValueError, match="(?i)evidence"):
            fact(source=DERIVED)

    def test_declared_needs_no_evidence(self):
        """ "Because the process engineer said so" is the evidence."""
        assert fact(source=DECLARED).evidence == ""


class TestConflictsAreNotSilentlyResolved:
    def test_a_higher_trust_fact_supersedes_a_lower_one(self):
        kb = KnowledgeBase(site="p").with_facts(
            fact(key="line1.upstream", value="mixer", source=SUGGESTED),
            fact(key="line1.upstream", value="oven", source=DECLARED),
        )
        resolved = kb.get("line1.upstream")
        assert resolved.value == "oven" and resolved.source == DECLARED

    def test_two_declared_facts_that_disagree_are_reported_not_picked(self):
        """Two humans contradicting each other is not something to average."""
        kb = KnowledgeBase(site="p").with_facts(
            fact(key="line1.upstream", value="mixer", source=DECLARED),
            fact(key="line1.upstream", value="oven", source=DECLARED),
        )
        with pytest.raises(ValueError, match="(?i)conflict"):
            kb.get("line1.upstream")

    def test_the_conflict_names_both_values(self):
        kb = KnowledgeBase(site="p").with_facts(
            fact(key="k", value="mixer", source=DECLARED),
            fact(key="k", value="oven", source=DECLARED),
        )
        with pytest.raises(ValueError) as excinfo:
            kb.get("k")
        assert "mixer" in str(excinfo.value) and "oven" in str(excinfo.value)

    def test_conflicts_are_discoverable_without_asking_key_by_key(self):
        kb = KnowledgeBase(site="p").with_facts(
            fact(key="k", value="mixer", source=DECLARED),
            fact(key="k", value="oven", source=DECLARED),
        )
        assert kb.conflicts() == ("k",)


class TestItIsImmutable:
    def test_adding_a_fact_returns_a_new_base(self):
        original = KnowledgeBase(site="p")
        extended = original.with_facts(fact())
        assert len(original.facts) == 0 and len(extended.facts) == 1

    def test_confirming_returns_a_new_fact(self):
        suggestion = fact(source=SUGGESTED)
        suggestion.confirmed_by("someone")
        assert suggestion.source == SUGGESTED


class TestItRoundTrips:
    def test_a_base_serializes_and_loads_back_identically(self):
        kb = KnowledgeBase(site="plant-a").with_facts(
            fact(key="a", source=DECLARED),
            fact(key="b", source=DERIVED, evidence="400 samples"),
            fact(key="c", source=SUGGESTED),
        )
        again = KnowledgeBase.from_dict(json.loads(json.dumps(kb.as_dict())))
        assert [(f.key, f.source, f.evidence) for f in again.facts] == [
            (f.key, f.source, f.evidence) for f in kb.facts
        ]

    def test_provenance_survives_the_round_trip(self):
        """If a reload lost provenance, every stored suggestion would silently
        become usable — the failure this whole module exists to prevent."""
        kb = KnowledgeBase(site="p").with_facts(fact(key="c", source=SUGGESTED))
        again = KnowledgeBase.from_dict(kb.as_dict())
        assert again.facts[0].usable is False

    def test_a_corrupt_source_fails_the_load_rather_than_defaulting(self):
        blob = KnowledgeBase(site="p").with_facts(fact()).as_dict()
        blob["facts"][0]["source"] = "trustme"
        with pytest.raises(ValueError):
            KnowledgeBase.from_dict(blob)

    def test_an_absent_source_fails_too(self):
        """The realistic corruption — a truncated file, an older format, or a
        hand-edited one. Defaulting a missing provenance to anything usable
        would quietly promote every such fact, which is the failure this module
        exists to prevent arriving through the back door."""
        blob = KnowledgeBase(site="p").with_facts(fact()).as_dict()
        del blob["facts"][0]["source"]
        with pytest.raises(ValueError, match="(?i)provenance"):
            KnowledgeBase.from_dict(blob)

    def test_an_empty_source_fails_too(self):
        blob = KnowledgeBase(site="p").with_facts(fact()).as_dict()
        blob["facts"][0]["source"] = ""
        with pytest.raises(ValueError, match="(?i)provenance"):
            KnowledgeBase.from_dict(blob)


class TestPersistence:
    """The stored file is the accumulated opinion of a tool about someone's
    factory. If they cannot open it and see that a relationship is marked
    `suggested` rather than `declared`, the provenance guarantee only exists
    inside the process that wrote it."""

    def test_a_site_with_no_knowledge_yet_loads_empty_rather_than_failing(self, tmp_path):
        """D20 in code: the product works on a site that has accumulated
        nothing, so "no knowledge yet" is a starting state, not a fault."""
        from iaiops.core.knowledge.store import load

        kb = load("plant-a", base_dir=tmp_path)
        assert kb.site == "plant-a" and kb.facts == ()

    def test_a_saved_base_reloads_with_provenance_intact(self, tmp_path):
        from iaiops.core.knowledge.store import load, save

        save(
            KnowledgeBase(site="plant-a").with_facts(
                fact(key="a", source=DECLARED), fact(key="c", source=SUGGESTED)
            ),
            base_dir=tmp_path,
        )
        again = load("plant-a", base_dir=tmp_path)
        assert {f.key for f in again.usable()} == {"a"}
        assert [f.key for f in again.pending_review()] == ["c"]

    def test_the_file_is_owner_only(self, tmp_path):
        from iaiops.core.knowledge.store import save

        path = save(KnowledgeBase(site="p").with_facts(fact()), base_dir=tmp_path)
        assert oct(path.stat().st_mode)[-3:] == "600"

    def test_the_file_is_human_readable(self, tmp_path):
        """Someone must be able to open it and check what the tool believes."""
        from iaiops.core.knowledge.store import save

        path = save(
            KnowledgeBase(site="p").with_facts(fact(key="上游", source=SUGGESTED)),
            base_dir=tmp_path,
        )
        text = path.read_text("utf-8")
        assert '"source": "suggested"' in text
        assert "上游" in text, "non-ASCII keys must stay legible, not escape to \\uXXXX"

    def test_a_site_name_cannot_escape_the_directory(self, tmp_path):
        from iaiops.core.knowledge.store import save

        with pytest.raises(ValueError, match="(?i)site name"):
            save(KnowledgeBase(site="../../etc/passwd"), base_dir=tmp_path)

    def test_a_corrupt_file_is_reported_not_swallowed(self, tmp_path):
        from iaiops.core.knowledge.store import load, site_path

        path = site_path("p", tmp_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{not json", "utf-8")
        with pytest.raises(ValueError, match="(?i)unreadable"):
            load("p", base_dir=tmp_path)

    def test_a_write_never_leaves_a_half_file_behind(self, tmp_path):
        from iaiops.core.knowledge.store import save, site_path

        save(KnowledgeBase(site="p").with_facts(fact()), base_dir=tmp_path)
        leftovers = list(site_path("p", tmp_path).parent.glob("*.tmp"))
        assert leftovers == []
