"""Local-LLM adapter belt — an OPTIONAL, on-box model for a fully air-gapped deployment.

Strict boundary (this is the whole point): the LLM is used ONLY to **narrate an already-computed,
already-cited** RCA verdict in plain language. It never derives causes, invents citations, or scores
confidence — that stays deterministic in ``iaiops.core.brain.rca`` (see docs/RCA.md). Pointing
this at an on-box model (e.g. Ollama) keeps diagnosis fully local — data never leaves the plant.

Providers lazy-import their client, so the base package imports without any.
"""

from iaiops.core.llm.base import LLMError, get_provider, narrate_rca_verdict

__all__ = ["LLMError", "get_provider", "narrate_rca_verdict"]
