"""Where a site actually stands on the path from a network to an answer.

Seven commands, in an order nobody was ever told:

    scan → endpoints in config → a point list per endpoint → what each point
    MEANS → collect → the answer (readiness / oee measure)

Every one of them existed. Nothing said which one you are on, so the honest
experience of this product was "read seven help texts and infer the sequence".

Two rules hold this together:

* **Derived, never remembered.** There is no onboarding state file. Every step's
  state is read back out of the store and ``config.yaml`` each time, so a site
  that edits its config by hand, or restores a backup, or does the steps out of
  order, gets a true answer instead of a stale one.
* **One next command.** Exactly one step is ``next``; the rest are waiting on it.
  A list of five things to do next is the same as no answer.

The path reports; it never advances itself. Contacts nothing.
"""

from __future__ import annotations

from typing import Any

from iaiops.core.onboard.model import STATE_DONE, STATE_NEXT, STATE_WAITING, OnboardPath, Step

#: Protocols whose point list can be asked FOR, and the command that asks.
#:
#: This started as five entries under a blanket sentence saying every other
#: protocol "has no point list to ask for". That sentence was false for five of
#: them — BACnet has an object list, MQTT has a topic tree, EtherCAT enumerates
#: its slaves, HART's dynamic variables are the device's variable set, and Modbus
#: ships register-map templates. Telling a site to type addresses in by hand
#: while the product can enumerate them is the same defect this module was built
#: to fix, pointed at the customer's afternoon.
_BROWSE: dict[str, str] = {
    "opcua": "iaiops opcua browse --endpoint {endpoint}",
    "ethernetip": "iaiops eip tags --endpoint {endpoint}",
    "eip": "iaiops eip tags --endpoint {endpoint}",
    "mtconnect": "iaiops mtconnect probe --endpoint {endpoint}",
    "iolink": "iaiops iolink ports --endpoint {endpoint}",
    "mqtt": "iaiops mqtt browse --endpoint {endpoint}",
    "ethercat": "iaiops ethercat slaves --endpoint {endpoint}",
    "hart": "iaiops hart dynamic --endpoint {endpoint}",
    "modbus": "iaiops modbus templates",
    # The only entry needing arguments a config cannot supply: BACnet addresses
    # a device by its network address and instance number, and both come from
    # `iaiops bacnet discover`. Rendered with the placeholders visible rather
    # than invented.
    "bacnet": "iaiops bacnet objects <address> <device_id> --endpoint {endpoint}",
}

#: Protocols with genuinely nothing to ask, each saying WHY in its own terms.
#: A per-protocol reason rather than one sentence, because the one sentence was
#: how five wrong claims travelled together — and because a protocol added later
#: must land in one of these two tables deliberately (there is a test).
_NO_BROWSE_REASONS: dict[str, str] = {
    "s7": (
        "an S7 CPU exposes no symbol table on the wire — the names live in the "
        "TIA/STEP7 project, not the PLC. Take the DB and offsets from the "
        "project and add them under `tags:`."
    ),
    "mc": (
        "MELSEC device memory (D/M/W...) has no symbol table on the wire. Take "
        "the device addresses from the GX Works project and add them under "
        "`tags:`."
    ),
    "fins": (
        "Omron memory areas (DM/CIO/W...) carry no symbol table on the wire. "
        "Take the addresses from the CX-Programmer project."
    ),
    "profinet": (
        "PROFINET DCP identifies STATIONS, not points, and this product does not "
        "speak the RT cyclic channel that carries process data at all. The points "
        "come from the engineering project, or from the device over a second "
        "protocol it also speaks."
    ),
    "secsgem": (
        "the SVID list IS discoverable (S1F11), but SECS/GEM has no CLI group "
        "yet — today it is reachable only through the "
        "`secsgem_list_status_variables` MCP tool."
    ),
    "bas": "a supervisory controller's point tree is behind its own API and credentials.",
    "ignition": "the gateway's tag tree is behind an API token.",
}


def _scan_count(db_path: Any) -> int:
    from iaiops.core.sink.scan_store import list_scans

    try:
        return len(list_scans(db_path, 50))
    except Exception:  # noqa: BLE001 — a store that will not open is "no scans yet"
        return 0


def _survey_step(scans: int) -> tuple[str, str, str]:
    if scans:
        return (
            STATE_DONE,
            f"{scans} scan(s) stored",
            "",
        )
    return (
        STATE_NEXT,
        "no scan has been stored",
        "iaiops scan plan --targets <cidr>",
    )


def _endpoint_step(facts: dict[str, Any], scans: int) -> tuple[str, str, str]:
    count = int(facts.get("endpoints") or 0)
    if count:
        return STATE_DONE, f"{count} endpoint(s) in config.yaml", ""
    if scans:
        return STATE_NEXT, "no endpoints in config.yaml", "iaiops onboard draft"
    return STATE_WAITING, "no endpoints in config.yaml", "iaiops onboard draft"


def _points_step(config: Any, facts: dict[str, Any]) -> tuple[str, str, str]:
    """Whether every configured endpoint has any points at all."""
    targets = tuple(getattr(config, "targets", ()) or ()) if config is not None else ()
    empty = [t for t in targets if not (getattr(t, "tags", ()) or ())]
    monitored = int(facts.get("monitored_tags") or 0)
    if targets and not empty:
        return STATE_DONE, f"{monitored} point(s) across {len(targets)} endpoint(s)", ""
    if not targets:
        return STATE_WAITING, "no endpoints yet, so no point list", ""
    first = empty[0]
    name = str(getattr(first, "name", ""))
    protocol = str(getattr(first, "protocol", ""))
    command = _BROWSE.get(protocol, "").format(endpoint=name)
    detail = (
        f"{len(empty)} of {len(targets)} endpoint(s) have no points — first: {name} ({protocol})"
    )
    if not command:
        reason = _NO_BROWSE_REASONS.get(
            protocol,
            # Unreachable while the coverage test holds; if it ever is reached,
            # say that nobody has decided, rather than asserting there is nothing.
            f"nobody has recorded whether {protocol} can be asked for a point list",
        )
        return STATE_NEXT, f"{detail}; {reason}", ""
    return STATE_NEXT, detail, command


def _meaning_step(config: Any, facts: dict[str, Any]) -> tuple[str, str, str]:
    """Whether anyone has said what the points MEAN.

    Deliberately reported as a state of its own rather than folded into the
    point list. Having points is a connection fact; knowing which one counts
    production is process knowledge, and the whole product refuses to guess it.
    """
    monitored = int(facts.get("monitored_tags") or 0)
    declared = dict(facts.get("oee_roles") or {})
    if not monitored:
        return STATE_WAITING, "no points to give meaning to yet", ""
    if declared:
        return (
            STATE_DONE,
            "declared: " + ", ".join(f"{role}={tag}" for role, tag in sorted(declared.items())),
            "",
        )
    return (
        STATE_NEXT,
        f"{monitored} point(s) configured, none declared as run_state / total_count / "
        "good_count / reject_count",
        "iaiops tags export sheet.csv",
    )


def _collect_step(facts: dict[str, Any]) -> tuple[str, str, str]:
    store = dict(facts.get("store") or {})
    samples = int(store.get("samples") or 0)
    collectable = list(facts.get("collectable_endpoints") or ())
    if samples:
        span = store.get("span_days") or 0.0
        return (
            STATE_DONE,
            f"{samples} sample(s), {store.get('tags', 0)} tag(s), {span:.1f} day span",
            "",
        )
    if not collectable:
        return STATE_WAITING, "no endpoint that can be sampled on a schedule yet", ""
    return (
        STATE_NEXT,
        "the local store holds no samples",
        f"iaiops collect run {collectable[0]} --duration 30m",
    )


def _answer_step(facts: dict[str, Any]) -> tuple[str, str, str]:
    store = dict(facts.get("store") or {})
    if not int(store.get("samples") or 0):
        return STATE_WAITING, "nothing collected yet", ""
    return (
        STATE_DONE,
        "there is history to ask questions of",
        "",
    )


def assess_path(config: Any = None, db_path: Any = None) -> OnboardPath:
    """Report the site's position on the path, and the single next command."""
    from iaiops.core.readiness.assess import gather_facts

    facts = gather_facts(config, db_path)
    if config is None:
        try:
            from iaiops.core.runtime.config import load_config

            config = load_config()
        except Exception:  # noqa: BLE001 — an unconfigured site is the state to report
            config = None

    scans = _scan_count(db_path)
    raw = [
        (
            "survey",
            "Find what is on the network",
            "You cannot configure what you have not found, and a plant network is "
            "never what the drawing says.",
            _survey_step(scans),
        ),
        (
            "endpoints",
            "Turn what was found into endpoints",
            "The scan already established how to reach each device. Typing it back "
            "in by hand is where forty devices become four.",
            _endpoint_step(facts, scans),
        ),
        (
            "points",
            "Get each endpoint's point list",
            "Which points exist is a question the device can answer — for the "
            "protocols where a point list is a thing at all.",
            _points_step(config, facts),
        ),
        (
            "meaning",
            "Say what the points MEAN",
            "The one step nothing can do for you. Which tag counts production is "
            "process knowledge, and a wrong guess yields a plausible OEE — worse "
            "than an error.",
            _meaning_step(config, facts),
        ),
        (
            "collect",
            "Collect some history",
            "Every question worth asking is about change over time.",
            _collect_step(facts),
        ),
        (
            "answers",
            "Ask the questions",
            "`iaiops readiness` says what this site can now run; `iaiops oee "
            "measure` is usually the first one worth running.",
            _answer_step(facts),
        ),
    ]

    # The FIRST not-done step owns the cursor; everything after it that is not
    # done waits. A step that is genuinely done stays done even when it sits
    # after the cursor — someone who hand-wrote config.yaml before ever scanning
    # has real endpoints, and telling them otherwise to keep the sequence tidy
    # would be a lie in the direction that makes the tool look more necessary.
    steps: list[Step] = []
    claimed = False
    for key, label, why, (state, detail, command) in raw:
        if state == STATE_DONE:
            resolved = STATE_DONE
        elif not claimed:
            resolved = STATE_NEXT
            claimed = True
        else:
            resolved = STATE_WAITING
        steps.append(
            Step(
                key=key,
                label=label,
                detail=detail,
                state=resolved,
                # Every step keeps its command, including the ones still waiting.
                # Blanking them here was tidier and hid a bug: the only command a
                # test could see was the one for whatever state the fixture
                # happened to be in, so `collect run --endpoint`, which does not
                # parse, was never checked by the test written to check it.
                # Showing one command at a time is a rendering decision, and it
                # belongs to the renderer (D17).
                command=command,
                why=why,
            )
        )

    notes: list[str] = []
    if facts.get("config_error"):
        notes.append(
            f"config.yaml did not load ({facts['config_error']}) — every step below "
            "that reads it is reporting on an empty config, not on your site."
        )
    if facts.get("role_conflict"):
        notes.append(f"role conflict in config.yaml: {facts['role_conflict']}")
    return OnboardPath(steps=tuple(steps), notes=tuple(notes))


__all__ = ["assess_path"]
