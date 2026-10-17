"""What a device DECLARES about itself through OPC UA companion specifications.

D16 forbids inferring a tag's role from its NAME: a ``GoodPartsCounter`` that
counts something else is ordinary, and a wrong production counter yields a
plausible OEE, which is worse than an error. A companion specification is a
different kind of evidence. When a server instantiates
``MachineryItemState_StateMachineType`` from ``http://opcfoundation.org/UA/Machinery/``,
the device itself is stating, in a published standard, which node carries its
state and what each number means. That is the device's declaration, not
our guess.

It is still only a SUGGESTION. A vendor can instantiate a type and wire it to
the wrong variable; a sub-state machine can hold a stale value while its parent
is stopped. So a match here pre-fills read-only columns in the ``tags export``
sheet with its evidence, a person confirms it by setting ``role``, and nothing
in this module ever writes a role (HLD D16 — confirmation stays human).

**Matched by type definition, never by browse name alone.** ISA-TR88 PackTags
names (``Status.StateCurrent``, ``Admin.ProdProcessedCount``) are common on PLCs
that expose PackTags without the OPC UA companion types. A node merely CALLED
``StateCurrent`` is a name, and inferring from names is exactly what D16 forbids.
Note also that ``StateCurrent`` is a PackTags name: OPC 30050 does not define it
— it models the state as ``BaseStateMachine/MachineState/ExecuteState``, a
FiniteStateMachine whose ``CurrentState`` carries the state.

**Only the language-independent value is suggested.** ``CurrentState`` is
LocalizedText (Annex B of OPC 30050 recommends localised names), so a German
server may say ``Ausführen`` where an English one says ``Execute``. The optional
``CurrentState/Number`` property (UInt32, OPC 10000-16 §4.4.3) is the same on
every server; when a server does not expose it, the type is reported as
recognised and no role is suggested.

Sources (checked 2026-10-17 on reference.opcfoundation.org):

* OPC 30050 PackML v1.01 — namespace ``http://opcfoundation.org/UA/PackML/`` (A.1);
  PackMLBaseObjectType components Admin / Status / BaseStateMachine (§6.3.2);
  PackMLAdminObjectType ProdProcessedCount / ProdDefectiveCount /
  ProdConsumedCount ``PackMLCountDataType[]``, StopReason ``PackMLAlarmDataType``
  (§6.3.4); PackMLMachineStateMachineType Running = 18 (§6.3.7);
  PackMLExecuteStateMachineType Execute = 6, Idle = 4, Held = 11 … (§6.3.8).
  PackML is RECOGNISED but not suggested — see :data:`SUBSTATE_TYPES`.
* OPC 40001-1 Machinery v1.04 — namespace ``http://opcfoundation.org/UA/Machinery/``
  (§20.1); MachineryItemState_StateMachineType NotAvailable 0, OutOfService 1,
  NotExecuting 2, Executing 3 (§12.2, Table 31).
* OPC 10000-16 §4.4.3 StateVariableType — Id mandatory; Name, Number (UInt32),
  EffectiveDisplayName optional.

[PURE] No I/O. The address-space walk that feeds this lives in
``iaiops.connectors.opcua.companion``.
"""

from __future__ import annotations

from dataclasses import dataclass

PACKML_NS = "http://opcfoundation.org/UA/PackML/"
MACHINERY_NS = "http://opcfoundation.org/UA/Machinery/"

#: Child path, under a matched state-machine object, of the value we suggest.
STATE_NUMBER_PATH = ("CurrentState", "Number")

#: Recorded in every suggestion so a reader can tell when the mapping was checked.
VERIFIED_ON = "2026-10-17"


@dataclass(frozen=True)
class StateRule:
    """A state-machine type whose ``CurrentState/Number`` declares a run state."""

    spec_id: str
    spec: str
    namespace_uri: str
    type_name: str
    running_when: tuple[int, ...]
    source: str
    caveats: tuple[str, ...]


@dataclass(frozen=True)
class RecognisedChild:
    """A child a spec type declares that has NO role in iaiops's vocabulary.

    Reported so the person sees the device declared it and why nothing was
    suggested — silence would read as "the device declares nothing".
    """

    spec_id: str
    spec: str
    namespace_uri: str
    parent_type: str
    child: str
    why_no_role: str


STATE_RULES: tuple[StateRule, ...] = (
    StateRule(
        spec_id="machinery",
        spec="OPC 40001-1 Machinery v1.04",
        namespace_uri=MACHINERY_NS,
        type_name="MachineryItemState_StateMachineType",
        running_when=(3,),
        source="§12.2 Table 31 MachineryItemState_StateMachineType: Executing = 3",
        caveats=(
            "Executing means the machine is performing its intended function; the "
            "spec says nothing about whether that output is good product.",
        ),
    ),
)

#: State machines that are recognised but deliberately NOT suggested as a run
#: state, with the reason. PackML is here, not in STATE_RULES, because of what a
#: review of the first version found: Execute (6) lives in ExecuteState, a SUB-state
#: machine that is only active while MachineState is Running (18, §6.3.7). Outside
#: Running a server either keeps the last sub-state (a stopped line reads 6 —
#: counted as production) or answers with a Bad status (Bad_StateNotActive), which
#: the collector records as a failed read — every stopped minute becomes a blind
#: window, and availability over KNOWN time then reads near 100%. Both errors
#: flatter the number. One tag cannot express "MachineState = Running AND
#: ExecuteState = Execute", and MachineState alone (Running = 18) also covers Idle,
#: Held and Suspended. So nothing is suggested until the collector can say
#: "inactive sub-state = not running" — refused rather than pretended.
SUBSTATE_TYPES: dict[tuple[str, str], str] = {
    (PACKML_NS, "PackMLExecuteStateMachineType"): (
        "PackML ExecuteState (OPC 30050 §6.3.8, Execute = 6) is a sub-state machine, "
        "active only while MachineState is Running (18, §6.3.7). Stopped, a server may "
        "keep a stale 6 (stopped time counted as producing) or return Bad_StateNotActive "
        "(stopped time becomes blind, availability over known time reads near 100%). "
        "No single tag says 'Running AND Execute', and MachineState Running also covers "
        "Idle / Held / Suspended — so no run_state is suggested. Declare it by hand after "
        "watching both values through a stop."
    ),
    (PACKML_NS, "PackMLMachineStateMachineType"): (
        "PackML MachineState (OPC 30050 §6.3.7): Running = 18 also covers Idle, Held and "
        "Suspended, so it is not a producing state. No role suggested."
    ),
}

RECOGNISED_WITHOUT_ROLE: tuple[RecognisedChild, ...] = (
    *(
        RecognisedChild(
            spec_id="packml",
            spec="OPC 30050 PackML v1.01",
            namespace_uri=PACKML_NS,
            parent_type="PackMLAdminObjectType",
            child=name,
            why_no_role=(
                f"{name} is PackMLCountDataType[] (§6.3.4) — one count structure per "
                "product/material id. A tag here holds ONE number, so picking an "
                "element would be a guess; no "
                f"{'reject_count' if name == 'ProdDefectiveCount' else 'count'} role "
                "is suggested. Configure the element's Count as its own tag if the "
                "server exposes it."
            ),
        )
        for name in ("ProdProcessedCount", "ProdDefectiveCount", "ProdConsumedCount")
    ),
    RecognisedChild(
        spec_id="packml",
        spec="OPC 30050 PackML v1.01",
        namespace_uri=PACKML_NS,
        parent_type="PackMLAdminObjectType",
        child="StopReason",
        why_no_role=(
            "StopReason is PackMLAlarmDataType (§6.3.4). iaiops has no stop-reason "
            "role: why a line stopped is recorded by a person (`iaiops case "
            "confirm`), not read off a signal."
        ),
    ),
)

#: Mode machines: recognised, deliberately not a run state.
MODE_TYPES: dict[tuple[str, str], str] = {
    (MACHINERY_NS, "MachineryOperationModeStateMachineType"): (
        "Operation MODE (None / Maintenance / Setup / Processing), OPC 40001-1 §13. "
        "Processing mode is not the same as executing — a machine can be in "
        "Processing and stopped. No role suggested."
    ),
}


def state_rule(namespace_uri: str, type_name: str) -> StateRule | None:
    """The rule for one (namespace, type) pair, or None."""
    for rule in STATE_RULES:
        if rule.namespace_uri == namespace_uri and rule.type_name == type_name:
            return rule
    return None


def recognised_children(namespace_uri: str, type_name: str) -> tuple[RecognisedChild, ...]:
    """Children of this type that are declared but carry no iaiops role."""
    return tuple(
        c
        for c in RECOGNISED_WITHOUT_ROLE
        if c.namespace_uri == namespace_uri and c.parent_type == type_name
    )


def suggestion(
    rule: StateRule,
    *,
    node_id: str,
    browse_path: str,
    instance_type: str,
    current_value: object = None,
) -> dict:
    """The suggestion record for one matched node — evidence first, role second."""
    via = (
        f"{instance_type} (a subtype of {rule.type_name})"
        if instance_type and instance_type != rule.type_name
        else rule.type_name
    )
    return {
        "node_id": node_id,
        "browse_path": browse_path,
        "spec_id": rule.spec_id,
        "spec": rule.spec,
        "namespace_uri": rule.namespace_uri,
        "type": rule.type_name,
        "instance_type": instance_type or rule.type_name,
        "role": "run_state",
        "running_when": list(rule.running_when),
        "basis": "type_definition",
        "why": (
            f"The device instantiates {via} from {rule.namespace_uri}; its "
            f"CurrentState/Number is the state number defined in {rule.source}."
        ),
        "caveats": list(rule.caveats),
        "current_value": current_value,
        "verified_on": VERIFIED_ON,
    }


def one_line(text: object) -> str:
    """Every run of whitespace — newline and CR included — folded to one space.

    Evidence carries device-supplied browse names and ends up in a YAML comment
    in the config patch. ``sanitize`` keeps ``\\n``/``\\r``, and a newline ends a
    YAML comment: a browse name could then write a ``role:`` nobody chose.
    """
    return " ".join(str(text or "").split())


def evidence_line(hint: dict) -> str:
    """One line for the sheet's read-only ``suggestion_evidence`` column."""
    caveat = " ".join(str(c) for c in hint.get("caveats", ()) if "待核实" in str(c))
    text = (
        f"{hint.get('spec', '')}: {hint.get('instance_type', '')} at "
        f"{hint.get('browse_path', '')} ({hint.get('node_id', '')}) — "
        f"{hint.get('why', '')}"
    )
    return one_line(f"{text} {caveat}")


__all__ = [
    "MACHINERY_NS",
    "MODE_TYPES",
    "PACKML_NS",
    "RECOGNISED_WITHOUT_ROLE",
    "STATE_NUMBER_PATH",
    "STATE_RULES",
    "SUBSTATE_TYPES",
    "RecognisedChild",
    "StateRule",
    "evidence_line",
    "one_line",
    "recognised_children",
    "state_rule",
    "suggestion",
]
