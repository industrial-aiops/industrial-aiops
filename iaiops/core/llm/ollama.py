"""Ollama local-LLM provider — on-box, air-gapped narration via Ollama's HTTP API.

Talks to a local Ollama server (default ``http://localhost:11434``) over plain HTTP — no heavy
client dependency (reuses ``requests``, the same pin as the MTConnect/InfluxDB extras). Install with
``pip install iaiops[ollama]``. The HTTP call is isolated in ``complete`` so callers are
mock-testable without a running model (待核实 against a live Ollama server).
"""

from __future__ import annotations

from iaiops.core.llm.base import LLMError


class OllamaProvider:
    """Uniform provider over the Ollama ``/api/chat`` endpoint (待核实)."""

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model: str = "llama3.1",
        timeout_s: float = 60.0,
        temperature: float = 0.1,
    ) -> None:
        self._url = (base_url or "http://localhost:11434").rstrip("/")
        self._model = model or "llama3.1"
        self._timeout = float(timeout_s or 60.0)
        self._temperature = float(temperature)

    def complete(self, prompt: str, system: str | None = None) -> str:
        """Return the model's reply text for ``prompt`` (with optional ``system`` steer)."""
        try:
            import requests
        except ImportError as exc:  # pragma: no cover — only without requests
            raise LLMError(
                "The 'requests' package is not installed. Install the Ollama provider: "
                "'pip install iaiops[ollama]'."
            ) from exc
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": str(prompt or "")})
        body = {
            "model": self._model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": self._temperature},
        }
        try:
            resp = requests.post(f"{self._url}/api/chat", json=body, timeout=self._timeout)
        except requests.RequestException as exc:
            raise LLMError(f"Ollama request to {self._url} failed: {exc}") from exc
        if resp.status_code >= 300:
            raise LLMError(f"Ollama returned HTTP {resp.status_code}: {resp.text[:200]}")
        data = resp.json()
        return str((data.get("message") or {}).get("content", "")).strip()


__all__ = ["OllamaProvider"]
