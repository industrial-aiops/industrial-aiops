"""Environment and connectivity diagnostics for iaiops.

A doctor must survive the thing it diagnoses being unhealthy: every connectivity
probe is reported as a status line, never raised as a traceback.
"""

from __future__ import annotations

from rich.console import Console

from iaiops.core.runtime.config import CONFIG_FILE, ENV_FILE, load_config, password_env_var
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
        _console.print(
            f"[yellow]! No config file ({CONFIG_FILE}); run 'iaiops init'.[/]"
        )

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
    elif ENV_FILE.exists():
        _console.print(
            f"[yellow]! Using legacy plaintext .env ({ENV_FILE}). Migrate with "
            f"'iaiops secret migrate'.[/]"
        )
    else:
        _console.print(
            "[yellow]! No encrypted secret store yet. Run 'iaiops init' to set "
            "up credentials (stored encrypted). Many OT endpoints are anonymous "
            "and need no password.[/]"
        )

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
        # EtherCAT can only be probed on Linux + root + NIC + real slaves (no
        # simulator). Treat an environmental miss as an informational status, not
        # a counted probe failure, so doctor stays useful off the bus.
        if target.protocol == "ethercat":
            ok, detail = _probe_ethercat(target)
            if ok:
                _console.print(f"[green]✓ Reachable '{target.name}' — {detail}[/]")
            else:
                _console.print(f"[yellow]! EtherCAT '{target.name}' — {detail}[/]")
            continue
        # OPC-UA: on failure, classify *why* (certificate / security policy / auth /
        # firewall / …) and print the conclusion + the fix, not a raw error string.
        if target.protocol == "opcua":
            ok, detail = _probe(target)
            if ok:
                _console.print(f"[green]✓ Reachable '{target.name}' — {detail}[/]")
            else:
                v = _diagnose_opcua(target)
                _console.print(
                    f"[red]✗ OPC-UA '{target.name}' — {v['class']}: {v['diagnosis']}[/]"
                )
                _console.print(f"  [yellow]→ {v['remediation']}[/]")
                problems += 1
            continue
        ok, detail = _probe(target)
        if ok:
            _console.print(f"[green]✓ Reachable '{target.name}' — {detail}[/]")
        else:
            _console.print(f"[red]✗ Probe '{target.name}' failed: {detail}[/]")
            problems += 1

    return 1 if problems else 0


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


def _where(target) -> str:
    """Human-readable 'where' for an endpoint, per protocol."""
    if target.protocol == "opcua":
        return target.endpoint_url or "?"
    if target.protocol == "mtconnect":
        return target.agent_url or f"{target.host}:{target.port}"
    if target.protocol == "s7":
        return f"{target.host}:{target.port} rack={target.rack} slot={target.slot}"
    if target.protocol == "mc":
        return f"{target.host}:{target.port} ({target.plctype})"
    if target.protocol == "mqtt":
        topic = target.topic or "#"
        return f"{target.host}:{target.port} topic={topic} tls={target.use_tls}"
    if target.protocol in ("ethernetip", "eip"):
        return f"{target.host} slot={target.slot}"
    if target.protocol == "ethercat":
        return f"nic={target.nic or target.host or '?'}"
    return f"{target.host}:{target.port}"


def _probe(target) -> tuple[bool, str]:
    """Probe one endpoint read-only; return (ok, detail) — never raises."""
    try:
        if target.protocol == "opcua":
            from iaiops.connectors.opcua.ops import server_info

            info = server_info(target)
            return True, f"OPC-UA state={info.get('state')} ({info.get('product_name', '?')})"
        if target.protocol == "modbus":
            from iaiops.connectors.modbus.ops import modbus_read_holding

            result = modbus_read_holding(target, address=0, count=1)
            return True, f"Modbus holding[0]={result.get('decoded')}"
        if target.protocol == "s7":
            from iaiops.connectors.s7.ops import s7_cpu_info

            info = s7_cpu_info(target)
            return True, f"S7 cpu_status={info.get('cpu_status')}"
        if target.protocol == "mc":
            from iaiops.connectors.mc.ops import mc_cpu_status

            info = mc_cpu_status(target)
            return True, f"MC cpu={info.get('cpu_type')}"
        if target.protocol == "mtconnect":
            from iaiops.connectors.mtconnect.ops import mtconnect_current

            cur = mtconnect_current(target)
            return True, f"MTConnect observations={cur.get('observation_count')}"
        if target.protocol == "mqtt":
            from iaiops.connectors.sparkplug.ops import mqtt_read_topic

            out = mqtt_read_topic(target, count=1, timeout_s=3)
            return True, f"MQTT connected, messages={out.get('message_count')}"
        if target.protocol in ("ethernetip", "eip"):
            from iaiops.connectors.eip.ops import eip_controller_info

            info = eip_controller_info(target)
            ctrl = info.get("controller", {})
            return True, f"EtherNet/IP controller={ctrl.get('product_name', '?')}"
    except Exception as exc:  # noqa: BLE001 — connectivity is a status, not a crash
        return False, str(exc)[:200]
    return False, f"No probe implemented for protocol '{target.protocol}'."
