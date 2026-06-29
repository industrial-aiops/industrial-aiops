"""subscription_health — sequenced-feed loss / reorder / overload detection."""

from __future__ import annotations

from iaiops.core.brain.diagnostics import subscription_health as sh


def test_clean_sequence_is_ok():
    r = sh([1, 2, 3, 4, 5])
    assert r["verdict"] == "ok"
    assert r["missed_count"] == 0
    assert r["duplicate_count"] == 0
    assert r["out_of_order_count"] == 0


def test_gap_is_lossy():
    r = sh([1, 2, 4, 5])
    assert r["missed_count"] == 1  # seq 3 dropped
    assert r["verdict"] == "lossy"
    r2 = sh([1, 2, 7])
    assert r2["missed_count"] == 4  # 3,4,5,6


def test_duplicate_and_out_of_order_are_reordered():
    assert sh([1, 2, 2, 3])["duplicate_count"] == 1
    assert sh([1, 2, 2, 3])["verdict"] == "reordered"
    r = sh([1, 2, 3, 2])
    assert r["out_of_order_count"] == 1
    assert r["verdict"] == "reordered"


def test_wrap_at_handles_rolling_counter():
    # Sparkplug B seq 0-255 rolls cleanly
    assert sh([254, 255, 0, 1], wrap_at=256)["verdict"] == "ok"
    # a gap across the wrap is still loss
    assert sh([254, 0], wrap_at=256)["missed_count"] == 1
    # a backward jump under the modulus is a reorder, not a huge "missed"
    r = sh([5, 3], wrap_at=256)
    assert r["out_of_order_count"] == 1
    assert r["missed_count"] == 0


def test_republish_rejection_means_overloaded():
    r = sh([1, 2, 3], republish_requested=10, republish_rejected=5)
    assert r["republish_reject_rate"] == 0.5
    assert r["verdict"] == "overloaded"


def test_channel_density_flagged_and_takes_priority():
    r = sh([1, 2, 4], tags_per_channel={"ch1": 7000, "ch2": 3000})
    assert any(c["channel"] == "ch1" for c in r["overloaded_channels"])
    assert all(c["channel"] != "ch2" for c in r["overloaded_channels"])
    # overloaded is the root cause and outranks the resulting loss
    assert r["verdict"] == "overloaded"


def test_recommendation_present_and_nothing_to_evaluate():
    assert sh([1, 2, 3])["recommendation"]
    assert "error" in sh([])
    assert "error" in sh([], tags_per_channel={})


def test_non_numeric_sequence_entries_ignored():
    r = sh([1, "x", 2, None, 3])
    assert r["received"] == 3
    assert r["verdict"] == "ok"
