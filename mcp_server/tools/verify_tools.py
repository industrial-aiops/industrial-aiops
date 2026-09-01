"""Self-verification MCP tool (READ-ONLY) — the determinism claim, executed.

The one thing an agent front-end should be able to demonstrate about its own
engine rather than assert: that the numbers it reports come out of deterministic
Python, not out of a model, and that running the same data again gives the same
bytes. Pure computation over a pinned in-repo dataset — no device, no store, and
the socket API raises for the duration, so it is safe on any network and needs
none.
"""

from typing import Any

from iaiops.core.governance import governed_tool
from mcp_server._shared import mcp, tool_errors


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def verify_determinism(subprocesses: bool = True) -> dict[str, Any]:
    """[READ][risk=low] Prove this engine's analysis is reproducible without a model.

    Runs a named suite of analyses (availability, production counts, the Six Big
    Losses, ISA-18.2 alarm load, control charts, the conservative baseline, the
    RCA copilot) over a pinned reference dataset, canonically encodes each result
    and digests it — twice in this process and, with ``subprocesses``, once more
    in each of two fresh interpreters started at different PYTHONHASHSEED values.
    That last arm is the one that catches a set or dict iteration order reaching a
    result; a single run never can. The socket API raises throughout, so a
    computation that reached for a device or a hostname fails here rather than
    quietly succeeding on a machine that happens to be online. ``sys.modules`` is
    checked afterwards for any model library — empty is the guarantee.

    Use it to answer "how do I know your AI didn't make this number up": the
    answer is that no model is in the path, and here is the SHA-256 that says so,
    reproducible on the customer's own box. Read-only; nothing is written unless
    the CLI (`iaiops verify determinism --out record.json`) is used to save the
    signable record for a validation file.

    Args:
        subprocesses: Also re-run in two fresh interpreters at fixed, different
            hash seeds (default True; adds roughly a second).

    Returns dict: {check, result:{verdict ('reproducible'|'not_reproducible'),
        suite_digest, dataset:{name, revision, digest}, checks:[{name, covers,
        digest}], arms:[{arm, suite_digest, matches_first_arm}], arms_disagreeing,
        model_modules_loaded, network}, context:{iaiops_version, python, platform,
        generated_at, ...}, note}. ``result`` is identical between runs; ``context``
        is not — it records when and where this run happened.

    Example: verify_determinism().
    """
    from iaiops.core.verify.determinism import run_determinism_check

    return run_determinism_check(subprocesses=subprocesses)
