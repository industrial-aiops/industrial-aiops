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

#: Protocols whose point list can be asked FOR, and the command that asks. The
#: rest are not an omission: a Modbus register map is not discoverable over
#: Modbus, and naming a command that cannot exist would send someone looking for
#: it on a plant floor.
_BROWSE: dict[str, str] = {
    "opcua": "iaiops opcua browse --endpoint {endpoint}",
    "ethernetip": "iaiops eip tags --endpoint {endpoint}",
    "eip": "iaiops eip tags --endpoint {endpoint}",
    "mtconnect": "iaiops mtconnect probe --endpoint {endpoint}",
    "iolink": "iaiops iolink ports --endpoint {endpoint}",
}

_NO_BROWSE = (
    "this protocol has no point list to ask for — a register/address map comes "
    "from the vendor's document, not from the wire. Add the addresses you care "
    "about under `tags:`."
)


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
        return STATE_NEXT, f"{detail}; {_NO_BROWSE}", ""
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
