"""Flood-warning invariant: legitimate named editions must not trip the warning.

``mcp_server.server`` logs a "Tool flood" warning when a launch exposes more than
:data:`TOOL_FLOOD_WARN_THRESHOLD` tools. Its only real purpose is to flag the
oversized catch-all ``IAIOPS_MCP=all``; if a normal named edition (e.g.
``factory``) also trips it, the signal drowns in alarm fatigue.

These tests expand every profile from source (no hardcoded counts) so the
invariant can't silently regress when an edition grows or a tool is added:

* every named edition EXCEPT the explicit catch-all ``all`` stays at or below the
  threshold (no warning), and
* ``all`` stays above the threshold (still warns).
"""

from __future__ import annotations

import pytest

from mcp_server.profiles import (
    NAMED_PROFILES,
    TOOL_FLOOD_WARN_THRESHOLD,
    selection_tool_count,
)

# The one named profile that is intentionally the "you asked for everything"
# opt-in — it is the case the flood warning exists to catch.
_CATCH_ALL = "all"


@pytest.mark.unit
@pytest.mark.parametrize("profile", [p for p in NAMED_PROFILES if p != _CATCH_ALL])
def test_named_edition_does_not_trip_flood_warning(profile):
    """Each legitimate named edition expands to <= threshold tools (no warning)."""
    count = selection_tool_count(profile)
    assert count <= TOOL_FLOOD_WARN_THRESHOLD, (
        f"edition {profile!r} exposes {count} tools, above the flood threshold "
        f"{TOOL_FLOOD_WARN_THRESHOLD} — it would warn on every legitimate launch"
    )


@pytest.mark.unit
def test_all_profile_still_trips_flood_warning():
    """The catch-all ``all`` stays above the threshold so the warning still fires."""
    count = selection_tool_count(_CATCH_ALL)
    assert count > TOOL_FLOOD_WARN_THRESHOLD, (
        f"IAIOPS_MCP=all exposes only {count} tools (<= threshold "
        f"{TOOL_FLOOD_WARN_THRESHOLD}) — the flood warning would never fire"
    )


@pytest.mark.unit
def test_threshold_sits_above_largest_legitimate_edition_but_below_all():
    """Sanity: threshold is bracketed by the largest named edition and ``all``."""
    largest_named = max(selection_tool_count(p) for p in NAMED_PROFILES if p != _CATCH_ALL)
    all_count = selection_tool_count(_CATCH_ALL)
    assert largest_named <= TOOL_FLOOD_WARN_THRESHOLD < all_count, (
        f"largest named edition={largest_named}, threshold="
        f"{TOOL_FLOOD_WARN_THRESHOLD}, all={all_count}"
    )
