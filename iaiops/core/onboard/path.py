"""Where a site actually stands on the path from its data to an answer.

There are two journeys, and they start in different places:

    devices — no UNS yet (or one being built): scan → endpoints → a point list
              per endpoint → what each point MEANS → collect → the answer
    uns     — the data already flows through an MQTT/UNS broker: connect →
              audit the namespace → choose the points → what they MEAN →
              collect → the answer

A UNS site told to "scan the network first" is being sent the long way round
to a dead end: a scan never identifies MQTT (it is deliberately left out of
identification, see ``discovery/identify.NO_SAFE_IDENTIFY``). The journey is
therefore derived before any step is graded. On the UNS journey the namespace
audit forks it again — **B1**, a namespace that audited clean, and **B2**, one
that did not, where governance is the work rather than a later step.

Three rules hold this together:

* **Derived, never remembered.** There is no onboarding state file. The journey
  comes from config.yaml, every step's state from the store and config.yaml,
  and B1/B2 from a stored namespace audit — each read back every time, so a site
  that edits its config by hand or restores a backup gets a true answer.
* **One next command.** Exactly one step is ``next``. The only exception is a
  genuine QUESTION the files cannot answer — nothing is configured, or both kinds
  of endpoint are — and then the path offers the two answers and picks neither.
* **Contacts nothing.** Which is why B1/B2 needs a stored audit, and says so
  while there is none.
"""

from __future__ import annotations

import shlex
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from iaiops.core.onboard.model import (
    STATE_DONE,
    STATE_NEXT,
    STATE_WAITING,
    TRACK_DEVICES,
    TRACK_MIXED,
    TRACK_UNDECIDED,
    TRACK_UNS,
    OnboardPath,
    Step,
)
from iaiops.core.onboard.uns_steps import (
    _connect_step,
    _governance_note,
    _name,
    _namespace_step,
    _uns_points_step,
    _uns_subtrack,
)

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


#: Above this, the count is reported as "at least N" — `list_scans` takes a
#: limit, and a site with 400 scans was told it had 50.
_SCAN_LIST_LIMIT = 200


def _scan_count(db_path: Any) -> tuple[int, str]:
    """How many scans are stored, and why we could not tell if we could not.

    Returning 0 for an unreadable store was wrong in the direction this repo
    keeps producing: a corrupt file, a permission error or a `--db` typo all
    became the assertion "no scan has been stored", and the remedy offered was
    to go scan a live plant network again. A tool-side failure must not be
    reported as a fact about the site's work.
    """
    from iaiops.core.sink.scan_store import list_scans

    try:
        return len(list_scans(db_path, _SCAN_LIST_LIMIT)), ""
    except Exception as exc:  # noqa: BLE001 — the store is not ours to trust
        return 0, f"{type(exc).__name__}: {exc}"


def _survey_step(scans: int, store_error: str) -> tuple[str, str, str]:
    """The command has to be the one that ADVANCES the step.

    This printed `iaiops scan plan --targets <cidr>`, which is a preview: it
    emits nothing and, by design, stores nothing. So the first command the
    product gave a first-time site could never satisfy the step it was printed
    for — run it, re-run `onboard status`, get the identical output forever.

    `scan run` is named here because it is what stores a scan; `scan plan` is
    named in the detail, because previewing first is the posture and an operator
    signs that output before anything touches the network.
    """
    if store_error:
        return (
            STATE_NEXT,
            f"the scan store could not be read ({store_error}) — this is about the "
            "store, not about your site; check the path you passed to --db",
            "",
        )
    if scans:
        at_least = "at least " if scans >= _SCAN_LIST_LIMIT else ""
        return STATE_DONE, f"{at_least}{scans} scan(s) stored", ""
    return (
        STATE_NEXT,
        "no scan has been stored — preview it first with `iaiops scan plan "
        "--targets <cidr>`, which sends nothing and is the output an operator "
        "signs; `scan run` is what stores the result",
        "iaiops scan run --targets <cidr> --approved-by <you>",
    )


def _endpoint_step(facts: dict[str, Any], scans: int, others: int = 0) -> tuple[str, str, str]:
    count = int(facts.get("endpoints") or 0)
    if count:
        return STATE_DONE, f"{count} endpoint(s) in config.yaml", ""
    # A file that will not parse is not an empty file. Reporting "no endpoints in
    # config.yaml" as a fact told a site its existing work did not exist, and
    # then offered to draft more endpoints to paste into the file that is broken.
    error = str(facts.get("config_error") or "")
    if error:
        return (
            STATE_NEXT,
            f"config.yaml did not parse ({error}) — this says nothing about how "
            "many endpoints it defines. Fix the file first; drafting more into a "
            "file that will not load cannot help",
            "",
        )
    # "no endpoints in config.yaml" was false on a site whose endpoints all belong
    # to the OTHER journey: a UNS site forced onto this one was told it had none,
    # then offered a draft of devices that a scan would find instead of its broker.
    missing = (
        f"no device endpoints in config.yaml ({others} broker endpoint(s) belong to "
        "the uns journey)"
        if others
        else "no endpoints in config.yaml"
    )
    if scans:
        return STATE_NEXT, missing, "iaiops onboard draft"
    return STATE_WAITING, missing, "iaiops onboard draft"


def _points_step(config: Any, facts: dict[str, Any]) -> tuple[str, str, str]:
    """Whether every configured endpoint has any points at all."""
    targets = tuple(getattr(config, "targets", ()) or ()) if config is not None else ()
    empty = [t for t in targets if not (getattr(t, "tags", ()) or ())]
    monitored = int(facts.get("monitored_tags") or 0)
    if targets and not empty:
        return STATE_DONE, f"{monitored} point(s) across {len(targets)} endpoint(s)", ""
    if not targets:
        return STATE_WAITING, "no endpoints yet, so no point list", ""
    # Prefer an endpoint whose point list we can actually ASK for. Taking
    # `empty[0]` meant a config whose first entry was S7 withheld `opcua browse`
    # for the endpoint two lines below it — advice that changes when you reorder
    # a YAML file is not advice derived from the site.
    first = next((e for e in empty if str(getattr(e, "protocol", "")) in _BROWSE), empty[0])
    name = str(getattr(first, "name", ""))
    protocol = str(getattr(first, "protocol", ""))
    command = _BROWSE.get(protocol, "").format(endpoint=shlex.quote(name))
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
    required = [str(r) for r in (facts.get("oee_required_roles") or ())]
    if not monitored:
        return STATE_WAITING, "no points to give meaning to yet", ""

    # Two tags claiming one role makes `roles_present` raise, and `gather_facts`
    # then discards that WHOLE endpoint's roles — so a site that had declared a
    # perfectly good run_state was told it had declared nothing, and sent to the
    # sheet, which does not surface the conflict either.
    conflict = str(facts.get("role_conflict") or "")
    if conflict:
        return (
            STATE_NEXT,
            "config.yaml claims one role twice, so none of that endpoint's roles "
            f"could be read: {conflict}",
            "",
        )

    shown = ", ".join(f"{role}={tag}" for role, tag in sorted(declared.items()))
    missing = [role for role in required if role not in declared]
    if declared and not missing:
        return STATE_DONE, f"declared: {shown}", ""
    if declared:
        # Graded on "did somebody type a role: anywhere", this reported DONE on a
        # site declaring only good_count — and the header then said all six steps
        # were done while `oee measure` refused for want of the two roles it
        # requires. The completion story flattered the tool.
        return (
            STATE_NEXT,
            f"declared: {shown} — still missing {', '.join(missing)}, which "
            "`oee measure` requires before it reports anything",
            "iaiops tags export sheet.csv",
        )
    return (
        STATE_NEXT,
        f"{monitored} point(s) configured, none declared. "
        f"{' and '.join(required)} are the two `oee measure` requires; good_count "
        "and reject_count are optional and add the Quality factor",
        "iaiops tags export sheet.csv",
    )


def _collect_step(facts: dict[str, Any]) -> tuple[str, str, str]:
    store = dict(facts.get("store") or {})
    if store.get("error"):
        # The store, not the site — the same rule as an unreadable scan store.
        return (
            STATE_NEXT,
            f"the sample store could not be read ({store['error']}) — this is about "
            "the store, not the site; nothing can be said about collection until it can",
            "",
        )
    samples = int(store.get("samples") or 0)
    collectable = list(facts.get("collectable_endpoints") or ())
    if samples:
        span = store.get("span_days") or 0.0
        return (
            STATE_DONE,
            f"{samples} sample(s), {store.get('tags', 0)} tag(s), {span:.1f} day span",
            "",
        )
    if not collectable and not int(facts.get("endpoints") or 0):
        # Nothing configured on this journey is not "this build cannot sample it":
        # a broker-only site shown the devices journey was told its (collectable)
        # protocol had no sampler.
        return STATE_WAITING, "no endpoint on this journey yet, so nothing to collect", ""
    if not collectable:
        # "no endpoint that can be sampled on a schedule YET" was false twice
        # over: nothing the site does will make an MTConnect agent collectable,
        # and the limit is this build's, not theirs. It also parked the path on
        # this step permanently, with no command and no explanation.
        from iaiops.core.collect.reader import collectable_protocols

        return (
            STATE_WAITING,
            "none of the configured protocols has a scheduled sampler in this "
            "build — a limit here, not something missing at your site. Continuous "
            f"collection works for: {', '.join(collectable_protocols())}",
            "",
        )
    return (
        STATE_NEXT,
        "the local store holds no samples",
        f"iaiops collect run {shlex.quote(str(collectable[0]))} --duration 30m",
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


_TRACK_AUTO = "auto"
_BROKER_PROTOCOLS = frozenset({"mqtt"})

_CHOICES: tuple[tuple[str, str], ...] = (
    (
        "The data is NOT in a broker yet — start from the devices "
        "(survey the network, then read PLCs and instruments directly)",
        "iaiops onboard status --track devices",
    ),
    (
        "The data ALREADY flows through an MQTT/UNS broker — start from the "
        "broker (no scan: a scan never identifies MQTT)",
        "iaiops onboard status --track uns",
    ),
)

#: A mixed site is not asked what KIND of site it is — config.yaml already says it
#: is both. It is asked which half to look at first, and both halves are real.
_MIXED_CHOICES: tuple[tuple[str, str], ...] = (
    (
        "Look at the device endpoints — the journey that reads PLCs and instruments directly",
        "iaiops onboard status --track devices",
    ),
    (
        "Look at the broker endpoints — the journey that subscribes to the UNS",
        "iaiops onboard status --track uns",
    ),
)

_START_WHY = (
    "The two journeys have different first steps. Reading devices starts with a "
    "survey; a site whose data is already in a broker starts by connecting to it, "
    "and a scan would never find that broker as MQTT."
)


class _View:
    """A config narrowed to one journey's endpoints.

    Every step reads ``config.targets`` and the facts gathered from it. On a site
    with both kinds of endpoint, grading the UNS journey on the device endpoints'
    tags — or the reverse — would report one journey's progress as the other's.
    ``gather_facts`` reads attributes with defaults, so this stand-in is enough to
    recompute them for exactly one journey.
    """

    def __init__(self, config: Any, targets: tuple[Any, ...]) -> None:
        self.targets = targets
        self.historian = getattr(config, "historian", None)
        self.retention_raw_days = getattr(config, "retention_raw_days", None)


def _split(config: Any) -> tuple[tuple[Any, ...], tuple[Any, ...]]:
    targets = tuple(getattr(config, "targets", ()) or ()) if config is not None else ()
    brokers = tuple(t for t in targets if str(getattr(t, "protocol", "")) in _BROKER_PROTOCOLS)
    devices = tuple(t for t in targets if str(getattr(t, "protocol", "")) not in _BROKER_PROTOCOLS)
    return brokers, devices


def validate_track(requested: Any) -> str:
    """The normalised track name, or ValueError naming the three that exist."""
    wanted = str(requested or _TRACK_AUTO).strip().lower()
    if wanted not in (_TRACK_AUTO, TRACK_DEVICES, TRACK_UNS):
        raise ValueError(
            f"Unknown track {requested!r}. Use 'auto' (derive it from config.yaml), "
            f"'{TRACK_DEVICES}' (read the devices directly) or '{TRACK_UNS}' (the "
            "data already flows through an MQTT/UNS broker)."
        )
    return wanted


def resolve_track(config: Any, requested: str = _TRACK_AUTO) -> tuple[str, str]:
    """Which journey this site is on, and what that was derived from."""
    wanted = validate_track(requested)
    brokers, devices = _split(config)
    if wanted != _TRACK_AUTO:
        # Not "--track": the same words reach an MCP caller, whose parameter is `track`.
        return wanted, f"chosen explicitly (track: {wanted})"
    if brokers and not devices:
        return (
            TRACK_UNS,
            f"config.yaml has {len(brokers)} broker endpoint(s) and no device endpoint",
        )
    if devices and not brokers:
        return (
            TRACK_DEVICES,
            f"config.yaml has {len(devices)} device endpoint(s) and no broker endpoint",
        )
    if brokers and devices:
        return (
            TRACK_MIXED,
            f"config.yaml has {len(devices)} device endpoint(s) and {len(brokers)} "
            "broker endpoint(s)",
        )
    return TRACK_UNDECIDED, "nothing is configured yet"


def _start_path(track: str, basis: str, config_error: str, scans: int) -> OnboardPath:
    """The one step a site gets when the files cannot say which journey it is on."""
    if config_error:
        # A broken file is not an empty one — and choosing a journey over a file
        # that will not load would be choosing blind.
        step = Step(
            key="start",
            label="Fix config.yaml",
            detail=(
                f"config.yaml did not parse ({config_error}) — which journey this site "
                "is on cannot be read out of a file that will not load. Fix it first."
            ),
            state=STATE_NEXT,
            why=_START_WHY,
        )
        return OnboardPath(
            steps=(step,), track=TRACK_UNDECIDED, track_detail="config.yaml did not load"
        )
    if track == TRACK_MIXED:
        detail = (
            f"{basis}. Those are two journeys with different first steps, and the tool "
            "will not pick one for you. Each half has its own path; look at both."
        )
    else:
        detail = (
            "Nothing is configured, and whether this site's data already flows through "
            "a broker is not something config.yaml or the store can tell."
            + (
                f" {scans} scan(s) are stored, which usually means the devices journey "
                "— but a UNS site can scan too, so it is not assumed."
                if scans
                else ""
            )
            + " Pick the one that describes the site."
        )
    step = Step(
        key="start",
        label="Pick the journey",
        detail=detail,
        state=STATE_NEXT,
        why=_START_WHY,
        choices=_MIXED_CHOICES if track == TRACK_MIXED else _CHOICES,
    )
    return OnboardPath(steps=(step,), track=track, track_detail=basis)


def _resolve_cursor(raw: list[tuple[str, str, str, tuple[str, str, str]]]) -> list[Step]:
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
        # Every step keeps its command, including the ones still waiting: showing
        # one at a time is a rendering decision (D17), and a blanked command is
        # one no test can check.
        steps.append(
            Step(key=key, label=label, detail=detail, state=resolved, command=command, why=why)
        )
    return steps


def _devices_raw(
    view: Any, facts: dict[str, Any], scans: int, store_error: str, others: int
) -> list:
    return [
        (
            "survey",
            "Find what is on the network",
            "You cannot configure what you have not found, and a plant network is "
            "never what the drawing says.",
            _survey_step(scans, store_error),
        ),
        (
            "endpoints",
            "Turn what was found into endpoints",
            "The scan already established how to reach each device. Typing it back "
            "in by hand is where forty devices become four.",
            _endpoint_step(facts, scans, others),
        ),
        (
            "points",
            "Get each endpoint's point list",
            "Which points exist is a question the device can answer — for the "
            "protocols where a point list is a thing at all.",
            _points_step(view, facts),
        ),
        *_shared_tail(view, facts),
    ]


def _uns_raw(
    view: Any, facts: dict[str, Any], brokers: tuple[Any, ...], audits: dict, now: datetime
) -> list:
    return [
        (
            "connect",
            "Connect to the broker",
            "The data is already published; iaiops subscribes. A scan is not needed "
            "and would never identify the broker as MQTT.",
            _connect_step(brokers),
        ),
        (
            "namespace",
            "Audit the namespace",
            "Publish-once/subscribe-many also means wrong-once/wrong-everywhere. "
            "Whether the topic tree is governed decides whether this site is B1 "
            "(clean) or B2 (governance is the work).",
            _namespace_step(brokers, audits, now),
        ),
        (
            "points",
            "Choose the points to monitor",
            "The broker can list what it carries; which of it matters is the site's call.",
            _uns_points_step(brokers),
        ),
        *_shared_tail(view, facts),
    ]


def _shared_tail(view: Any, facts: dict[str, Any]) -> list:
    return [
        (
            "meaning",
            "Say what the points MEAN",
            "The one step nothing can do for you. Which tag counts production is "
            "process knowledge, and a wrong guess yields a plausible OEE — worse "
            "than an error.",
            _meaning_step(view, facts),
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


def _journey_coverage(db_path: Any, names: list[str]) -> dict[str, Any]:
    """Sample coverage for THIS journey's endpoints only.

    The whole-store figure counted a device endpoint's samples as progress on the
    UNS journey: a devices-only site forced onto ``--track uns`` was shown "collect:
    done, 5000 samples" with no broker ever collected. The samples table carries
    the endpoint, so only this journey's endpoints are counted. Static queries per
    endpoint rather than a built ``IN (...)`` clause.
    """
    from iaiops.core.sink.sqlite_local import local_db_path

    empty: dict[str, Any] = {"exists": False, "samples": 0, "tags": 0, "span_days": 0.0}
    if not names:
        return empty
    path = Path(db_path).expanduser() if db_path else local_db_path()
    try:
        if not path.exists():
            return empty
        conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    except (OSError, sqlite3.Error) as exc:
        return {**empty, "error": f"{type(exc).__name__}: {exc}"}
    total, tags, span = 0, set(), 0.0
    try:
        for name in names:
            (count,) = conn.execute(
                "SELECT COUNT(*) FROM samples WHERE endpoint = ?", (name,)
            ).fetchone()
            total += int(count or 0)
            tags.update(
                row[0]
                for row in conn.execute(
                    "SELECT DISTINCT tag FROM samples WHERE endpoint = ?", (name,)
                )
            )
            best = conn.execute(
                "SELECT julianday(MAX(ts)) - julianday(MIN(ts)) AS s FROM samples "
                "WHERE endpoint = ? GROUP BY tag ORDER BY s DESC LIMIT 1",
                (name,),
            ).fetchone()
            if best and best[0] is not None:
                span = max(span, float(best[0]))
    except sqlite3.DatabaseError as exc:
        # A file with no samples table has never been written to; anything else is
        # a store we could not read, which is not the same as an empty one.
        if "no such table" in str(exc):
            return {**empty, "exists": True}
        return {**empty, "error": f"{type(exc).__name__}: {exc}"}
    finally:
        conn.close()
    return {"exists": True, "samples": total, "tags": len(tags), "span_days": round(span, 2)}


def assess_path(
    config: Any = None,
    db_path: Any = None,
    track: str = _TRACK_AUTO,
    audit_dir: Any = None,
) -> OnboardPath:
    """Report the site's journey, its position on it, and the single next move."""
    from iaiops.core.readiness.assess import gather_facts
    from iaiops.core.sink.uns_audit_store import load_uns_audit

    whole = gather_facts(config, db_path)
    if config is None:
        try:
            from iaiops.core.runtime.config import load_config

            config = load_config()
        except Exception:  # noqa: BLE001 — an unconfigured site is the state to report
            config = None

    config_error = str(whole.get("config_error") or "")
    scans, store_error = _scan_count(db_path)
    chosen, basis = resolve_track(config, track)
    if chosen in (TRACK_UNDECIDED, TRACK_MIXED):
        return _start_path(chosen, basis, config_error, scans)

    brokers, devices = _split(config)
    view = _View(config, brokers if chosen == TRACK_UNS else devices)
    facts = gather_facts(view, db_path)
    facts["config_error"] = config_error
    facts["store"] = _journey_coverage(db_path, [_name(t) for t in view.targets])
    now = datetime.now(UTC)

    notes: list[str] = []
    if chosen == TRACK_UNS:
        audits = {_name(t): load_uns_audit(_name(t), base_dir=audit_dir, now=now) for t in brokers}
        raw = _uns_raw(view, facts, brokers, audits, now)
        sub, sub_text, messy_target = _uns_subtrack(brokers, audits, now)
        detail = f"{basis} — {sub_text}"
        if sub == "B2" and messy_target is not None:
            notes.append(_governance_note(messy_target))
        if devices:
            notes.append(
                f"This site also has {len(devices)} device endpoint(s). They are not on "
                "this journey — see them with `iaiops onboard status --track devices`."
            )
    else:
        raw = _devices_raw(view, facts, scans, store_error, len(brokers))
        detail = basis
        if brokers:
            notes.append(
                f"This site has {len(brokers)} broker endpoint(s). They are not on this "
                "journey, and a scan never identifies MQTT — see them with "
                "`iaiops onboard status --track uns`."
            )
    if config_error:
        notes.append(
            f"config.yaml did not load ({config_error}) — every step below that reads it "
            "is reporting on an empty config, not on your site."
        )
    if facts.get("role_conflict"):
        notes.append(f"role conflict in config.yaml: {facts['role_conflict']}")
    return OnboardPath(
        steps=tuple(_resolve_cursor(raw)),
        notes=tuple(notes),
        track=chosen,
        track_detail=detail,
    )


__all__ = ["assess_path", "resolve_track", "validate_track"]
