"""Adapter-belt MCP tools — stream egress + on-box LLM narration (mocked, no bus/model)."""

import pytest

import mcp_server.tools.egress_tools as egress_tools
import mcp_server.tools.llm_tools as llm_tools
from mcp_server.profiles import BRAIN_MODULES
from mcp_server.tools.egress_tools import stream_publish, stream_publish_event
from mcp_server.tools.llm_tools import rca_narrate


@pytest.fixture()
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("IAIOPS_HOME", str(tmp_path))
    return tmp_path


class _FakePublisher:
    def __init__(self, **opts):
        self.opts = opts
        self.points = None
        self.event = None

    def publish_points(self, points):
        self.points = points
        return len(points)

    def publish_event(self, subject, event):
        self.event = (subject, event)
        return 1

    def close(self):
        pass


@pytest.mark.unit
def test_tools_governed_low_and_registered():
    for tool in (stream_publish, stream_publish_event, rca_narrate):
        assert getattr(tool, "_is_governed_tool", False) is True
        assert getattr(tool, "_risk_level", "") == "low"
    assert "egress_tools" in BRAIN_MODULES and "llm_tools" in BRAIN_MODULES


@pytest.mark.unit
def test_stream_publish_skips_nonnumeric(home, monkeypatch):
    fake = _FakePublisher()
    monkeypatch.setattr(egress_tools, "get_publisher", lambda kind, **o: fake)
    out = stream_publish(
        points=[{"ref": "a", "value": 1.0}, {"ref": "b", "value": "OPEN"}], subject_prefix="p"
    )
    assert out["publisher"] == "nats"
    assert out["received"] == 2 and out["published"] == 1 and out["skipped_non_numeric"] == 1
    assert fake.points[0]["metric"] == "a"


@pytest.mark.unit
def test_stream_publish_unknown_publisher_teaches(home):
    assert "Unknown publisher" in stream_publish(points=[], publisher="kafka")["error"]


@pytest.mark.unit
def test_stream_publish_event(home, monkeypatch):
    fake = _FakePublisher()
    monkeypatch.setattr(egress_tools, "get_publisher", lambda kind, **o: fake)
    out = stream_publish_event(
        subject="rca.verdict", event={"primary_cause": "seal"}, subject_prefix="p"
    )
    assert out["published"] == 1 and out["subject"] == "p.rca.verdict"
    assert fake.event[0] == "rca.verdict"


@pytest.mark.unit
def test_stream_publish_event_requires_subject(home):
    assert "subject is required" in stream_publish_event(subject=" ", event={})["error"]


@pytest.mark.unit
def test_rca_narrate(home, monkeypatch):
    class FakeProvider:
        def complete(self, prompt, system=None):
            return "The pump seal failed just before the stop."

    monkeypatch.setattr(llm_tools, "get_provider", lambda kind, **o: FakeProvider())
    out = rca_narrate(verdict={"verdict": "one_primary_cause", "primary_cause": "seal"})
    assert out["provider"] == "ollama" and out["model"] == "llama3.1"
    assert "pump seal" in out["narration"].lower()


@pytest.mark.unit
def test_rca_narrate_requires_verdict(home):
    assert "verdict is required" in rca_narrate(verdict={})["error"]


@pytest.mark.unit
def test_rca_narrate_unknown_provider_teaches(home):
    assert "Unknown LLM provider" in rca_narrate(verdict={"a": 1}, provider="gpt")["error"]
