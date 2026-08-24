"""An IoTDB path node is quoted — always, not only when it looks illegal.

A bare number is not a legal IoTDB path node, and a Modbus site's tags ARE
numbers: `collect run` stores samples under the register address, so a plain line
yields `0` and `10`. Unquoted, a live IoTDB 1.3.2 refuses both directions —
`ILLEGAL_PATH(509)` on insert, "no viable alternative at input" on select — so an
IoTDB historian could not serve a Modbus site at all. Every fixture in the live
suite used alphabetic metric names, which happen to be legal unquoted.

These are unit tests over the RULE. Whether a given node is quoted is not
observable from the outside — the server resolves `` `T` `` and `T` to the same
node, confirmed live — so a "quote only when it starts with a digit" variant
would behave identically and no round-trip test can tell them apart. The rule is
pinned here on purpose: encoding IoTDB's unquoted-identifier grammar is a second
rule that can disagree with the first, and getting it subtly wrong is exactly the
defect being fixed. Behaviour is covered by `test_tsdb_live.py`.
"""

from __future__ import annotations

import pytest

from iaiops.core.sink.iotdb import _sanitize_path, quote_path_node

pytestmark = pytest.mark.unit


class TestEveryNodeIsQuoted:
    @pytest.mark.parametrize("metric", ["0", "10", "BEARING_TEMP", "line1_temp", "40001"])
    def test_the_node_is_backquoted_whatever_it_looks_like(self, metric):
        assert quote_path_node(metric) == f"`{metric}`"

    def test_a_purely_numeric_tag_survives_as_itself(self):
        """`0` must stay `0`. Prefixing it to make it legal would rename the
        operator's tag, and the name is what every lookup uses."""
        assert quote_path_node("0") == "`0`"


class TestQuotingCannotBeEscaped:
    """The sanitizer runs first, so nothing can close the quote it sits inside."""

    @pytest.mark.parametrize(
        "hostile",
        [
            "a`.root.evil",
            "`",
            "t`;DELETE DATABASE root.x;--",
            "a.b",
            "*",
        ],
    )
    def test_no_backquote_survives_into_the_quoted_text(self, hostile):
        node = quote_path_node(hostile)
        assert node.startswith("`") and node.endswith("`")
        assert "`" not in node[1:-1], f"a backquote survived sanitization: {node}"

    def test_an_empty_metric_still_yields_a_node(self):
        """A node must exist for the path to be well-formed at all."""
        assert quote_path_node("") == "`unknown`"

    def test_it_quotes_exactly_what_the_sanitizer_produced(self):
        """One sanitizer, so the write path and the read path cannot disagree
        about which node a tag maps to."""
        for metric in ["a.b", "40 001", "线体1"]:
            assert quote_path_node(metric) == f"`{_sanitize_path(metric)}`"
