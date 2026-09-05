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


def _endpoint_name(protocol: str, ip: str) -> str:
    """A stable, unique, YAML-safe name — and deliberately not a friendly one.

    Naming an endpoint ``filler-line-3`` from a scan would be inventing a fact
    about the plant. The address is what was observed; a person renames it when
    they know what the box actually does.
    """
    return f"{protocol}-{_SAFE_NAME.sub('-', ip.lower()).strip('-')}"


def _extra(host: dict[str, Any], protocol: str) -> dict[str, Any]:
    identity = host.get("identity") or {}
    per_protocol = identity.get(protocol) or {}
    extra = per_protocol.get("extra") if isinstance(per_protocol, dict) else None
    return extra if isinstance(extra, dict) else {}


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
    recorded = int(candidate.get("port") or 0)
    if recorded:
        return recorded, ""

    from iaiops.core.discovery.ports import describe_port

    protocol = str(candidate.get("protocol") or "")
    open_ports = [int(p) for p in host.get("open_ports") or ()]
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
    unit = extra.get("unit_id")
    unit_id = int(unit) if isinstance(unit, int) else 1
    return [
        DraftField("host", ip, "the address that answered"),
        *_port_field(port, port_why, 502),
        DraftField(
            "unit_id",
            unit_id,
            f"unit {unit_id} answered the FC43 identity request",
            caution=(
                "one unit answering does not mean it is the machine you want. A "
                "serial gateway fronts several slaves behind one IP, and the "
                "scan asks unit 1 only — deliberately, because walking unit ids "
                "is a request storm. One endpoint per unit you actually read."
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
        DraftField(
            "slot",
            None,
            caution=(
                "ListIdentity is answered by the network adapter and says nothing "
                "about which backplane slot holds the CPU. 0 is right for a "
                "CompactLogix and for a ControlLogix whose controller sits in slot "
                "0; on any other rack layout it reads the wrong module."
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
    devices = [str(d) for d in (extra.get("devices") or []) if str(d).strip()]
    count = extra.get("device_count")
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
    if port:
        return [DraftField("port", port, "the port this device answered on", caution=why)]
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


def draft_from_scan(record: dict[str, Any], existing_names: tuple[str, ...] = ()) -> Draft:
    """Build the config draft a stored scan supports. Reads nothing else."""
    taken = {str(n).strip().lower() for n in existing_names if str(n).strip()}
    endpoints: list[DraftEndpoint] = []
    skipped: list[SkippedHost] = []

    for host in record.get("hosts") or ():
        ip = str(host.get("ip") or "")
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
            name = _endpoint_name(config_protocol, ip)
            endpoints.append(
                DraftEndpoint(
                    name=name,
                    protocol=config_protocol,
                    ip=ip,
                    fields=tuple(fields),
                    evidence=str(candidate.get("detail") or candidate.get("evidence") or ""),
                    already_configured=name.lower() in taken,
                )
            )
            made += 1
        if not made and not any(s.ip == ip for s in skipped):  # pragma: no cover - defensive
            skipped.append(SkippedHost(ip, "confirmed, but nothing could be drafted from it", seen))

    return Draft(
        scan_id=str(record.get("scan_id") or ""),
        site=str(record.get("site") or ""),
        scanned_at=str(record.get("started_at") or record.get("finished_at") or ""),
        endpoints=tuple(endpoints),
        skipped=tuple(skipped),
        limits=_limits(),
    )


__all__ = ["draft_from_scan"]
