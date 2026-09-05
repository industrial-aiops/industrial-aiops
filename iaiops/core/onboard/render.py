"""Render a :class:`~iaiops.core.onboard.model.Draft` as pasteable YAML.

The output is a fragment, not a file: it is meant to be merged into an existing
``config.yaml`` whose comments a site wrote for itself. ``iaiops tags apply``
made the same choice for the same reason, and the two now behave alike — every
write to ``config.yaml`` in this product is made by a person.

Two rules the renderer holds:

* A field the scan did not establish is emitted as a **comment**, never as a
  value. Pasting the block therefore cannot enable an unjustified setting, and
  deleting the comment is a deliberate act.
* Nothing is quietly omitted. An omitted field takes the protocol default in
  silence, which is how a Modbus gateway ends up read at unit 1.
"""

from __future__ import annotations

import textwrap
from typing import Any

from iaiops.core.onboard.model import Draft, DraftEndpoint

#: Wrapped narrow enough to survive an 80-column terminal WITHOUT the renderer
#: on the other end re-wrapping it. A comment line that gets re-wrapped loses its
#: leading ``#`` on the continuation, and the YAML someone pastes then fails to
#: parse — the draft's whole job is to be pasted.
_WIDTH = 74


def _scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return str(value)
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"') + '"'


def _comment(text: str, indent: str) -> list[str]:
    body = " ".join(str(text).split())
    if not body:
        return []
    width = max(_WIDTH - len(indent) - 2, 30)
    return [f"{indent}# {line}" for line in textwrap.wrap(body, width)]


def _endpoint_block(endpoint: DraftEndpoint) -> list[str]:
    lines = [f"  - name: {_scalar(endpoint.name)}"]
    lines += _comment(
        f"rename this: the address is what was observed, not what the box does. "
        f"{endpoint.evidence}".strip(),
        "    ",
    )
    lines.append(f"    protocol: {_scalar(endpoint.protocol)}")
    for field in endpoint.fields:
        if field.established:
            lines.append(f"    {field.name}: {_scalar(field.value)}")
            lines += _comment(f"observed: {field.observed}", "    ")
            if field.caution:
                lines += _comment(f"but: {field.caution}", "    ")
        else:
            lines += _comment(f"{field.name}: NOT ESTABLISHED BY THE SCAN.", "    ")
            lines += _comment(field.caution, "    ")
    lines.append("    tags: []")
    lines += _comment(
        "empty on purpose. A scan finds devices; which point on this device means "
        "run state or good count is process knowledge nobody here has. Add the "
        "points you want, then run `iaiops tags export sheet.csv` to confirm what "
        "each one means.",
        "    ",
    )
    return lines


def render_yaml(draft: Draft) -> str:
    """The ``endpoints:`` fragment, with everything the scan could not settle."""
    header = [
        f"# iaiops onboard draft — from scan {draft.scan_id or '(unstored)'}"
        + (f", site {draft.site}" if draft.site else ""),
        f"# scanned {draft.scanned_at}" if draft.scanned_at else "",
        "#",
        "# NOTHING HAS BEEN WRITTEN. Merge what you agree with into config.yaml.",
        "# Every value below names what the scan observed to justify it; every",
        "# commented field is one the scan could NOT settle — read it before you",
        "# uncomment it, because a plausible default is what makes a wrong reading",
        "# look right.",
        "#",
    ]
    header = [line for line in header if line != ""]

    pastable = draft.pastable
    body: list[str] = []
    if pastable:
        body.append("endpoints:")
        for endpoint in pastable:
            body += _endpoint_block(endpoint)
            body.append("")
    else:
        body += _comment(
            "No endpoint could be drafted from this scan. Either no protocol was "
            "confirmed, or every host it confirmed is already in config.yaml.",
            "",
        )

    already = [e for e in draft.endpoints if e.already_configured]
    tail: list[str] = []
    if already:
        tail.append("")
        tail += _comment(
            "Already in config.yaml, so not offered again: "
            + ", ".join(f"{e.name} ({e.ip})" for e in already)
            + ". A re-scan must not hand you a block that replaces an endpoint a "
            "site has already tuned.",
            "",
        )
    if draft.skipped:
        tail.append("")
        tail += _comment("Seen and not drafted:", "")
        for host in draft.skipped:
            tail += _comment(f"{host.ip} — {host.reason}", "")
    if draft.limits:
        tail.append("")
        tail += _comment("What this draft cannot contain:", "")
        for limit in draft.limits:
            tail += _comment(limit, "")
    return "\n".join([*header, "", *body, *tail]).rstrip() + "\n"


__all__ = ["render_yaml"]
