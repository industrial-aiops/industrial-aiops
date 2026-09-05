"""Turn a stored scan into a ``config.yaml`` draft — of connection facts only.

The gap this closes: a site scans 40 devices, and then types all 40 back in by
hand, because nothing carried the scan's answer forward. Everything needed was
already on disk.

**What is drafted and what is not.** A scan establishes how to *reach* a device.
It establishes nothing about what the device's data *means*. So this module
emits endpoints and an explicitly empty ``tags:`` list, and the point list is
confirmed by a person afterwards (``iaiops tags export`` → fill → ``tags
apply``). No amount of chaining changes that boundary; it is D16, and a guessed
production counter yields a plausible OEE, which is worse than an error.

**Only confirmed protocols become endpoints.** ``port_only`` means something is
listening on 502. It does not mean the thing is a Modbus device, and a config
that says it is would be believed. Those hosts are reported as skipped, with the
reason, so nothing quietly disappears.

**Every drafted field names its evidence.** :class:`~iaiops.core.onboard.model.DraftField`
refuses to hold a value without one. Fields the scan could not establish are
still rendered — commented, with what they are waiting for — because omitting
them lets a protocol default apply in silence, and a Modbus gateway read at unit
1 answers happily while showing you the wrong machine.

Contacts nothing. Writes nothing. ``config.yaml`` stays the one source of truth,
edited by a person, exactly as ``iaiops tags apply`` leaves it.
"""

from __future__ import annotations

import re
from typing import Any

from iaiops.core.onboard.model import Draft, DraftEndpoint, DraftField, SkippedHost

#: Scan protocol name → the ``protocol:`` value ``config.yaml`` uses. Protocols
#: a scan can identify but this product has no connector for are absent, and
#: their hosts are skipped with that reason rather than silently dropped.
_CONFIG_PROTOCOL: dict[str, str] = {
    "modbus": "modbus",
    "opcua": "opcua",
    "s7": "s7",
    "ethernetip": "ethernetip",
    "mc": "mc",
    "mtconnect": "mtconnect",
    "iolink": "iolink",
}

_SAFE_NAME = re.compile(r"[^a-z0-9]+")


def _endpoint_name(protocol: str, ip: str, port: int = 0, *, qualify: bool = False) -> str:
    """A stable, YAML-safe name — and deliberately not a friendly one.

    Naming an endpoint ``filler-line-3`` from a scan would be inventing a fact
    about the plant. The address is what was observed; a person renames it when
    they know what the box actually does.

    ``qualify`` appends the port, and it is not cosmetic. One host can confirm
    the same protocol on two ports — OPC-UA is allowlisted on 4840 and 4843 and
    MTConnect on 80, 5000 and 8080 — and protocol+ip alone then minted the same
    name twice. ``AppConfig.get_target`` returns the first match, so the second
    endpoint would be unreachable by name for as long as the config lived, while
    both were still collected under one name.
    """
    base = f"{protocol}-{_SAFE_NAME.sub('-', ip.lower()).strip('-')}"
    return f"{base}-{port}" if qualify and port else base


def _int(value: Any) -> int:
    """A port from the store, or 0. Never a raise, never a rounded float.

    The record reaches us through a bare ``json.loads`` of a sqlite column, so
    its shape is whatever was written — a string port, a float, None. Every one
    of those used to escape as a raw traceback (``ValueError``/``TypeError`` are
    not in the CLI's handled set), and ``1.5`` silently became port 1.
    """
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else 0


def _extra(host: dict[str, Any], protocol: str) -> dict[str, Any]:
    """The per-protocol identity extras, guarding EVERY level.

    ``identity`` was guarded one level in and not at the outer level, which is an
    inconsistency rather than a contract: a column holding a list or a string
    raised ``AttributeError`` out of the command.
    """
    identity = host.get("identity")
    if not isinstance(identity, dict):
        return {}
    per_protocol = identity.get(protocol)
    if not isinstance(per_protocol, dict):
        return {}
    extra = per_protocol.get("extra")
    return extra if isinstance(extra, dict) else {}


def _names(extra: dict[str, Any], key: str) -> list[str]:
    """A list of names from ``extra``, or none. A string is not a list of names.

    ``devices: "abc"`` iterated into three devices ``a``, ``b``, ``c``.
    """
    value = extra.get(key)
    if not isinstance(value, list | tuple):
        return []
    return [str(v) for v in value if str(v).strip()]


def _confirmed_port(host: dict[str, Any], candidate: dict[str, Any]) -> tuple[int, str]:
    """The port this protocol was confirmed on, and the caveat on knowing it.

    The second element is empty when the scan recorded the port itself, and
    carries the caveat when it did not. Scans stored before the candidate
    carried its own port read back as 0; for those, the port is recoverable when
    exactly ONE of the host's open ports can serve this protocol at all — which
    is deduction, not a guess, and is labelled as deduction. With two candidate
    ports it is neither, and the field goes out unestablished rather than
    picking the lower number.
    """
    recorded = _int(candidate.get("port"))
    if recorded:
        return recorded, ""

    from iaiops.core.discovery.ports import describe_port

    protocol = str(candidate.get("protocol") or "")
    open_ports = [n for n in (_int(p) for p in host.get("open_ports") or ()) if n]
    serving = [
        p
        for p in open_ports
        if (entry := describe_port(p)) is not None and protocol in entry.protocols
    ]
    if len(serving) == 1:
        return serving[0], (
            "the scan did not record which port this protocol answered on — it "
            "predates that — so this is the only open port on the host that can "
            "serve this protocol, deduced rather than observed."
        )
    return 0, ""


def _bool(extra: dict[str, Any], key: str) -> bool | None:
    value = extra.get(key)
    return value if isinstance(value, bool) else None


def _fields_modbus(ip: str, port: int, port_why: str, extra: dict[str, Any]) -> list[DraftField]:
    """Note what is NOT here: ``unit_id``.

    It used to be drafted as ``1`` with the evidence "unit 1 answered the FC43
    identity request" — a sentence built out of the default, which is precisely
    what :class:`DraftField` refuses and was here smuggled past by manufacturing
    the string. Two things are wrong with it. On a host confirmed by REJECTION
    the block said the device *declined* the request and *answered* it four lines
    apart. And even on success nothing observed a unit: the probe hardcodes
    ``unit_id=1`` and the connector echoes that same 1 back into the identity, so
    no reading of any device can justify the claim.

    That leaves the field unestablished — which is right. It is the one field
    this module's own docstring names as the killer: a gateway read at unit 1
    answers happily and shows you the wrong machine.
    """
    return [
        DraftField("host", ip, "the address that answered"),
        *_port_field(port, port_why, 502),
        DraftField(
            "unit_id",
            None,
            caution=(
                "the scan asks unit 1 and ONLY unit 1 — deliberately, because "
                "walking unit ids is a request storm — and the reply echoes back "
                "the id we asked for, so nothing here establishes which slave "
                "this is. The default if you leave this out is 1, which is right "
                "for a directly-addressed device. A serial gateway fronts several "
                "slaves behind one IP: one endpoint per unit you actually read."
            ),
        ),
    ]


def _fields_opcua(ip: str, port: int, port_why: str, extra: dict[str, Any]) -> list[DraftField]:
    fields: list[DraftField] = []
    if port:
        url = f"opc.tcp://{ip}:{port}/"
        count = extra.get("endpoint_count")
        caution = ""
        if isinstance(count, int) and count > 1:
            caution = (
                f"the server advertised {count} endpoints. This is the discovery "
                "URL that answered GetEndpoints; a session may require one of the "
                "advertised URLs, which can carry a path."
            )
        fields.append(
            DraftField(
                "endpoint_url",
                url,
                "GetEndpoints answered at this URL",
                caution="; ".join(c for c in (port_why, caution) if c),
            )
        )
    else:
        fields.append(
            DraftField(
                "endpoint_url",
                None,
                caution=(
                    "OPC-UA was confirmed on this host but the port it answered on "
                    "was not recorded and more than one open port could serve it. "
                    "Re-scan, or read the port off the server."
                ),
            )
        )

    none_security = _bool(extra, "allows_none_security")
    if none_security is True:
        fields.append(
            DraftField(
                "security_mode",
                "None",
                "the server advertises an endpoint with no message security",
                caution=(
                    "advertised is not recommended. An unencrypted OPC-UA session "
                    "is a 62443 finding in its own right; use it to get a first "
                    "read, not as the end state."
                ),
            )
        )
        fields.append(DraftField("security_policy", "None", "same endpoint as security_mode above"))
    elif none_security is False:
        fields.append(
            DraftField(
                "security_mode",
                None,
                caution=(
                    "this server advertises NO unsecured endpoint, so an anonymous "
                    "unencrypted read will not connect. Set security_mode / "
                    "security_policy and the certificate paths."
                ),
            )
        )

    if _bool(extra, "allows_anonymous") is False:
        fields.append(
            DraftField(
                "username",
                None,
                caution=(
                    "the server does not accept anonymous sessions. Set a username "
                    "here and store its password with `iaiops secret set` — never "
                    "in config.yaml."
                ),
            )
        )
    return fields


def _fields_s7(ip: str, port: int, port_why: str, extra: dict[str, Any]) -> list[DraftField]:
    slot = extra.get("slot")
    fields = [
        DraftField("host", ip, "the address that answered"),
        *_port_field(port, port_why, 102),
        DraftField("rack", 0, "the probe connected at rack 0, which is where the CPU answered"),
    ]
    if isinstance(slot, int):
        fields.append(
            DraftField("slot", slot, f"the CPU returned its identity at rack 0 / slot {slot}")
        )
    else:
        fields.append(
            DraftField(
                "slot",
                None,
                caution=(
                    "the CPU answered in-protocol but declined the identity read, "
                    "so no slot was established. S7-1200/1500 usually answer at "
                    "slot 1 and S7-300/400 at slot 2."
                ),
            )
        )
    return fields


def _fields_ethernetip(
    ip: str, port: int, port_why: str, extra: dict[str, Any]
) -> list[DraftField]:
    return [
        DraftField("host", ip, "the address that answered ListIdentity"),
        # Emitted rather than omitted, per this module's own rule: an absent
        # field takes the protocol default in silence.
        *_port_field(port, port_why, 44818),
        DraftField(
            "slot",
            None,
            caution=(
                "ListIdentity is answered by the network adapter and says nothing "
                "about which backplane slot holds the CPU. Leaving this line out "
                "does NOT mean 0 — the default is 1. Set it explicitly: 0 for a "
                "CompactLogix and for a ControlLogix whose controller sits in slot "
                "0, otherwise the slot the rack actually uses."
            ),
        ),
    ]


def _fields_mc(ip: str, port: int, port_why: str, extra: dict[str, Any]) -> list[DraftField]:
    plctype = str(extra.get("plctype") or "")
    fields = [
        DraftField("host", ip, "the address that answered"),
        *_port_field(port, port_why, 5007),
    ]
    if plctype:
        fields.append(DraftField("plctype", plctype, "the CPU reported this type"))
    else:
        fields.append(
            DraftField(
                "plctype",
                None,
                caution=(
                    "the CPU answered but reported no type. Q / L / QnA / iQ-R "
                    "differ in frame limits, so the wrong one reads short."
                ),
            )
        )
    return fields


def _fields_mtconnect(ip: str, port: int, port_why: str, extra: dict[str, Any]) -> list[DraftField]:
    if not port:
        return [
            DraftField(
                "agent_url",
                None,
                caution=(
                    "MTConnect was confirmed but the port was not recorded and more "
                    "than one open port could serve it. Re-scan."
                ),
            )
        ]
    fields = [
        DraftField("agent_url", f"http://{ip}:{port}", "/probe answered at this URL", port_why)
    ]
    devices = _names(extra, "devices")
    count = extra.get("device_count")
    if not isinstance(count, int) or isinstance(count, bool):
        count = None
    if len(devices) == 1 and count in (1, None):
        fields.append(
            DraftField(
                "device",
                devices[0],
                "the agent's probe response listed exactly this one device",
            )
        )
    else:
        listed = ", ".join(devices[:8]) or "(names not recorded)"
        fields.append(
            DraftField(
                "device",
                None,
                caution=(
                    f"this agent serves {count if isinstance(count, int) else 'several'} "
                    f"devices — {listed}. It also streams its own `Agent` device, whose "
                    "Availability is AVAILABLE whenever the agent is answering, so "
                    "picking wrong yields a machine that is never down. Name the machine."
                ),
            )
        )
    return fields


def _fields_iolink(ip: str, port: int, port_why: str, extra: dict[str, Any]) -> list[DraftField]:
    if not port:
        return [
            DraftField(
                "agent_url",
                None,
                caution="the port this master answered on was not recorded. Re-scan.",
            )
        ]
    fields = [
        DraftField("agent_url", f"http://{ip}:{port}", "the master answered at this URL", port_why)
    ]
    flavor = str(extra.get("flavor") or "")
    if flavor:
        fields.append(DraftField("flavor", flavor, "the master answered in this JSON dialect"))
    return fields


def _port_field(port: int, why: str, default: int) -> list[DraftField]:
    """``why`` non-empty means the port was DEDUCED, and the evidence must say so.

    It used to say "the port this device answered on" either way and put the
    deduction in the caution — but ``observed:`` is the line the rendered header
    tells the reader to trust, so the weaker claim has to live there.
    """
    if port and why:
        return [
            DraftField(
                "port",
                port,
                "deduced, not observed: the only open port on this host that can "
                "serve this protocol",
                caution=why,
            )
        ]
    if port:
        return [DraftField("port", port, "the port this device answered on")]
    return [
        DraftField(
            "port",
            None,
            caution=(
                f"the port was not recorded and more than one open port could serve "
                f"this protocol. The protocol default is {default}; confirm it, or "
                "re-scan with a current version."
            ),
        )
    ]


_FIELD_RULES = {
    "modbus": _fields_modbus,
    "opcua": _fields_opcua,
    "s7": _fields_s7,
    "ethernetip": _fields_ethernetip,
    "mc": _fields_mc,
    "mtconnect": _fields_mtconnect,
    "iolink": _fields_iolink,
}


def _address_of(protocol: str, ip: str, fields: list[DraftField]) -> str:
    """The same ``protocol|address`` key :func:`endpoint_address` builds, from a
    drafted endpoint rather than a configured one, so the two can be compared."""
    by_name = {f.name: f for f in fields}
    for field in ("endpoint_url", "agent_url", "host"):
        value = by_name.get(field)
        if value is not None and value.established:
            return f"{protocol}|{str(value.value).strip().lower()}"
    return f"{protocol}|{ip.strip().lower()}"


def _limits() -> tuple[str, ...]:
    """What this draft structurally cannot contain — stated, not left to be noticed.

    Read off the discovery tables rather than written down here, so a protocol
    that becomes identifiable stops being listed on its own.
    """
    from iaiops.core.discovery.identify import IDENTIFY_PLAN, NO_SAFE_IDENTIFY

    out = [
        "A protocol missing from this draft is NOT evidence that the site does not "
        "speak it. This lists what a scan established, and a scan is narrow on purpose.",
        "BACnet, FINS and HART are UDP. The sweep is TCP-only, so those devices never "
        "appear here at all — configure them by hand.",
    ]
    for protocol, reason in sorted(NO_SAFE_IDENTIFY.items()):
        out.append(f"{protocol}: seen as an open port only, never identified — {reason}")
    identifiable = ", ".join(sorted(IDENTIFY_PLAN))
    out.append(
        f"Only these are ever confirmed by a scan, and only these are drafted: {identifiable}."
    )
    return tuple(out)


def draft_from_scan(
    record: dict[str, Any],
    existing_names: tuple[str, ...] = (),
    existing_addresses: tuple[str, ...] = (),
) -> Draft:
    """Build the config draft a stored scan supports. Reads nothing else.

    ``existing_addresses`` are ``protocol|address`` keys, and they matter because
    the draft's own header tells the reader to rename what it emits. Matching
    only on the generated name meant the guard worked exactly once: rename
    ``opcua-10-0-0-9`` to ``filler-line-3`` and the next scan re-offered the same
    device as new.
    """
    taken = {str(n).strip().lower() for n in existing_names if str(n).strip()}
    taken_addresses = {str(a).strip().lower() for a in existing_addresses if str(a).strip()}
    endpoints: list[DraftEndpoint] = []
    skipped: list[SkippedHost] = []

    malformed = 0
    for host in record.get("hosts") or ():
        if not isinstance(host, dict):
            # The record comes back through a bare `json.loads` of a sqlite
            # column. A row that is not a mapping used to escape as a raw
            # AttributeError traceback out of the command.
            malformed += 1
            continue
        ip = str(host.get("ip") or "")
        if not ip:
            # `host: ""` used to be drafted with the evidence "the address that
            # answered". No address answered.
            malformed += 1
            continue
        candidates = [c for c in host.get("protocols") or () if isinstance(c, dict)]
        seen = tuple(str(c.get("protocol") or "") for c in candidates)
        confirmed = [c for c in candidates if c.get("confidence") == "confirmed"]
        if not confirmed:
            skipped.append(
                SkippedHost(
                    ip,
                    (
                        "no protocol was confirmed — an open port means something is "
                        "listening, not that it speaks this protocol"
                    )
                    if candidates
                    else "nothing on this host was identified",
                    seen,
                )
            )
            continue

        # How many endpoints this host will contribute per config protocol, so a
        # second one on another port can be told apart by name instead of
        # silently shadowing the first.
        per_protocol: dict[str, int] = {}
        for candidate in confirmed:
            mapped = _CONFIG_PROTOCOL.get(str(candidate.get("protocol") or ""))
            if mapped:
                per_protocol[mapped] = per_protocol.get(mapped, 0) + 1

        made = 0
        for candidate in confirmed:
            scan_protocol = str(candidate.get("protocol") or "")
            config_protocol = _CONFIG_PROTOCOL.get(scan_protocol)
            if config_protocol is None:
                skipped.append(
                    SkippedHost(
                        ip,
                        f"{scan_protocol} was confirmed, but iaiops has no connector for it",
                        seen,
                    )
                )
                continue
            port, port_why = _confirmed_port(host, candidate)
            fields = _FIELD_RULES[config_protocol](ip, port, port_why, _extra(host, scan_protocol))
            name = _endpoint_name(
                config_protocol, ip, port, qualify=per_protocol[config_protocol] > 1
            )
            endpoints.append(
                DraftEndpoint(
                    name=name,
                    protocol=config_protocol,
                    ip=ip,
                    fields=tuple(fields),
                    evidence=str(candidate.get("detail") or candidate.get("evidence") or ""),
                    already_configured=(
                        name.lower() in taken
                        or _address_of(config_protocol, ip, fields) in taken_addresses
                    ),
                )
            )
            made += 1
        if not made and not any(s.ip == ip for s in skipped):  # pragma: no cover - defensive
            skipped.append(SkippedHost(ip, "confirmed, but nothing could be drafted from it", seen))

    if malformed:
        skipped.append(
            SkippedHost(
                "",
                f"{malformed} stored host row(s) carried no usable address and were "
                "not drafted — the scan store holds whatever was written to it",
            )
        )
    return Draft(
        scan_id=str(record.get("scan_id") or ""),
        site=str(record.get("site") or ""),
        scanned_at=str(record.get("started_at") or record.get("finished_at") or ""),
        endpoints=tuple(endpoints),
        skipped=tuple(skipped),
        limits=_limits(),
    )


__all__ = ["draft_from_scan"]
