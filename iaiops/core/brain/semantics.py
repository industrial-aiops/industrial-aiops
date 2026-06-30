"""Shared OT tag semantics: class inference + alias canonicalization (pure).

This is the SINGLE home for the heuristic that turns a cryptic tag/browse name
into a semantic class (``temperature`` / ``pressure`` / ``alarm`` …) and the
scheme that canonicalizes an asset path + tag name into a clean dotted alias.

Both the OPC-UA discovery layer (:mod:`iaiops.connectors.opcua.discovery`, which
re-exports ``classify_tag`` / ``suggest_alias`` for API stability) and the
cross-protocol asset model (:mod:`iaiops.core.brain.asset_model`) import from
here so the SAME classes + alias rules apply everywhere — no divergent fork.

Pure, no I/O — fully unit-testable.
"""

from __future__ import annotations

# Semantic class → name substrings (checked lowercased, first match wins).
# Ordered so more-specific classes (setpoint, runtime) precede generic ones.
_CLASS_HINTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("setpoint", ("setpoint", "_sp", "sptval", "target")),
    ("alarm", ("alarm", "alert", "fault", "trip", "fail")),
    ("state", ("state", "status", "running", "ready", "mode")),
    # Physical quantities precede the generic 'command' class so a name like
    # "Startup_Temperature" classifies by its quantity, not the bare verb.
    ("temperature", ("temp", "temperature", "_t_", "degc", "degf")),
    ("pressure", ("press", "pressure", "_p_", "bar", "psi")),
    ("flow", ("flow", "_fl_", "lpm", "gpm", "m3h")),
    ("level", ("level", "_lv_", "tanklvl")),
    ("speed", ("speed", "rpm", "freq", "hz", "velocity")),
    ("torque", ("torque",)),
    ("power", ("power", "_kw", "watt", "_pwr")),
    ("energy", ("energy", "kwh", "consumption")),
    ("current", ("current", "amp", "_i_")),
    ("voltage", ("voltage", "volt", "_v_")),
    ("vibration", ("vibration", "vib", "accel")),
    ("position", ("position", "_pos", "encoder")),
    ("counter", ("count", "counter", "total", "qty")),
    ("runtime", ("runtime", "hours", "uptime", "elapsed")),
    ("command", ("command", "cmd", "start", "stop", "enable")),
)


def classify_tag(browse_name: str) -> str:
    """Infer a semantic class for a tag from its name (heuristic).

    Returns ``other`` when nothing matches rather than guessing — honest over a
    confident-but-wrong label that downstream tooling would trust.
    """
    text = str(browse_name or "").lower()
    for klass, hints in _CLASS_HINTS:
        if any(h in text for h in hints):
            return klass
    return "other"


def alias_segment(text: str) -> str:
    """Lowercase a path/name segment to an alias-safe token (alnum/_)."""
    out = "".join(c if (c.isalnum() or c == "_") else "_" for c in str(text).lower())
    return out.strip("_") or "unknown"


def suggest_alias(asset_path: str, browse_name: str) -> str:
    """Propose a clean canonical alias ``<asset>.<tag>`` (dot-delimited, advisory)."""
    parts = [alias_segment(p) for p in str(asset_path or "").split("/") if p]
    tag = alias_segment(browse_name)
    return ".".join([*parts, tag]) if parts else tag


__all__ = ["classify_tag", "alias_segment", "suggest_alias"]
