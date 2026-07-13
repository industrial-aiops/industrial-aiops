"""Environment and connectivity diagnostics for iaiops.

A doctor must survive the thing it diagnoses being unhealthy: every connectivity
probe is reported as a status line, never raised as a traceback.
"""

from __future__ import annotations

from rich.console import Console

from iaiops.core.runtime.capabilities import (
    PROBE_INFORMATIONAL,
    PROBE_OPCUA,
    UNSUPPORTED,
    get_capabilities,
)
from iaiops.core.runtime.config import (
    CONFIG_FILE,
    ENV_FILE,
    load_config,
    password_env_var,
)
from iaiops.core.runtime.secretstore import SECRETS_FILE, check_permissions, has_store

_console = Console()


def run_doctor(skip_probe: bool = False) -> int:
    """Check config, the encrypted store, and endpoint reachability.

    Returns a process exit code: 0 healthy, 1 problems found.
    """
    problems = 0

    if CONFIG_FILE.exists():
        _console.print(f"[green]✓ Config file present: {CONFIG_FILE}[/]")
    else:
        _console.print(f"[yellow]! No config file ({CONFIG_FILE}); run 'iaiops init'.[/]")

    try:
        config = load_config()
    except Exception as exc:  # noqa: BLE001 — report, do not crash
        _console.print(f"[red]✗ Config load failed: {exc}[/]")
        return 1

    if has_store():
        _console.print(f"[green]✓ Encrypted secret store present: {SECRETS_FILE}[/]")
        perm_warning = check_permissions()
        if perm_warning:
            _console.print(f"[yellow]! {perm_warning}[/]")
    elif not ENV_FILE.exists():
        _console.print(
            "[yellow]! No encrypted secret store yet. Run 'iaiops init' to set "
            "up credentials (stored encrypted). Many OT endpoints are anonymous "
            "and need no password.[/]"
        )
    # A plaintext .env is loaded at import time whenever it exists — that is
    # secrets-on-disk in cleartext, an ERROR (not a warning), even if the
    # encrypted store also exists.
    if ENV_FILE.exists():
        _console.print(
            f"[red]✗ Plaintext .env in use ({ENV_FILE}) — secrets are stored "
            f"unencrypted on disk. Migrate with 'iaiops secret migrate'.[/]"
        )
        problems += 1

    if not config.targets:
        _console.print("[yellow]! No endpoints configured.[/]")
        problems += 1
    else:
        _console.print(f"[green]✓ {len(config.targets)} endpoint(s) configured[/]")
        for t in config.targets:
            var = password_env_var(t.name)
            present = "set" if t.password() else "none (anonymous or run init)"
            _console.print(
                f"  [dim]{t.name} ({t.protocol} @ {_where(t)}) — password: {present} ({var})[/]"
            )
            insecure = _opcua_insecure_auth_warning(t)
            if insecure:
                _console.print(f"[yellow]! {insecure}[/]")

    if skip_probe:
        _console.print("[dim]Skipping connectivity probe (--skip-probe).[/]")
        return 1 if problems else 0

    _console.print(
        "[dim]Tip: point an endpoint at a local simulator to validate safely — "
        "asyncua demo server (OPC-UA), a Modbus simulator, a pyS7/snap7 S7 sim, GX "
        "Simulator (MC), the MTConnect public demo agent, or a local mosquitto "
        "broker (MQTT).[/]"
    )

    for target in config.targets:
        problems += _report_target_probe(target)

    return 1 if problems else 0


def _report_target_probe(target) -> int:
    """Probe one endpoint, print its status, and return 1 iff it's a counted problem.

    The per-protocol reporting *style* (hard fail vs informational vs OPC-UA
    classify) comes from the capability registry — the same table every other
    dispatch site reads — so a new protocol can never silently mis-default.
    """
    cap = get_capabilities(target.protocol)
    style = cap.probe_style if cap else ""
    if style == PROBE_INFORMATIONAL:
        return _report_informational_probe(target)
    if style == PROBE_OPCUA:
        return _report_opcua_probe(target)
    return _report_hard_probe(target)


def _report_informational_probe(target) -> int:
    """EtherCAT/PROFINET/BACnet: an environmental miss is a yellow status, never counted.

    These need Linux/root/NIC/optional-lib/live-segment and have no software
    simulator, so a miss off the bus is informational — not a probe failure.
    """
    label, probe = _INFORMATIONAL_PROBES[target.protocol]
    ok, detail = probe(target)
    if ok:
        _console.print(f"[green]✓ Reachable '{target.name}' — {detail}[/]")
    else:
        _console.print(f"[yellow]! {label} '{target.name}' — {detail}[/]")
    return 0


def _report_opcua_probe(target) -> int:
    """OPC-UA: on failure, classify *why* and print the conclusion + fix, not a raw error."""
    ok, detail = _probe(target)
    if ok:
        _console.print(f"[green]✓ Reachable '{target.name}' — {detail}[/]")
        return 0
    v = _diagnose_opcua(target)
    if v["class"] == "ok":
        # probe failed but the diagnosis re-connect succeeded — a transient blip,
        # not a real fault; don't print a red ✗ ok.
        _console.print(
            f"[green]✓ Reachable '{target.name}' — recovered on retry ({v['diagnosis']})[/]"
        )
        return 0
    _console.print(f"[red]✗ OPC-UA '{target.name}' — {v['class']}: {v['diagnosis']}[/]")
    _console.print(f"  [yellow]→ {v['remediation']}[/]")
    return 1


def _report_hard_probe(target) -> int:
    """Every other protocol: a failed probe is a counted, red ✗ problem."""
    ok, detail = _probe(target)
    if ok:
        _console.print(f"[green]✓ Reachable '{target.name}' — {detail}[/]")
        return 0
    _console.print(f"[red]✗ Probe '{target.name}' failed: {detail}[/]")
    return 1


def _opcua_insecure_auth_warning(target) -> str | None:
    """Warn when OPC-UA username auth rides an unencrypted channel.

    ``security_mode: None`` means the session is neither signed nor encrypted, so
    a configured username's password crosses the wire in cleartext.
    """
    if getattr(target, "protocol", "") != "opcua":
        return None
    username = getattr(target, "username", "")
    security_mode = getattr(target, "security_mode", "None")
    if username and security_mode == "None":
        return (
            f"OPC-UA '{target.name}': username is set but security_mode is 'None' — "
            f"the password travels unencrypted. Set security_mode to 'Sign' or "
            f"'SignAndEncrypt' (with a security_policy, e.g. Basic256Sha256)."
        )
    return None


def _diagnose_opcua(target) -> dict:
    """Classify why an OPC-UA endpoint won't connect (never raises).

    Always returns a dict with ``class`` / ``diagnosis`` / ``remediation`` so the
    doctor can print a conclusion + fix rather than a raw error.
    """
    try:
        from iaiops.connectors.opcua.diagnostics import diagnose_connection

        return diagnose_connection(target)
    except Exception as exc:  # noqa: BLE001 — the doctor must never crash on a probe
        return {
            "class": "unknown",
            "diagnosis": f"Diagnosis itself failed: {str(exc)[:160]}",
            "remediation": "Re-run 'iaiops doctor'; point the endpoint at a local simulator.",
        }


def _probe_ethercat(target) -> tuple[bool, str]:
    """Probe an EtherCAT endpoint; never raises, never counts as a hard failure.

    On Linux with pysoem + root + a real bus this opens the master and reports the
    slave count; otherwise it returns a clear teaching status (needs
    Linux/root/NIC/pysoem) instead of crashing.
    """
    try:
        from iaiops.connectors.ethercat.ops import ethercat_master_state

        info = ethercat_master_state(target)
        return True, (
            f"EtherCAT master_state={info.get('master_state')} "
            f"slaves_found={info.get('slaves_found')}"
        )
    except Exception as exc:  # noqa: BLE001 — environmental miss is a status, not a crash
        return False, str(exc)[:200]


def _probe_bacnet(target) -> tuple[bool, str]:
    """Probe a BACnet endpoint (Who-Is); never raises, never a hard failure.

    Needs the optional BAC0 lib + a reachable BACnet/IP segment; an environmental
    miss returns a teaching status. Preview — not validated against live gear.
    """
    try:
        from iaiops.connectors.bacnet.ops import bacnet_discover

        info = bacnet_discover(target)
        return True, f"BACnet devices_found={info.get('device_count')}"
    except Exception as exc:  # noqa: BLE001 — environmental miss is a status, not a crash
        return False, str(exc)[:200]


def _probe_profinet(target) -> tuple[bool, str]:
    """Probe a PROFINET endpoint; never raises, never counts as a hard failure.

    With pnio-dcp + raw-socket access on the right NIC this runs a DCP IdentifyAll
    and reports the station count; otherwise it returns a clear teaching status
    (needs pnio-dcp + root/admin/CAP_NET_RAW on the PROFINET subnet's NIC).
    """
    try:
        from iaiops.connectors.profinet.ops import profinet_discover

        info = profinet_discover(target)
        return True, f"PROFINET-DCP stations_found={info.get('station_count')}"
    except Exception as exc:  # noqa: BLE001 — environmental miss is a status, not a crash
        return False, str(exc)[:200]


# EtherCAT/PROFINET/BACnet get bespoke, informational run-loop reporting (see
# _report_informational_probe). The registry marks them PROBE_INFORMATIONAL; this
# map pins each to its label + dedicated environmental-miss probe. The drift guard
# asserts these keys match the registry's informational protocols.
_INFORMATIONAL_PROBES = {
    "ethercat": ("EtherCAT", _probe_ethercat),
    "profinet": ("PROFINET", _probe_profinet),
    "bacnet": ("BACnet", _probe_bacnet),
}


def _where(target) -> str:
    """Human-readable 'where' for an endpoint, per protocol (registry-driven)."""
    cap = get_capabilities(target.protocol)
    if cap is None:
        return f"{target.host}:{target.port}"
    return cap.where_hint(target)


def _probe(target) -> tuple[bool, str]:
    """Probe one endpoint read-only; return (ok, detail) — never raises.

    Dispatches through the capability registry: a protocol with no generic
    ``doctor_probe`` (e.g. the informational ethercat/profinet/bacnet, handled
    separately in the run loop) yields the same "No probe implemented" status
    as before instead of a wrong default.
    """
    cap = get_capabilities(target.protocol)
    probe = cap.doctor_probe if cap else UNSUPPORTED
    if probe is UNSUPPORTED:
        return False, f"No probe implemented for protocol '{target.protocol}'."
    try:
        return probe(target)
    except Exception as exc:  # noqa: BLE001 — connectivity is a status, not a crash
        return False, str(exc)[:200]
