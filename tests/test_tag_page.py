"""The point-list confirmation page — the App front end, as one static file.

HLD §13.9 ordered the App page after the CLI and the report, and justified it
narrowly: it exists for the steps where a person must go **row by row and tick**
— point-list confirmation, timeline review — where a table beats command-line
question-and-answer. It is not a dashboard.

Delivered as a self-contained file rather than a served app. A localhost server
inside an OT box has to answer which address it binds, who authenticates, and how
the firewall is opened — and every declaration in this product requires `--by`,
so **a page with no identity cannot answer "who ticked this"**, which is the one
thing it exists to record. The file avoids all of that: it opens on the laptop
already in the plant office, and the CSV it produces goes through `tags apply`,
which is where the author is supplied.

**The rule this page must not break: it does not re-implement a single refusal.**
`run_state` needing `running_when`, a ref having to be monitored, a role claimed
twice — reproducing those in JavaScript is how they drift apart from the ones
that actually gate the config. The page collects; `iaiops tags apply` judges.

This page ships script, unlike the investigation and OEE reports. That is a real
difference and worth stating: what stays true is that it makes **no network
request** — which is the property that matters in a plant.
"""

from __future__ import annotations

import json
import re

import pytest

from iaiops.core.runtime.tag_page import render_tag_page

pytestmark = pytest.mark.unit

HOSTILE = '</script><script>alert("x")</script>'


class FakeTag:
    def __init__(self, ref, label="", role="", running_when=()):
        self.ref = ref
        self.label = label
        self.role = role
        self.running_when = running_when


class FakeTarget:
    def __init__(self, name, tags):
        self.name = name
        self.protocol = "modbus"
        self.tags = tags


class FakeConfig:
    def __init__(self, targets):
        self.targets = targets


def site(label="GoodPartsCounter"):
    return FakeConfig(
        [
            FakeTarget("line1", [FakeTag("40001", label), FakeTag("40002", "Machine running")]),
            FakeTarget("line2", [FakeTag("30001", "Total", role="total_count")]),
        ]
    )


def page(**kw):
    return render_tag_page(site(), generated_at="2026-08-28T09:00:00Z", **kw)


class TestItStillNeverSuggests:
    """The same D16 rule as the CSV, in the front end where a pre-selected
    dropdown would be far more persuasive than a pre-filled cell."""

    def test_no_row_arrives_with_a_role_chosen(self):
        data = _embedded(page())
        assert all(r["role"] == "" for r in data["rows"]), data["rows"]

    def test_the_tag_named_after_a_role_is_not_pre_selected(self):
        row = next(r for r in _embedded(page())["rows"] if r["label"] == "GoodPartsCounter")
        assert row["role"] == "", row

    def test_an_existing_declaration_is_shown_read_only(self):
        row = next(r for r in _embedded(page())["rows"] if r["ref"] == "30001")
        assert row["declared_role"] == "total_count" and row["role"] == ""


class TestTheChoicesCannotDriftFromTheEngine:
    def test_the_options_are_exactly_the_declared_vocabulary(self):
        """A hand-written option list is how a fifth role appears on a page and
        is then refused by `apply` — with the person having no way to know why."""
        from iaiops.core.runtime.config import TagRole

        assert tuple(_embedded(page())["roles"]) == tuple(TagRole.ALL)

    def test_the_columns_are_the_sheet_columns(self):
        from iaiops.core.runtime.tag_sheet import SHEET_COLUMNS

        assert tuple(_embedded(page())["columns"]) == tuple(SHEET_COLUMNS)


class TestItDoesNotReImplementTheRefusals:
    """The rule that keeps this page honest. Duplicated validation drifts, and a
    page that says "looks fine" while `apply` refuses is worse than no page."""

    def test_it_names_apply_as_the_authority(self):
        assert "tags apply" in page()

    def test_it_does_not_ship_a_javascript_role_validator(self):
        script = _script(page())
        for smell in ("running_when.length", "isValid", "validate(", "REQUIRED_ROLES"):
            assert smell not in script, f"the page re-implements a rule: {smell}"


class TestTheDataIsEmbeddedSafely:
    """The escaping context here is JavaScript, not HTML text — a different trap
    from the reports. A label containing `</script>` ends the block early and
    everything after it becomes markup."""

    def test_a_label_that_closes_the_script_tag_cannot_escape(self):
        html = render_tag_page(site(label=HOSTILE), generated_at="x")
        assert "</script><script>alert" not in html

    def test_the_hostile_label_is_still_carried_through_faithfully(self):
        """Escaping must not silently mangle it — the person has to recognise
        their own tag in the table."""
        html = render_tag_page(site(label=HOSTILE), generated_at="x")
        assert _embedded(html)["rows"][0]["label"] == HOSTILE

    def test_no_raw_angle_bracket_survives_in_the_embedded_json(self):
        html = render_tag_page(site(label=HOSTILE), generated_at="x")
        assert "<" not in _script(html).split("</script")[0].split("=", 1)[1].split("\n")[0]


class TestItMakesNoNetworkRequest:
    def test_nothing_is_loaded_from_anywhere(self):
        html = page()
        for pattern in ("http://", "https://", "//cdn", "@import", "url(http"):
            assert pattern not in html, f"the page references {pattern!r}"

    def test_there_are_no_external_resource_elements(self):
        html = page().lower()
        for tag in ("<link", "<img", "<iframe", "<object", "<embed", "<source"):
            assert tag not in html

    def test_it_does_not_fetch(self):
        script = _script(page())
        for call in ("fetch(", "XMLHttpRequest", "WebSocket", "navigator.sendBeacon"):
            assert call not in script


class TestStructure:
    def test_it_is_a_complete_standalone_document(self):
        html = page()
        assert html.startswith("<!doctype html>")
        assert "<title>" in html and html.rstrip().endswith("</html>")

    def test_the_same_config_renders_the_same_bytes(self):
        assert page() == page()

    def test_it_has_a_row_per_tag_with_a_role_control(self):
        html = page()
        assert html.count("<select") == 3

    def test_wide_content_scrolls_inside_its_own_container(self):
        assert 'class="scroll"' in page()

    def test_a_site_with_no_tags_says_what_to_do_first(self):
        html = render_tag_page(FakeConfig([]), generated_at="x")
        assert "scan run" in html


class TestBothLanguages:
    def test_an_unknown_language_raises(self):
        with pytest.raises(ValueError, match="fr"):
            page(lang="fr")

    def test_the_chinese_page_declares_itself_chinese(self):
        assert 'lang="zh"' in page(lang="zh")


def _script(html: str) -> str:
    return "\n".join(re.findall(r"<script[^>]*>(.*?)</script>", html, flags=re.S))


def _embedded(html: str) -> dict:
    found = re.search(r"const SHEET = (\{.*?\});", _script(html), flags=re.S)
    assert found, "the page must embed its data as `const SHEET = {...}`"
    return json.loads(found.group(1).replace("\\u003c", "<"))


class TestEditableCellsAllStartEmpty:
    """Found by looking at the rendered page, not by an assertion.

    `running_when` was echoed into its EDITABLE input while `role` was left
    blank. Two editable fields, one pre-filled — and somebody who changed that
    row to a counter got refused over a field they never touched. Everything
    already declared is read-only context; everything editable starts empty.
    """

    def _declared(self):
        return FakeConfig(
            [FakeTarget("line1", [FakeTag("40002", "Machine running", "run_state", (2,))])]
        )

    def test_the_running_when_input_is_empty(self):
        html = render_tag_page(self._declared(), generated_at="x")
        assert re.search(r'id="run-0"[^>]*value=""', html), html[html.index("run-0") - 200 :][:400]

    def test_the_existing_value_is_still_shown_read_only(self):
        """It must not vanish — a person confirming a run_state needs to see what
        the line already says it is."""
        html = render_tag_page(self._declared(), generated_at="x")
        assert "running_when: 2" in html

    def test_the_exported_sheet_agrees_with_the_page(self):
        from iaiops.core.runtime.tag_sheet import sheet_rows

        row = sheet_rows(self._declared())[0]
        assert row["running_when"] == "" and row["declared_role"] == "run_state"


class TestTheScriptCannotDriftFromTheColumns:
    """pytest never runs this page's JavaScript, so anything it hardcodes is
    untested by construction. The CSV builder therefore reads `SHEET.columns`
    rather than naming fields in order — a reordering of `SHEET_COLUMNS` would
    otherwise shift every value one column right with nothing to catch it."""

    def test_the_builder_does_not_hardcode_the_field_order(self):
        script = _script(page())
        assert "SHEET.columns.map" in script, script
        assert "row.endpoint, row.ref" not in script
