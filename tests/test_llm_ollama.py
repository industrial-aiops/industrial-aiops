"""Ollama provider + strict RCA narration (fake requests / fake provider, no model)."""

import sys
import types

import pytest

from iaiops.core.llm import LLMError, get_provider, narrate_rca_verdict
from iaiops.core.llm.ollama import OllamaProvider


def _fake_requests(reply: str = "It broke.", status: int = 200) -> types.ModuleType:
    mod = types.ModuleType("requests")

    class _ReqError(Exception):
        pass

    class Resp:
        def __init__(self) -> None:
            self.status_code = status
            self.text = "err"

        def json(self):
            return {"message": {"content": reply}}

    def post(url, json=None, timeout=None):
        post.captured = {"url": url, "json": json}
        return Resp()

    mod.RequestException = _ReqError
    mod.post = post
    return mod


@pytest.mark.unit
def test_complete(monkeypatch):
    fr = _fake_requests("Pump seal failed.")
    monkeypatch.setitem(sys.modules, "requests", fr)
    out = OllamaProvider(model="llama3.1").complete("hi", system="sys")
    assert out == "Pump seal failed."
    body = fr.post.captured["json"]
    assert body["model"] == "llama3.1"
    assert body["messages"][0]["role"] == "system"
    assert body["stream"] is False


@pytest.mark.unit
def test_complete_http_error(monkeypatch):
    monkeypatch.setitem(sys.modules, "requests", _fake_requests(status=500))
    with pytest.raises(LLMError):
        OllamaProvider().complete("x")


@pytest.mark.unit
def test_narrate_is_cited_only_and_uses_provider():
    class FakeProvider:
        def complete(self, prompt, system=None):
            self.prompt, self.system = prompt, system
            return "narrated"

    fp = FakeProvider()
    out = narrate_rca_verdict({"verdict": "insufficient_evidence"}, fp)
    assert out == "narrated"
    assert "insufficient_evidence" in fp.prompt  # the real verdict is handed to the model
    assert "Do not invent" in fp.system  # strict, cited-only steer


@pytest.mark.unit
def test_get_provider():
    assert isinstance(get_provider("ollama"), OllamaProvider)
    with pytest.raises(LLMError):
        get_provider("gpt")
