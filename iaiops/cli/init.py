"""``iaiops init`` — a friendly, interactive onboarding wizard.

Walks a new user through connecting their first OT endpoint: collects the
non-secret connection details into ``config.yaml`` and the optional password
into the *encrypted* store (never plaintext on disk).
"""

from __future__ import annotations

import getpass

import typer
import yaml

from iaiops.cli._common import cli_errors, console
from iaiops.core.runtime.config import (
    CONFIG_DIR,
    CONFIG_FILE,
    DEFAULT_BACNET_PORT,
    DEFAULT_EIP_PORT,
    DEFAULT_MC_PORT,
    DEFAULT_MODBUS_PORT,
    DEFAULT_MQTT_PORT,
    DEFAULT_S7_PORT,
    SUPPORTED_PROTOCOLS,
)
from iaiops.core.runtime.secretstore import SecretStore, resolve_master_password

_DEFAULT_RULES_YAML = """\
# iaiops governance rules — hot-reloaded from this file (~/.iaiops/rules.yaml).
#
# risk_tiers implement graduated autonomy: each entry maps matching operations
# to an approval tier (none / confirm / dual / review). Tiers 'dual' and
# 'review' require a named human approver — grant one-shot approvals with:
#   iaiops approve <tool> --endpoint <ep> --by <name> [--ttl 600]
#
# NOTE: even WITHOUT this file a builtin safe default applies: high/critical
# risk operations require an approver. This file makes the gate explicit and
# tunable. Deleting it does NOT relax policy for a running server (last-known
# -good rules are retained in memory, fail closed).
risk_tiers:
  - name: high_risk_needs_approver
    min_risk_level: high
    tier: dual
    reason: High/critical-risk (write/command) operations require a named approver.

# Optional examples (uncomment to use):
# deny:
#   - name: no_writes_in_prod
#     operations: ["*_write*"]
#     environments: [production]
#     reason: Writes to production are forbidden outside change control.
# maintenance_window:
#   start: "22:00"
#   end: "06:00"
"""


def _write_default_rules() -> None:
    """Write a starter rules.yaml (explicit risk_tiers) if none exists yet.

    Operators see and can tune the approver gate instead of only hitting the
    builtin default. Never overwrites an existing file.
    """
    from iaiops.core.governance.paths import ops_path

    rules_file = ops_path("rules.yaml")
    if rules_file.exists():
        return
    rules_file.parent.mkdir(parents=True, exist_ok=True)
    try:
        rules_file.parent.chmod(0o700)
    except OSError:
        pass
    rules_file.write_text(_DEFAULT_RULES_YAML, "utf-8")
    try:
        rules_file.chmod(0o600)
    except OSError:
        pass
    console.print(f"[green]✓ Wrote default governance rules:[/] {rules_file}")


def _load_existing() -> list[dict]:
    if not CONFIG_FILE.exists():
        return []
    raw = yaml.safe_load(CONFIG_FILE.read_text("utf-8")) or {}
    return list(raw.get("endpoints", raw.get("targets", [])))


def _write_endpoints(endpoints: list[dict]) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    try:
        CONFIG_DIR.chmod(0o700)
    except OSError:
        pass
    CONFIG_FILE.write_text(
        yaml.safe_dump({"endpoints": endpoints}, sort_keys=False), "utf-8"
    )


def _prompt_protocol(protocol: str, name: str, store):
    """Collect per-protocol connection details; returns (entry, store).

    Any password is stored encrypted under the endpoint name; the returned entry
    holds only non-secret fields.
    """
    entry: dict = {"name": name, "protocol": protocol}
    if protocol == "opcua":
        entry["endpoint_url"] = typer.prompt(
            "OPC-UA endpoint URL", default="opc.tcp://localhost:4840"
        ).strip()
        username = typer.prompt("Username (optional, Enter for anonymous)", default="").strip()
        if username:
            entry["username"] = username
            store = _maybe_store_password(store, name)
    elif protocol == "modbus":
        entry["host"] = typer.prompt("Modbus host (IP/FQDN)").strip()
        entry["port"] = typer.prompt("Port", default=DEFAULT_MODBUS_PORT, type=int)
        entry["unit_id"] = typer.prompt("Unit/device id", default=1, type=int)
    elif protocol == "s7":
        entry["host"] = typer.prompt("S7 PLC host (IP/FQDN)").strip()
        entry["port"] = typer.prompt("Port", default=DEFAULT_S7_PORT, type=int)
        entry["rack"] = typer.prompt("Rack (0 for S7-1200/1500)", default=0, type=int)
        entry["slot"] = typer.prompt("Slot (1 for S7-1200/1500, 2 for S7-300/400)",
                                     default=1, type=int)
    elif protocol == "mc":
        entry["host"] = typer.prompt("Mitsubishi PLC host (IP/FQDN)").strip()
        entry["port"] = typer.prompt("Port", default=DEFAULT_MC_PORT, type=int)
        entry["plctype"] = typer.prompt("PLC type (Q|L|QnA|iQ-R|iQ-L)", default="Q").strip()
    elif protocol in ("ethernetip", "eip"):
        entry["protocol"] = "ethernetip"
        entry["host"] = typer.prompt("EtherNet/IP (Logix) host (IP/FQDN)").strip()
        entry["slot"] = typer.prompt(
            "Controller slot (0 for CompactLogix; CPU slot for ControlLogix)",
            default=0, type=int,
        )
        entry["port"] = typer.prompt("Port", default=DEFAULT_EIP_PORT, type=int)
    elif protocol == "ethercat":
        console.print(
            "[yellow]EtherCAT needs Linux + root (or CAP_NET_RAW) + a dedicated NIC "
            "cabled to the bus + real slaves, and the optional extra "
            "'pip install iaiops[ethercat]'. No software simulator; macOS "
            "unsupported.[/]"
        )
        entry["nic"] = typer.prompt(
            "Dedicated NIC interface name (e.g. eth1)", default="eth1"
        ).strip()
        entry["expected_slaves"] = typer.prompt(
            "Expected slave count (0 = unknown / do not check)", default=0, type=int
        )
    elif protocol == "profinet":
        console.print(
            "[yellow]PROFINET-DCP needs raw-socket access (root/admin/CAP_NET_RAW) on "
            "the NIC on the PROFINET subnet, and the optional extra "
            "'pip install iaiops[profinet]'. Read-only discovery/identify — no RT "
            "cyclic data.[/]"
        )
        entry["host"] = typer.prompt(
            "THIS machine's IP on the PROFINET subnet (DCP broadcast source)"
        ).strip()
    elif protocol == "bacnet":
        console.print(
            "[yellow]BACnet/IP read-only facility/HVAC monitoring — optional extra "
            "'pip install iaiops[bacnet]'. Preview: not yet validated against live gear.[/]"
        )
        entry["host"] = typer.prompt(
            "THIS machine's BACnet/IP interface (ip or ip/mask, e.g. 10.0.0.5/24)"
        ).strip()
        entry["port"] = typer.prompt("Port", default=DEFAULT_BACNET_PORT, type=int)
    elif protocol == "mtconnect":
        entry["agent_url"] = typer.prompt(
            "MTConnect agent base URL", default="http://localhost:5000"
        ).strip()
    elif protocol == "iolink":
        console.print(
            "[yellow]IO-Link master JSON interface (read-only sensor visibility) — "
            "'pip install iaiops[iolink]'. flavor: iotcore (ifm IoT-Core, default) "
            "or rest (plain-REST masters).[/]"
        )
        entry["agent_url"] = typer.prompt(
            "IO-Link master base URL", default="http://192.168.0.10"
        ).strip()
        entry["flavor"] = typer.prompt(
            "JSON flavor (iotcore|rest)", default="iotcore"
        ).strip().lower()
    elif protocol == "mqtt":
        entry["host"] = typer.prompt("MQTT broker host (IP/FQDN)").strip()
        entry["use_tls"] = typer.confirm("Use TLS?", default=False)
        default_port = 8883 if entry["use_tls"] else DEFAULT_MQTT_PORT
        entry["port"] = typer.prompt("Port", default=default_port, type=int)
        entry["topic"] = typer.prompt(
            "Default topic filter", default="spBv1.0/#"
        ).strip()
        username = typer.prompt("Username (optional, Enter for none)", default="").strip()
        if username:
            entry["username"] = username
            store = _maybe_store_password(store, name)
    return entry, store


def _maybe_store_password(store, name: str):
    """Prompt for a hidden password and store it encrypted under ``name``."""
    secret = getpass.getpass(f"Password for '{name}' (hidden, Enter to skip): ")
    if secret:
        store = store.set(name, secret)
    return store


@cli_errors
def init_cmd() -> None:
    """Interactively set up your first OT endpoint (any supported protocol)."""
    console.print("[bold cyan]Industrial-AIOps (iaiops) — setup wizard[/]")
    console.print(
        "Collects connection details (saved to config.yaml) and any password "
        "(saved [bold]encrypted[/] to secrets.enc). Read-only, preview.\n"
    )
    _write_default_rules()

    console.print("[bold]Step 1 — master password[/]")
    console.print(
        "[dim]Encrypts secrets.enc. Set it via IAIOPS_MASTER_PASSWORD for "
        "non-interactive/MCP use. (Skip if all your endpoints are anonymous.)[/]"
    )
    password = resolve_master_password(confirm_if_new=True)
    store = SecretStore.unlock(password)

    endpoints = _load_existing()
    existing_names = {e.get("name") for e in endpoints}

    while True:
        console.print("\n[bold]Step 2 — add an endpoint[/]")
        name = typer.prompt("Endpoint name (e.g. line1)").strip()
        if name in existing_names:
            if not typer.confirm(f"'{name}' already exists — overwrite?", default=False):
                continue
            endpoints = [e for e in endpoints if e.get("name") != name]
            existing_names.discard(name)

        protocol = typer.prompt(
            f"Protocol {SUPPORTED_PROTOCOLS}", default="opcua"
        ).strip()
        if protocol not in SUPPORTED_PROTOCOLS:
            console.print("[yellow]Unknown protocol; defaulting to 'opcua'.[/]")
            protocol = "opcua"

        entry, store = _prompt_protocol(protocol, name, store)
        endpoints.append(entry)
        existing_names.add(name)
        _write_endpoints(endpoints)
        console.print(f"[green]✓ Saved endpoint '{name}'.[/]")

        if not typer.confirm("\nAdd another endpoint?", default=False):
            break

    console.print(f"\n[green]✓ Setup complete.[/] Config: {CONFIG_FILE}")
    console.print(
        "[dim]Tip: export IAIOPS_MASTER_PASSWORD=... so the MCP server and CLI "
        "can unlock secrets non-interactively.[/]"
    )
    if typer.confirm("Run a connectivity check now (iaiops doctor)?", default=True):
        from iaiops.doctor import run_doctor

        raise typer.Exit(run_doctor())
