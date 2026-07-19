"""On-box LLM MCP tool — air-gapped narration of an already-cited RCA verdict (adapter belt).

STRICT boundary: the model only rephrases a verdict the deterministic RCA core already produced and
cited — it never derives causes, invents citations, or scores confidence (see docs/RCA.md). Runs
against an on-box model (Ollama) so diagnosis stays fully local. Optional extra:
``pip install iaiops[ollama]``.
"""

from typing import Any

from iaiops.core.governance import governed_tool
from iaiops.core.llm import get_provider, narrate_rca_verdict
from iaiops.core.llm.base import SUPPORTED_PROVIDERS
from mcp_server._shared import mcp, tool_errors


# egress=True — the closest judgment call in the classification; argued here so a
# reviewer can disagree with the reasoning rather than guess at it.
#
# AGAINST marking it: the tool is designed for air-gapped use, ``base_url``
# defaults to localhost, and a site that sets IAIOPS_NO_EGRESS is exactly the
# site that wants on-box narration. Marking it costs that site a capability.
#
# FOR marking it (what we did): ``base_url`` is a free-text argument, so the
# DESTINATION is chosen by the caller — and under this repo's threat model the
# caller is a weak, local, or prompt-injected model. The payload is not
# incidental: the prompt embeds the full RCA verdict, i.e. plant tags, values and
# evidence citations. "Nothing leaves this box, as long as the model passes
# localhost" is not a guarantee, and the gate deliberately refuses to police
# arguments at call time. Same reasoning as historian_push's local 'sqlite' sink.
#
# A truly air-gapped box has no route out anyway, so the operator loses defence
# in depth, not the narration itself, by leaving IAIOPS_NO_EGRESS off there.
@mcp.tool()
@governed_tool(risk_level="low", egress=True)
@tool_errors("dict")
def rca_narrate(
    verdict: dict[str, Any],
    base_url: str = "http://localhost:11434",
    model: str = "llama3.1",
    provider: str = "ollama",
) -> dict:
    """[READ][risk=low] Narrate a cited RCA verdict in plain language via an on-box LLM.

    Air-gapped: hands the already-computed, already-cited verdict to a LOCAL model (Ollama) that
    ONLY rephrases it — it never adds a cause, number, or citation (strict prompt; see docs/RCA.md).
    Read-only; no device I/O. Needs the extra + a running local model: pip install iaiops[ollama].

    Args:
        verdict: An RCA verdict dict (e.g. the output of downtime_root_cause).
        base_url: Ollama server URL (default http://localhost:11434).
        model: Local model name (default 'llama3.1').
        provider: LLM provider (currently 'ollama').

    Returns dict: {provider, model, narration}.

    Example: rca_narrate(verdict=<downtime_root_cause output>, model="llama3.1").
    """
    kind = (provider or "").strip().lower()
    if kind not in SUPPORTED_PROVIDERS:
        raise ValueError(
            f"Unknown LLM provider '{provider}'. Supported: {', '.join(SUPPORTED_PROVIDERS)}."
        )
    if not isinstance(verdict, dict) or not verdict:
        raise ValueError("verdict is required (an RCA verdict dict, e.g. downtime_root_cause).")
    prov = get_provider(kind, base_url=base_url, model=model)
    narration = narrate_rca_verdict(verdict, prov)
    return {"provider": kind, "model": model, "narration": narration}
