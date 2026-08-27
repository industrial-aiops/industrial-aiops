"""Who feeds whom on this line — stated by a person, never inferred.

HLD §10.3② and D25. Relations are the **second axis** of root-cause analysis:
without them, an upstream stoppage produces a string of equally-confident
downstream false causes, because time alone cannot tell "caused" from
"was caused by".

D25 is the reason this is a declaration and not a detector: on a production line
an upstream stop makes everything downstream correlate, so timestamp
co-occurrence produces candidates a person must confirm — never edges. The most
trustworthy source, and the one that needs no inference at all, is somebody
saying what order the line runs in.

This is also the first thing to move `Requirement.expressible` from False to
True. Until now `investigate plan` reported cross-asset propagation as "this
product offers no way to supply it yet", which was accurate. Once a command
exists to declare it, that same gap must report as *unmet*, not as impossible —
otherwise the flag stops meaning anything (D36).
"""

from __future__ import annotations

import pytest

from iaiops.core.knowledge.relations import (
    declare_relation,
    downstream_of,
    forget_relation,
    line_relations,
)

pytestmark = pytest.mark.unit


@pytest.fixture
def site(tmp_path):
    return tmp_path


class TestAPersonStatesTheOrder:
    def test_a_declared_relation_comes_back(self, site):
        declare_relation("press", "oven", by="wei", base_dir=site)
        assert [(r.upstream, r.downstream) for r in line_relations(base_dir=site)] == [
            ("press", "oven")
        ]

    def test_it_is_stored_as_declared_not_suggested(self, site):
        """A person is the evidence (D23). Filing this as `suggested` would hold
        it out of the reasoning it exists to inform."""
        declare_relation("press", "oven", by="wei", base_dir=site)
        assert line_relations(base_dir=site)[0].source == "declared"

    def test_it_records_who_said_so(self, site):
        """The whole trust model rests on a person having stated it. An edge with
        no author is indistinguishable from an inferred one a year later."""
        declare_relation("press", "oven", by="wei", base_dir=site)
        assert line_relations(base_dir=site)[0].by == "wei"

    def test_declaring_without_an_author_is_refused(self, site):
        with pytest.raises(ValueError, match="who"):
            declare_relation("press", "oven", by="", base_dir=site)

    def test_it_survives_a_reload(self, site):
        declare_relation("press", "oven", by="wei", base_dir=site)
        declare_relation("oven", "packer", by="wei", base_dir=site)
        assert len(line_relations(base_dir=site)) == 2

    def test_declaring_the_same_edge_twice_does_not_duplicate_it(self, site):
        declare_relation("press", "oven", by="wei", base_dir=site)
        declare_relation("press", "oven", by="lin", base_dir=site)
        assert len(line_relations(base_dir=site)) == 1

    def test_the_later_author_wins(self, site):
        """Re-declaring is how a correction is made; the audit log holds both."""
        declare_relation("press", "oven", by="wei", base_dir=site)
        declare_relation("press", "oven", by="lin", base_dir=site)
        assert line_relations(base_dir=site)[0].by == "lin"

    def test_an_edge_can_be_withdrawn(self, site):
        declare_relation("press", "oven", by="wei", base_dir=site)
        assert forget_relation("press", "oven", base_dir=site) is True
        assert line_relations(base_dir=site) == ()

    def test_withdrawing_something_never_declared_says_so(self, site):
        assert forget_relation("press", "oven", base_dir=site) is False


class TestItRefusesShapesThatWouldMislead:
    def test_an_asset_cannot_feed_itself(self, site):
        with pytest.raises(ValueError, match="itself"):
            declare_relation("press", "press", by="wei", base_dir=site)

    @pytest.mark.parametrize("bad", ["", "   "])
    def test_an_empty_asset_name_is_refused(self, site, bad):
        with pytest.raises(ValueError, match="name"):
            declare_relation(bad, "oven", by="wei", base_dir=site)

    def test_a_cycle_is_refused(self, site):
        """A line that feeds itself makes "downstream" meaningless, and the
        propagation walk would not terminate. Refused at declaration, where a
        person can still fix it, rather than at analysis time."""
        declare_relation("press", "oven", by="wei", base_dir=site)
        declare_relation("oven", "packer", by="wei", base_dir=site)
        with pytest.raises(ValueError, match="cycle"):
            declare_relation("packer", "press", by="wei", base_dir=site)

    def test_the_refused_cycle_is_not_stored(self, site):
        """A refusal that still writes is worse than no refusal."""
        declare_relation("press", "oven", by="wei", base_dir=site)
        with pytest.raises(ValueError):
            declare_relation("oven", "press", by="wei", base_dir=site)
        assert len(line_relations(base_dir=site)) == 1


class TestWhatIsDownstream:
    @pytest.fixture
    def line(self, site):
        declare_relation("press", "oven", by="wei", base_dir=site)
        declare_relation("oven", "packer", by="wei", base_dir=site)
        declare_relation("packer", "palletiser", by="wei", base_dir=site)
        return site

    def test_it_follows_the_line_all_the_way_down(self, line):
        assert downstream_of("press", base_dir=line) == ("oven", "packer", "palletiser")

    def test_it_is_ordered_by_distance(self, line):
        """Nearest first: the operator walks the line in that order."""
        assert downstream_of("oven", base_dir=line) == ("packer", "palletiser")

    def test_the_last_station_has_nothing_downstream(self, line):
        assert downstream_of("palletiser", base_dir=line) == ()

    def test_an_unknown_asset_has_nothing_downstream(self, line):
        """Not an error: an asset nobody declared is simply unrelated, which is
        exactly what an undeclared line looks like."""
        assert downstream_of("nowhere", base_dir=line) == ()

    def test_it_never_walks_upstream(self, line):
        """The direction is the whole content of the fact. A symmetric answer
        would put the cause downstream of its own effect."""
        assert "press" not in downstream_of("packer", base_dir=line)


class TestSitesAreSeparate:
    """D34 — the boundary is the plant area / environment, not the person."""

    def test_a_relation_declared_on_one_site_is_not_visible_on_another(self, site):
        declare_relation("press", "oven", by="wei", site="line-a", base_dir=site)
        assert line_relations(site="line-b", base_dir=site) == ()

    def test_each_site_keeps_its_own(self, site):
        declare_relation("press", "oven", by="wei", site="line-a", base_dir=site)
        declare_relation("mixer", "filler", by="wei", site="line-b", base_dir=site)
        assert len(line_relations(site="line-a", base_dir=site)) == 1
        assert len(line_relations(site="line-b", base_dir=site)) == 1
