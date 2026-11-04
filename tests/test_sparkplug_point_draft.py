"""A bounded BIRTH capture produces candidates, never semantic assertions."""

from types import SimpleNamespace

import pytest

from iaiops.core.onboard.sparkplug_draft import capture_point_draft, point_draft


def test_draft_keeps_roles_blank_and_reports_incomplete_capture():
    target = SimpleNamespace(name="broker", protocol="mqtt", stale_after_s=10)
    capture = {
        "schema": {"Plant/Edge/Device": {"Speed": "Float", "Running": "Boolean"}},
        "birth_count": 1,
        "node_count": 1,
        "message_count": 1,
        "topic": "spBv1.0/#",
    }
    result = point_draft(capture, target)
    assert result["complete"] is False
    assert {r["ref"] for r in result["candidate_tags"]} == {
        "Plant/Edge/Device:Speed",
        "Plant/Edge/Device:Running",
    }
    assert all(r["role"] == "" and r["label"] == "" for r in result["candidate_tags"])


def test_draft_refuses_no_birth_and_missing_staleness():
    target = SimpleNamespace(name="broker", protocol="mqtt", stale_after_s=10)
    with pytest.raises(ValueError, match="No BIRTH"):
        point_draft({"schema": {}}, target)
    with pytest.raises(ValueError, match="stale_after_s"):
        point_draft(
            {"schema": {"G/E": {"M": "Int"}}},
            SimpleNamespace(name="broker", protocol="mqtt", stale_after_s=0),
        )


def test_invalid_target_is_refused_before_broker_subscription(monkeypatch):
    from iaiops.connectors.sparkplug import live

    monkeypatch.setattr(
        live,
        "sparkplug_live_schema",
        lambda *_args: pytest.fail("subscribed before checking endpoint"),
    )
    with pytest.raises(ValueError, match="MQTT endpoint"):
        capture_point_draft(SimpleNamespace(name="plc", protocol="s7", stale_after_s=10))
    with pytest.raises(ValueError, match="stale_after_s"):
        capture_point_draft(SimpleNamespace(name="broker", protocol="mqtt", stale_after_s=0))
