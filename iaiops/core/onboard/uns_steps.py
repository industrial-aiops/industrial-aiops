"""The UNS journey's own steps: connect, audit the namespace, choose points.

Split from ``path.py``, which grades both journeys and resolves the cursor. Nothing
here contacts a broker — every judgement is made from ``config.yaml`` and the
namespace audits ``uns-live-audit`` stored, and each one says what it could not
establish rather than rounding it up to B1.
"""

from __future__ import annotations

import math
import shlex
from datetime import UTC, datetime
from typing import Any

from iaiops.core.onboard.model import STATE_DONE, STATE_NEXT, STATE_WAITING


def _name(target: Any) -> str:
    return str(getattr(target, "name", ""))


def _audit_command(target: Any) -> str:
    """The audit that can actually establish B1.

    Printed without a naming standard, this ran with no allowed roots and a minimum
    depth of 0, so two of the six checks could not fire and "clean" was largely a
    product of the defaults the tool itself suggested. The roots and depth ARE the
    site's naming standard, so they are placeholders to fill, not values to guess.
    The topic filter is the endpoint's own, so the audit describes what this
    endpoint subscribes to.
    """
    if target is None:
        name, topic, window = "<endpoint>", "'#'", 30
    else:
        name = shlex.quote(_name(target))
        topic = shlex.quote(str(getattr(target, "topic", "") or "#"))
        # At least one publish interval as the site itself stated it: a window
        # shorter than stale_after_s can miss a topic entirely and still read clean.
        window = max(30, math.ceil(_stale_after(target)))
    return (
        f"iaiops mqtt uns-live-audit --endpoint {name} --topic {topic} "
        f"--root <root> --min-segments <depth> --duration-s {window}"
    )


def _age(stamp: str, now: datetime) -> str:
    try:
        then = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return "at an unrecorded time"
    if then.tzinfo is None:
        then = then.replace(tzinfo=UTC)
    seconds = max(0.0, (now - then).total_seconds())
    if seconds < 3600:
        return f"{int(seconds // 60)} min ago"
    if seconds < 86400:
        return f"{int(seconds // 3600)} h ago"
    return f"{int(seconds // 86400)} day(s) ago"


def _instant(stamp: str) -> datetime:
    try:
        then = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return datetime.min.replace(tzinfo=UTC)
    return then if then.tzinfo else then.replace(tzinfo=UTC)


def _stale_after(target: Any) -> float:
    try:
        return float(getattr(target, "stale_after_s", 0) or 0)
    except (TypeError, ValueError):
        return 0.0


def _connect_step(brokers: tuple[Any, ...]) -> tuple[str, str, str]:
    """A broker endpoint that collection can actually use.

    No command advances this one: it is a config edit, and the broker address is
    the one fact only the site has.
    """
    if not brokers:
        return (
            STATE_NEXT,
            "no broker endpoint in config.yaml — add one with protocol: mqtt, host, "
            'port, topic ("spBv1.0/#" for Sparkplug) and stale_after_s. Store the '
            "password with `iaiops secret set <endpoint>`, never in the file.",
            "",
        )
    hostless = [t for t in brokers if not str(getattr(t, "host", "") or "").strip()]
    if hostless:
        return (
            STATE_NEXT,
            f"{len(hostless)} of {len(brokers)} broker endpoint(s) have no host — first: "
            f"{_name(hostless[0])}. Collection refuses an endpoint with no broker to "
            "connect to; add host (and port) in config.yaml.",
            "",
        )
    missing = [t for t in brokers if _stale_after(t) <= 0]
    if missing:
        return (
            STATE_NEXT,
            f"{len(missing)} of {len(brokers)} broker endpoint(s) have no usable "
            f"stale_after_s — first: {_name(missing[0])}. Collection refuses without it: "
            "a value that stopped updating and one that is simply constant look "
            "identical on the wire, so only the site knows how often a point is published.",
            "",
        )
    return (
        STATE_DONE,
        f"{len(brokers)} broker endpoint(s), each with a host and stale_after_s set",
        "",
    )


#: How one broker's stored audit stands against its endpoint's CURRENT config.
#: Only ``clean`` can make a site B1 and only ``messy`` (a sprawling verdict) makes
#: it B2; every other standing leaves the fork undecided, each with its own reason.
_MISSING, _UNREADABLE, _MISMATCH, _MESSY, _REVIEW, _WEAK, _CLEAN = (
    "missing",
    "unreadable",
    "mismatch",
    "messy",
    "review",
    "weak",
    "clean",
)


def _audit_standing(target: Any, record: Any) -> tuple[str, str]:
    """``(standing, why)`` for one broker endpoint's stored audit."""
    from iaiops.core.sink.uns_audit_store import broker_id

    if record is None:
        return _MISSING, "never audited"
    if record.error:
        return (
            _UNREADABLE,
            f"the stored audit could not be read ({record.error}) — this is about the "
            "file, not the namespace",
        )
    here = broker_id(target)
    if not record.broker:
        return _MISMATCH, "the stored audit does not record which broker it came from"
    if record.broker != here:
        return _MISMATCH, f"audited on {record.broker}, but the endpoint now points at {here}"
    configured = str(getattr(target, "topic", "") or "#")
    whole_tree = record.topic_filter == "#" and configured != "#"
    if record.topic_filter != configured and not whole_tree:
        return (
            _MISMATCH,
            f"audited topic filter {record.topic_filter or '(none recorded)'!r} does not "
            f"cover the endpoint's {configured!r}",
        )
    if whole_tree and record.verdict != "clean":
        # Clean over the whole broker is clean over any part of it. Findings over the
        # whole broker may all sit outside this endpoint's filter, so they cannot
        # make THIS endpoint's namespace B2.
        return (
            _MISMATCH,
            f"audited the whole broker ('#') and found {record.sprawl_findings} finding(s), "
            f"which may lie outside the endpoint's {configured!r} — re-audit with its own filter",
        )
    if record.verdict == "sprawling":
        return _MESSY, f"sprawling ({record.sprawl_findings} finding(s))"
    if record.verdict != "clean":
        return (
            _REVIEW,
            f"{record.verdict} ({record.sprawl_findings} finding(s)) — heuristics that can "
            "fire on a sound tree (a Sparkplug STATE topic, one leaf name under many "
            "parents), so they are findings to review, not a verdict on governance",
        )
    if record.capture_capped:
        cap = (
            f"hit its {record.max_msgs}-message cap"
            if record.max_msgs
            else "did not record its message cap"
        )
        return (
            _WEAK,
            f"clean, but the capture {cap} — it may have seen only part of the "
            "namespace, and clean on part of it is not clean",
        )
    if not record.naming_standard:
        return (
            _WEAK,
            "clean, but audited without a naming standard (--root and --min-segments), "
            "so two of the six checks could not fire",
        )
    interval = _stale_after(target)
    if record.duration_s < interval:
        return (
            _WEAK,
            f"clean, but the capture listened {record.duration_s}s while points may publish "
            f"only every {interval:g}s (stale_after_s) — a topic that did not publish in "
            "the window was never seen",
        )
    return _CLEAN, f"clean over {record.topic_count} topic(s)"


def _namespace_step(
    brokers: tuple[Any, ...], audits: dict[str, Any], now: datetime
) -> tuple[str, str, str]:
    """Whether each broker's namespace audited clean against its standard.

    Done ONLY when every broker is clean. A B2 namespace keeps this step open:
    governance is the work, and a path that reached "every step done" on a site
    whose audit had just come back sprawling contradicted its own note.
    """
    if not brokers:
        return STATE_WAITING, "no broker endpoint to audit yet", _audit_command(None)
    standings = [(t, *_audit_standing(t, audits.get(_name(t)))) for t in brokers]
    for target, standing, why in standings:
        if standing == _CLEAN:
            continue
        record = audits.get(_name(target))
        dated = record is not None and not record.error and record.audited_at
        age = f", audited {_age(record.audited_at, now)}" if dated else ""
        if standing == _MISSING:
            never = sum(1 for _, s, _ in standings if s == _MISSING)
            detail = (
                f"{never} of {len(brokers)} broker endpoint(s) never audited — first: "
                f"{_name(target)}. onboard contacts nothing, so it knows only what a "
                "stored audit says; until one exists this site is neither B1 nor B2."
            )
        elif standing == _MESSY:
            detail = (
                f"{_name(target)}: {why}{age}. This is B2 — governance is the work: fix "
                "what the audit flagged, then re-audit. This step stays open until an "
                "audit comes back clean."
            )
        elif standing == _REVIEW:
            detail = (
                f"{_name(target)}: {why}{age}. Review them: fix and re-audit, or — if the "
                "structure is intended — re-audit with --min-segments and "
                "--max-leaf-parents set to your standard. Until then this site is neither "
                "B1 nor B2."
            )
        else:
            detail = f"{_name(target)}: {why}{age}. Re-audit so the fork can be decided."
        return STATE_NEXT, detail, _audit_command(target)
    parts = [
        f"{_name(t)}: {why}, audited {_age(audits[_name(t)].audited_at, now)}"
        for t, _, why in standings
    ]
    return STATE_DONE, "; ".join(parts), ""


def _uns_subtrack(
    brokers: tuple[Any, ...], audits: dict[str, Any], now: datetime
) -> tuple[str, str, Any]:
    """``(B1|B2|"", explanation, the broker a B2 note is about)`` — never guessed."""
    if not brokers:
        return "", "no broker endpoint configured yet", None
    standings = [(t, *_audit_standing(t, audits.get(_name(t)))) for t in brokers]
    kinds = {s for _, s, _ in standings}
    messy = [(t, why) for t, s, why in standings if s == _MESSY]
    if messy:
        # Findings are findings even while another broker is unaudited.
        target, why = messy[0]
        age = _age(audits[_name(target)].audited_at, now)
        return (
            "B2",
            f"B2 — the namespace needs governance ({_name(target)}: {why}, audited {age})",
            target,
        )
    if kinds & {_MISSING, _UNREADABLE, _MISMATCH, _REVIEW}:
        return (
            "",
            "the namespace audit does not yet decide every broker endpoint (never audited, "
            "unreadable, taken on a different broker or filter, or findings still to "
            "review) — B1 or B2 is unknown until it does",
            None,
        )
    weak = [(t, why) for t, s, why in standings if s == _WEAK]
    if weak:
        target, why = weak[0]
        return "", f"B1 is not established — {_name(target)}: {why}", None
    # Compared as instants: ISO strings with different UTC offsets do not sort by time.
    oldest = min((audits[_name(t)].audited_at for t in brokers), key=_instant)
    return (
        "B1",
        "B1 — every broker namespace audited clean against its naming standard "
        f"(oldest audit {_age(oldest, now)})",
        None,
    )


def _uns_points_step(brokers: tuple[Any, ...]) -> tuple[str, str, str]:
    """Which points to monitor — listed by the broker, written into tags: by hand."""
    if not brokers:
        return STATE_WAITING, "no broker endpoint yet, so no points", ""
    empty = [t for t in brokers if not (getattr(t, "tags", ()) or ())]
    if not empty:
        count = sum(len(getattr(t, "tags", ()) or ()) for t in brokers)
        return STATE_DONE, f"{count} point(s) across {len(brokers)} broker endpoint(s)", ""
    first = empty[0]
    topic = str(getattr(first, "topic", "") or "#")
    sparkplug = topic.startswith("spBv1.0")
    name = shlex.quote(_name(first))
    if sparkplug:
        command = f"iaiops mqtt live-schema --endpoint {name} --duration-s 30"
        ref_rule = (
            "a Sparkplug ref is `group/edge[/device]:metric`, with the node exactly "
            "as live-schema prints it"
        )
    else:
        command = f"iaiops mqtt browse --endpoint {name} --topic {shlex.quote(topic)}"
        ref_rule = "a plain-MQTT ref is the topic itself"
    return (
        STATE_NEXT,
        f"{len(empty)} of {len(brokers)} broker endpoint(s) have no points — first: "
        f"{_name(first)}. Nothing turns the listing into `tags:` yet, so write them "
        f"by hand: {ref_rule}.",
        command,
    )


def _governance_note(target: Any) -> str:
    """What B2 governance can use on THIS broker.

    Both schema commands read Sparkplug BIRTH messages only. Offered to a plain-MQTT
    namespace, `live-schema` returned an empty schema and `uns-live-drift` then
    reported "no change" forever — a watch that can never fire, presented as the
    governance the site needed.
    """
    head = (
        "This site is on B2: the namespace did not audit clean, so governance is the "
        "work, not a later step. Fix the naming the audit flagged, then re-audit."
    )
    topic = str(getattr(target, "topic", "") or "")
    if not topic.startswith("spBv1.0"):
        return (
            f"{head} There is no schema-drift watch for plain MQTT here: "
            "`live-schema` and `uns-live-drift` read Sparkplug BIRTH messages, and a "
            "plain topic tree has none — they would report no drift whatever changed."
        )
    quoted = shlex.quote(_name(target))
    return (
        f"{head} Keep a schema baseline — save the `schema` field of "
        f"`iaiops mqtt live-schema --endpoint {quoted}` to baseline.json — then watch "
        "for breaking changes with "
        f"`iaiops mqtt uns-live-drift --endpoint {quoted} --baseline baseline.json`."
    )


__all__: list[str] = []  # internal to the onboard package; path.py is the API
