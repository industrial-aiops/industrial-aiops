"""Local-LLM SPI — provider factory + a STRICT, cited-only RCA narration prompt.

A provider exposes one method: ``complete(prompt, system=None) -> str``. Adapters live in sibling
modules and lazy-import their client. The narration prompt is deliberately constraining — it hands
the model only the facts already present in the deterministic verdict and forbids adding causes,
numbers, or citations — so the on-box model *phrases*, it does not *reason*.
"""

from __future__ import annotations

import json
from typing import Any

SUPPORTED_PROVIDERS = ("ollama",)

_NARRATION_SYSTEM = (
    "You are an OT diagnostics writing assistant. You are given a root-cause verdict already "
    "computed by a deterministic engine, with its evidence citations. Rephrase it in clear, "
    "concise plain language for a plant engineer. STRICT RULES: use ONLY the causes, "
    "confidences, and citations provided; never introduce a new cause, number, or citation; "
    "never claim more certainty than the verdict states; if the verdict is "
    "'insufficient_evidence', say so plainly and list the suggested next data to collect. "
    "Do not invent."
)


class LLMError(Exception):
    """A local-LLM operation failed; carries a teaching message."""


def build_rca_narration_prompt(verdict: dict) -> str:
    """Build the user prompt for narrating a (deterministic, cited) RCA verdict."""
    payload = json.dumps(verdict or {}, ensure_ascii=False, sort_keys=True, default=str)
    return (
        "Narrate this root-cause verdict for a plant engineer, following the strict rules. "
        "Return 2-5 sentences, no markdown headers.\n\nVERDICT (JSON):\n" + payload
    )


def narrate_rca_verdict(verdict: dict, provider: Any) -> str:
    """Phrase a cited RCA verdict via ``provider`` — narration only, never new reasoning."""
    return provider.complete(build_rca_narration_prompt(verdict), system=_NARRATION_SYSTEM)


def get_provider(kind: str, **opts: Any) -> Any:
    """Return a local-LLM provider for ``kind`` (ollama)."""
    k = (kind or "").strip().lower()
    if k == "ollama":
        from iaiops.core.llm.ollama import OllamaProvider

        return OllamaProvider(**opts)
    raise LLMError(
        f"Unknown LLM provider '{kind}'. Supported: {', '.join(SUPPORTED_PROVIDERS)}."
    )


__all__ = [
    "LLMError",
    "build_rca_narration_prompt",
    "narrate_rca_verdict",
    "get_provider",
    "SUPPORTED_PROVIDERS",
]
