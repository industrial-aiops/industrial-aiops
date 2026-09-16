"""The README's credibility table must agree with the verification record.

The README table is what a reader meets first; `docs/VERIFICATION-RECORD.md` is
where the rung was argued. They drifted: the record graded **MQTT / Sparkplug B**
at 2a against a real mosquitto broker while the README still listed Sparkplug
under "mock-verified, no real device" — an UNDERclaim, on the headline feature,
in the one table whose whole job is to be exact. S7comm, Mitsubishi MC and
SECS/GEM sat in the same wrong row.

An underclaim is a defect here for the same reason an overclaim is: the table's
value is that a reader can rely on it without reading the record, and a table
that is wrong in either direction cannot be relied on in either direction.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_RUNGS = ("2a", "2b", "2c", "3", "mock")


def _root() -> Path:
    return Path(__file__).resolve().parents[1]


def _key(name: str) -> str:
    """Canonical protocol key: the name before any parenthetical qualifier."""
    name = re.sub(r"[*`_]", "", name).split("(")[0]
    return re.sub(r"[^a-z0-9]", "", name.lower())


def _rungs_in(cell: str) -> set[str]:
    # Footnote markers are superscripts (`2a⁴`), and Python counts those as word
    # characters — so `\b2a\b` silently missed every footnoted rung, which is most
    # of the interesting ones. Match on the ASCII skeleton instead.
    cell = re.sub(r"[^\x00-\x7f]", " ", cell)
    found = set(re.findall(r"\b(2a|2b|2c)\b", cell))
    if "mock only" in cell:
        found.add("mock")
    if re.fullmatch(r"[\s*]*3[\s*]*", cell.strip()):
        found.add("3")
    return found


#: The record grades the energy package, the MCP interface and the egress paths in
#: their own sections. The README table summarises THIS package's protocols.
_BASE_SECTION = "## Base package"


def _record(base_only: bool = True) -> dict[str, set[str]]:
    """protocol → the rungs the record grades it at."""
    out: dict[str, set[str]] = {}
    in_base = not base_only
    for line in (_root() / "docs/VERIFICATION-RECORD.md").read_text("utf-8").splitlines():
        if line.startswith("## "):
            in_base = line.startswith(_BASE_SECTION) or not base_only
        if not in_base or not line.startswith("| **") or line.count("|") < 4:
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        rungs = _rungs_in(cells[1])
        if rungs and _key(cells[0]) not in ("1", ""):
            out.setdefault(_key(cells[0]), set()).update(rungs)
    return out


def _readme_table() -> dict[str, set[str]]:
    """protocol → every rung row it is listed in, in the README's summary table.

    A SET, not one row: a protocol listed at its right rung AND at a flattering
    one reads as verified at the flattering one, and a dict that lets the later
    row win could not see it.
    """
    text = (_root() / "README.md").read_text("utf-8")
    out: dict[str, set[str]] = {}
    for line in text.splitlines():
        if not line.startswith("| **") or "—" not in line:
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        rung = next(
            (r for r in _RUNGS if cells[0].startswith(f"**{r}") and cells[0][2 + len(r)] in "* "),
            "",
        )
        if not rung or len(cells) < 3 or "zero, for every protocol" in cells[2]:
            continue
        for entry in cells[2].split("·"):
            if _key(entry):
                out.setdefault(_key(entry), set()).add(rung)
    return out


def test_the_readme_summarises_the_record_rather_than_disagreeing_with_it():
    record, readme = _record(), _readme_table()
    assert readme, "the README rung table was not found — did its shape change?"
    wrong = {
        name: (sorted(rungs), sorted(record[name]))
        for name, rungs in readme.items()
        if name in record and not rungs <= record[name]
    }
    assert not wrong, f"README rung disagrees with the record: {wrong}"


def test_nothing_verified_on_a_wire_is_listed_as_mock_only():
    """The exact drift that happened: a protocol graded 2a listed as mock."""
    record, readme = _record(), _readme_table()
    misfiled = sorted(
        name
        for name, rungs in readme.items()
        if "mock" in rungs and record.get(name, set()) & {"2a", "2b", "2c"}
    )
    assert not misfiled, f"listed as mock-only but verified on a wire: {misfiled}"


def test_every_protocol_the_readme_names_exists_in_the_record():
    unknown = sorted(set(_readme_table()) - set(_record()))
    assert not unknown, f"named in the README table, absent from the record: {unknown}"


@pytest.mark.parametrize("readme", ["README.md", "README.zh-CN.md"])
def test_the_edition_count_matches_the_skills_that_ship(readme):
    """`pharma` shipped and the English README kept saying nine — a whole vertical
    invisible to the primary-language reader, while the file contradicted itself
    two sections later."""
    editions = sorted(
        p.name.removeprefix("iaiops-")
        for p in (_root() / "skills").iterdir()
        if p.is_dir() and p.name.startswith("iaiops-")
    )
    text = (_root() / readme).read_text("utf-8")
    words = {"Ten": 10, "十个": 10, "Nine": 9, "九个": 9, "Eleven": 11, "十一个": 11}
    hits = list(re.finditer("(" + "|".join(words) + r")[ *]*(?:per-industry |行业版)", text))
    assert hits, f"{readme} no longer states an edition count"
    claimed = {words[m.group(1)] for m in hits}
    assert claimed == {len(editions)}, (
        f"{readme} claims {claimed}, ships {len(editions)}: {editions}"
    )
    # In the SAME passage, not merely somewhere in the file: `pharma` was named in
    # a later section while the list that counts the editions left it out.
    passage = text[hits[0].start() : hits[0].end() + 400]
    absent = [name for name in editions if name not in passage]
    assert not absent, f"{readme} counts {len(editions)} editions but its list omits: {absent}"


def test_every_protocol_the_record_grades_is_in_the_readme_table():
    """A protocol quietly dropped from the summary is as misleading as one filed
    at the wrong rung — the reader cannot tell "not verified" from "not listed"."""
    missing = sorted(set(_record()) - set(_readme_table()))
    assert not missing, f"graded in the record, absent from the README table: {missing}"
