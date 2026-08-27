"""A mountable fault-mechanism library — and the four things it may never do.

HLD §13.8 and §12. Until now step 07 reported `expressible=False`: fault
mechanisms were hardcoded constants and there was no way to mount anything. This
is the slot, and its shape comes from what the field actually standardised
rather than from what would be easy.

**ISO 14224's three levels, kept separate.** The standard distinguishes the
failure MODE (the observed effect — "reading frozen"), the failure MECHANISM
(the physical process — "transmitter drift") and the failure CAUSE (the root
condition — "wrong material"). This repo's seven `CAUSE_KEYWORDS` collapse all
three into one word. A library entry keeps them apart, because they answer
different questions: the mode is what you SAW, the mechanism is what to go and
check, the cause is what to fix.

**Seven top-level causes is the right number, and the library does not add to
it.** Practitioner consensus is blunt: past roughly forty codes, two operators
stop picking the same one and the data degrades. So an entry *attaches to* an
existing taxonomy cause; it never invents one.

The four refusals, in order of how much damage each would do:

1. **Silence is not agreement.** A library with nothing to say about a candidate
   must produce "nothing known", never "no objection". This is the flattering
   reading and the one that would make the whole step worse than useless.
2. **It may exclude, never confirm** (D29). Applicability constraints can rule a
   candidate out — that is the strong, useful move (D28). Raising one to
   `confirmed` must still come from outside the ranking: a measurement, a
   reproduction, or a person.
3. **An entry says where it came from.** A mechanism with no source is
   indistinguishable from a guess a year later.
4. **It never invents a cause** outside the taxonomy the learner speaks.
"""

from __future__ import annotations

import pytest
import yaml

from iaiops.core.knowledge.mechanisms import (
    check_candidate,
    load_library,
    mount_library,
    mounted_mechanisms,
)

pytestmark = pytest.mark.unit

GOOD = {
    "version": 1,
    "source": "Pump vendor manual rev C (2024)",
    "mechanisms": [
        {
            "cause": "sensor_fault",
            "mechanism": "transmitter drift",
            "mode": "reading frozen at the last good value",
            "applies_to": {"protocols": ["modbus"]},
            "excluded_when": ["the same value read from a second source agrees"],
            "confirm_by": ["loop check of the transmitter and its wiring"],
        },
        {
            "cause": "comms_loss",
            "mechanism": "media converter power loss",
            "mode": "all tags stale together",
            "applies_to": {"protocols": ["modbus", "opcua"]},
        },
    ],
}


def _write(tmp_path, doc, name="lib.yaml"):
    path = tmp_path / name
    path.write_text(yaml.safe_dump(doc), encoding="utf-8")
    return path


class TestMountingALibrary:
    def test_a_valid_library_mounts(self, tmp_path):
        result = mount_library(_write(tmp_path, GOOD), by="wei", base_dir=tmp_path)
        assert result["mounted"] == 2

    def test_the_entries_come_back(self, tmp_path):
        mount_library(_write(tmp_path, GOOD), by="wei", base_dir=tmp_path)
        assert {m.cause for m in mounted_mechanisms(base_dir=tmp_path)} == {
            "sensor_fault",
            "comms_loss",
        }

    def test_iso_14224_levels_stay_separate(self, tmp_path):
        """Mode, mechanism and cause answer different questions: what you saw,
        what to go and check, what to fix. Merged, the entry can only repeat the
        ranking back."""
        mount_library(_write(tmp_path, GOOD), by="wei", base_dir=tmp_path)
        entry = next(m for m in mounted_mechanisms(base_dir=tmp_path) if m.cause == "sensor_fault")
        assert entry.mechanism == "transmitter drift"
        assert entry.mode == "reading frozen at the last good value"
        assert entry.cause == "sensor_fault"

    def test_it_records_where_the_knowledge_came_from(self, tmp_path):
        mount_library(_write(tmp_path, GOOD), by="wei", base_dir=tmp_path)
        entry = mounted_mechanisms(base_dir=tmp_path)[0]
        assert entry.source == "Pump vendor manual rev C (2024)"
        assert entry.by == "wei"

    def test_a_library_with_no_source_is_refused(self, tmp_path):
        """A mechanism with no source is indistinguishable from a guess a year
        later — which is exactly what `suggested` exists to keep out of
        reasoning."""
        doc = {**GOOD, "source": ""}
        with pytest.raises(ValueError, match="source"):
            mount_library(_write(tmp_path, doc), by="wei", base_dir=tmp_path)

    def test_mounting_without_an_author_is_refused(self, tmp_path):
        with pytest.raises(ValueError, match="who"):
            mount_library(_write(tmp_path, GOOD), by="", base_dir=tmp_path)


class TestItNeverInventsACause:
    def test_a_cause_outside_the_taxonomy_is_refused(self, tmp_path):
        """Past roughly forty codes two operators stop picking the same one. The
        library attaches to the seven the learner already speaks; it does not
        grow them."""
        doc = {**GOOD, "mechanisms": [{"cause": "gremlins", "mechanism": "x", "mode": "y"}]}
        with pytest.raises(ValueError, match="gremlins"):
            mount_library(_write(tmp_path, doc), by="wei", base_dir=tmp_path)

    def test_the_refusal_names_the_causes_that_are_allowed(self, tmp_path):
        doc = {**GOOD, "mechanisms": [{"cause": "gremlins", "mechanism": "x", "mode": "y"}]}
        with pytest.raises(ValueError, match="sensor_fault"):
            mount_library(_write(tmp_path, doc), by="wei", base_dir=tmp_path)

    def test_nothing_is_stored_when_one_entry_is_bad(self, tmp_path):
        """All or nothing: a half-mounted library is one nobody can reason about."""
        doc = {**GOOD, "mechanisms": [*GOOD["mechanisms"], {"cause": "gremlins", "mode": "x"}]}
        with pytest.raises(ValueError):
            mount_library(_write(tmp_path, doc), by="wei", base_dir=tmp_path)
        assert mounted_mechanisms(base_dir=tmp_path) == ()


class TestSilenceIsNotAgreement:
    """The refusal that matters most. A library that says nothing about a
    candidate must say NOTHING KNOWN — never "no objection", which reads as
    support and would make the step worse than not having it."""

    def test_an_unknown_cause_yields_nothing_known(self, tmp_path):
        mount_library(_write(tmp_path, GOOD), by="wei", base_dir=tmp_path)
        verdict = check_candidate("changeover", protocol="modbus", base_dir=tmp_path)
        assert verdict["status"] == "nothing_known"

    def test_nothing_known_carries_no_support(self, tmp_path):
        mount_library(_write(tmp_path, GOOD), by="wei", base_dir=tmp_path)
        verdict = check_candidate("changeover", protocol="modbus", base_dir=tmp_path)
        assert verdict["supports"] == [] and verdict["excluded"] is False

    def test_an_empty_library_says_nothing_known_for_everything(self, tmp_path):
        assert check_candidate("sensor_fault", protocol="modbus", base_dir=tmp_path)["status"] == (
            "nothing_known"
        )

    def test_a_known_cause_does_produce_something(self, tmp_path):
        """The complement: a checker that always said 'nothing known' would pass
        every test above and never earn its place."""
        mount_library(_write(tmp_path, GOOD), by="wei", base_dir=tmp_path)
        verdict = check_candidate("sensor_fault", protocol="modbus", base_dir=tmp_path)
        assert verdict["status"] == "known"
        assert verdict["supports"]


class TestItMayExcludeButNeverConfirm:
    """D28/D29. Excluding is the strong move a ranker cannot make; confirming is
    the one thing a library must never do on its own."""

    def test_a_mechanism_that_does_not_apply_here_excludes_the_candidate(self, tmp_path):
        """Applicability is what turns a knowledge base into a filter: this
        mechanism cannot happen on this equipment, so stop looking down it."""
        mount_library(_write(tmp_path, GOOD), by="wei", base_dir=tmp_path)
        verdict = check_candidate("sensor_fault", protocol="s7", base_dir=tmp_path)
        assert verdict["excluded"] is True
        assert "modbus" in verdict["reason"]

    def test_an_applicable_mechanism_is_not_excluded(self, tmp_path):
        mount_library(_write(tmp_path, GOOD), by="wei", base_dir=tmp_path)
        assert check_candidate("sensor_fault", protocol="modbus", base_dir=tmp_path)[
            "excluded"
        ] is (False)

    def test_a_mechanism_with_no_applicability_applies_everywhere(self, tmp_path):
        """Absence of a constraint is not a constraint. Reading "applies_to
        unset" as "applies nowhere" would silently exclude everything."""
        doc = {**GOOD, "mechanisms": [{"cause": "changeover", "mechanism": "m", "mode": "o"}]}
        mount_library(_write(tmp_path, doc), by="wei", base_dir=tmp_path)
        verdict = check_candidate("changeover", protocol="anything", base_dir=tmp_path)
        # `status` alone does not pin this: an entry judged inapplicable is still
        # "known", just excluded. The first version asserted only the status and
        # a mutation flipping `applies_to` to False survived it.
        assert verdict["status"] == "known"
        assert verdict["excluded"] is False, verdict
        assert verdict["supports"], verdict

    def test_it_never_returns_a_confirmed_grade(self, tmp_path):
        """D29 — `confirmed` is reachable only from outside the ranking. A
        library entry is inside it."""
        mount_library(_write(tmp_path, GOOD), by="wei", base_dir=tmp_path)
        verdict = check_candidate("sensor_fault", protocol="modbus", base_dir=tmp_path)
        assert "confirmed" not in str(verdict).lower()

    def test_it_hands_back_what_would_confirm_it(self, tmp_path):
        """The useful half: not a verdict, an instruction. In a plant that is
        usually a field action, not another query."""
        mount_library(_write(tmp_path, GOOD), by="wei", base_dir=tmp_path)
        verdict = check_candidate("sensor_fault", protocol="modbus", base_dir=tmp_path)
        assert any("loop check" in step for step in verdict["confirm_by"])


class TestSitesAreSeparate:
    def test_a_library_mounted_on_one_site_is_not_visible_on_another(self, tmp_path):
        mount_library(_write(tmp_path, GOOD), by="wei", site="line-a", base_dir=tmp_path)
        assert mounted_mechanisms(site="line-b", base_dir=tmp_path) == ()


class TestTheFileItself:
    def test_a_missing_file_says_which_one(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="nope.yaml"):
            load_library(tmp_path / "nope.yaml")

    def test_a_file_that_is_not_a_library_is_refused(self, tmp_path):
        path = tmp_path / "junk.yaml"
        path.write_text("just a string", encoding="utf-8")
        with pytest.raises(ValueError, match="mechanisms"):
            load_library(path)
