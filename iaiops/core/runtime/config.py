"""Configuration management for iaiops.

Loads OT endpoint targets from a YAML config file (``~/.iaiops/config.yaml``).
Each endpoint declares a ``protocol`` (``opcua`` or ``modbus``) and the
non-secret connection details for that protocol:

  * OPC-UA: ``endpoint_url`` (e.g. ``opc.tcp://plc.lan:4840``), optional
    ``security_mode`` / ``security_policy`` / ``username``.
  * Modbus-TCP: ``host`` / ``port`` (default 502) / ``unit_id`` (a.k.a.
    device/slave id, default 1).

Secrets are NEVER stored here and never on disk in plaintext: the per-endpoint
password (OPC-UA username/password auth, or a Modbus auth proxy) lives in the
encrypted store ``~/.iaiops/secrets.enc`` (see
:mod:`iaiops.core.runtime.secretstore`), keyed by the endpoint target name.

For backward compatibility a legacy plaintext env var
(``OT_<NAME_UPPER>_PASSWORD``) is honoured as a fallback, with a warning
nudging migration to the encrypted store.

Endpoints may also declare ``tags`` — monitored points with optional warn/alarm
thresholds — used by the ``health_summary`` problem-surfacing tool.
"""

from __future__ import annotations

import logging
import os
import stat
from dataclasses import dataclass
from pathlib import Path

import yaml
from dotenv import load_dotenv

from iaiops.core.runtime.secretstore import (
    SecretStoreError,
    get_secret,
    has_store,
)

CONFIG_DIR = Path.home() / ".iaiops"
CONFIG_FILE = CONFIG_DIR / "config.yaml"
ENV_FILE = CONFIG_DIR / ".env"

# Legacy env-var prefix/suffix; also used by the migration helper.
SECRET_ENV_PREFIX = "OT_"  # nosec B105 — env var prefix, not a secret
SECRET_ENV_SUFFIX = "_PASSWORD"  # nosec B105 — env var suffix, not a secret

_log = logging.getLogger("iaiops.core.runtime.config")

# OT protocols this tool officially supports. ``eip`` is an accepted alias for
# ``ethernetip`` (normalized to ``ethernetip`` on load). ``ethercat`` is a REAL
# driver backed by the OPTIONAL ``pysoem`` extra (Linux + root/CAP_NET_RAW + a
# dedicated NIC + real slaves; no software simulator) — see iaiops.connectors.ethercat.ops.
SUPPORTED_PROTOCOLS = (
    "opcua",
    "modbus",
    "s7",
    "mc",
    "mtconnect",
    "mqtt",
    "ethernetip",
    "eip",
    "ethercat",
    "secsgem",  # host-side SECS/GEM (was registered everywhere else but missing here)
    "profinet",
    # Building edition (read-only): BACnet/IP (facility / HVAC / 厂务).
    "bacnet",
    # Process edition (read-only): HART-IP process instrumentation.
    "hart",
    # Omron FINS (CS/CJ/CP/NX-via-FINS; in-repo stdlib client, UDP 9600 + TCP).
    "fins",
    # IO-Link master JSON integration (read-only sensor-level visibility).
    "iolink",
)

DEFAULT_MODBUS_PORT = 502
DEFAULT_OPCUA_PORT = 4840
DEFAULT_S7_PORT = 102  # ISO-on-TCP (RFC1006)
DEFAULT_MC_PORT = 5007  # Mitsubishi MC 3E binary (common default)
DEFAULT_MQTT_PORT = 1883  # plain MQTT (8883 when TLS)
DEFAULT_MQTT_TLS_PORT = 8883
DEFAULT_EIP_PORT = 44818  # EtherNet/IP (CIP over TCP)
DEFAULT_SECSGEM_PORT = 5000  # HSMS (SECS-II over TCP) default
DEFAULT_BACNET_PORT = 47808  # BACnet/IP (UDP 0xBAC0)
DEFAULT_HART_PORT = 5094  # HART-IP (UDP/TCP 5094)
DEFAULT_FINS_PORT = 9600  # Omron FINS (UDP default; FINS/TCP same port)
DEFAULT_IOLINK_PORT = 80  # IO-Link master HTTP/JSON interface

# Connect/request timeout applied to every TCP-based client builder so a dead
# endpoint fails in seconds, not the OS TCP default (60-120s+). Override the
# fleet default with the IAIOPS_TIMEOUT_S env var; override per endpoint with
# 'timeout_s:' in its config entry.
DEFAULT_TIMEOUT_S = 10.0
TIMEOUT_ENV_VAR = "IAIOPS_TIMEOUT_S"

# Per-protocol default TCP port, used by load_config + the init wizard.
_DEFAULT_PORTS = {
    "opcua": DEFAULT_OPCUA_PORT,
    "modbus": DEFAULT_MODBUS_PORT,
    "s7": DEFAULT_S7_PORT,
    "mc": DEFAULT_MC_PORT,
    "mqtt": DEFAULT_MQTT_PORT,
    "ethernetip": DEFAULT_EIP_PORT,
    "secsgem": DEFAULT_SECSGEM_PORT,
    "bacnet": DEFAULT_BACNET_PORT,
    "hart": DEFAULT_HART_PORT,
    "fins": DEFAULT_FINS_PORT,
    "iolink": DEFAULT_IOLINK_PORT,
}


def _check_dir_permissions() -> None:
    """Warn if the config dir is accessible beyond the owner (should be 700)."""
    if not CONFIG_DIR.exists():
        return
    try:
        mode = CONFIG_DIR.stat().st_mode
        if mode & (stat.S_IRWXG | stat.S_IRWXO):
            _log.warning(
                "Security warning: %s has permissions %s (should be 700). Run: chmod 700 %s",
                CONFIG_DIR,
                oct(stat.S_IMODE(mode)),
                CONFIG_DIR,
            )
    except OSError:
        pass


def _load_env() -> None:
    """Load ~/.iaiops/.env so legacy per-endpoint passwords are available."""
    if ENV_FILE.exists():
        load_dotenv(ENV_FILE)


_check_dir_permissions()
_load_env()


def password_env_var(target_name: str) -> str:
    """Return the legacy env var name holding an endpoint's password.

    ``line1`` → ``OT_LINE1_PASSWORD``. Non-alphanumeric characters in the
    name become underscores so it is a valid shell identifier.
    """
    safe = "".join(c if c.isalnum() else "_" for c in target_name).upper()
    return f"{SECRET_ENV_PREFIX}{safe}{SECRET_ENV_SUFFIX}"


def _resolve_secret(name: str) -> str:
    """Resolve an endpoint's password: encrypted store first, then legacy env.

    Returns "" when no secret is found anywhere — many OT endpoints are
    anonymous (no auth), so a missing password is a warning surfaced by
    ``iaiops doctor``, not a hard error.
    """
    if has_store():
        try:
            return get_secret(name)
        except SecretStoreError:
            pass  # fall through to legacy env var
    legacy = os.environ.get(password_env_var(name))
    if legacy:
        _log.warning(
            "Using plaintext env var %s. Migrate to the encrypted store with "
            "'iaiops secret migrate'.",
            password_env_var(name),
        )
        return legacy
    return ""


@dataclass(frozen=True)
class MonitorTag:
    """A monitored point with optional warn/alarm thresholds.

    ``ref`` is an OPC-UA node id (e.g. ``ns=2;i=5``) or a Modbus register
    address (as a string). Thresholds are optional; any combination of
    high/low warn/alarm bounds may be set. Used by ``health_summary``.
    """

    ref: str
    label: str = ""
    warn_high: float | None = None
    alarm_high: float | None = None
    warn_low: float | None = None
    alarm_low: float | None = None

    def classify(self, value: float) -> str:
        """Classify a numeric value as 'ok', 'warn', or 'alarm'."""
        if self.alarm_high is not None and value >= self.alarm_high:
            return "alarm"
        if self.alarm_low is not None and value <= self.alarm_low:
            return "alarm"
        if self.warn_high is not None and value >= self.warn_high:
            return "warn"
        if self.warn_low is not None and value <= self.warn_low:
            return "warn"
        return "ok"


@dataclass(frozen=True)
class TargetConfig:
    """An OT endpoint connection target (vendor-neutral, multi-protocol).

    Non-secret connection details per protocol:

      * ``opcua``     — ``endpoint_url``, optional ``username`` / security_*.
      * ``modbus``    — ``host`` / ``port`` (502) / ``unit_id``.
      * ``s7``        — ``host`` / ``port`` (102) / ``rack`` / ``slot`` (Siemens
                        + 仿西门子 国产 PLCs, ISO-on-TCP).
      * ``mc``        — ``host`` / ``port`` (5007) / ``plctype`` (Mitsubishi
                        Q/L/QnA/iQ-R, MC 3E binary).
      * ``mtconnect`` — ``agent_url`` (HTTP agent base, e.g. http://host:5000).
      * ``mqtt``      — ``host`` / ``port`` (1883/8883) / ``topic`` / ``use_tls``
                        / ``username`` (Sparkplug B / UNS).
      * ``ethernetip``— ``host`` / ``slot`` (Rockwell/Allen-Bradley Logix,
                        ControlLogix/CompactLogix, CIP via pycomm3). ``eip`` is
                        an accepted alias.
      * ``ethercat``  — ``nic`` (the dedicated NIC interface name, e.g. ``eth1``)
                        / optional ``expected_slaves`` (EtherCAT fieldbus master
                        via pysoem/SOEM; Linux + root/CAP_NET_RAW + real slaves).
      * ``profinet``  — ``host`` (the LOCAL interface IP the DCP L2 broadcast goes
                        out on, e.g. the IP of the NIC on the PROFINET subnet).
                        Read-only DCP discovery/identify via pnio-dcp; needs L2
                        raw-socket access (root/admin). NO RT cyclic data.
      * ``fins``      — ``host`` / ``port`` (9600) / ``transport`` (``udp``
                        default | ``tcp``) (Omron CS/CJ/CP/NX-via-FINS; in-repo
                        stdlib client, W227/W342 framing).
      * ``bacnet``    — ``host`` (THIS machine's local BACnet/IP interface, optionally
                        ``ip/mask`` e.g. ``10.0.0.5/24``) / ``port`` (47808). Read-only
                        facility/HVAC monitoring via the ``bacnet`` (BAC0) extra.
      * ``hart``      — ``host`` / ``port`` (5094) / ``transport`` (``udp`` default |
                        ``tcp``) / optional ``long_address``: the transmitter's 5-byte
                        unique address as 10 hex digits (spaces/colons/dashes between
                        bytes allowed, e.g. ``"26 06 12 34 56"``). Empty = auto-discover
                        via a short-frame Command 0 identity poll.

    The password / MQTT password is resolved from the encrypted store, never
    stored here.
    """

    name: str
    protocol: str = "opcua"
    endpoint_url: str = ""
    host: str = ""
    port: int = 0
    unit_id: int = 1
    # Wire transport selector (per-protocol meaning, resolved at parse time):
    #   * Modbus — "tcp" (default) or "rtu" (serial); "rtu" + the serial_* params
    #     select pymodbus's ModbusSerialClient instead of ModbusTcpClient.
    #   * HART-IP — "udp" (default) or "tcp"; both speak the same 8-byte framing
    #     on port 5094, "tcp" picks the stream (length-delimited) session.
    # Empty means "protocol default" (Modbus→tcp, HART→udp) so a directly built
    # TargetConfig is unsurprising; the YAML parser always fills in a concrete value.
    transport: str = ""
    serial_port: str = ""
    baudrate: int = 19200
    parity: str = "N"
    stopbits: int = 1
    bytesize: int = 8
    security_mode: str = "None"
    security_policy: str = "None"
    username: str = ""
    # S7comm (Siemens / 仿西门子)
    rack: int = 0
    slot: int = 1
    # Mitsubishi MC
    plctype: str = "Q"
    # MTConnect + IO-Link master (HTTP): base URL of the agent/master.
    agent_url: str = ""
    # IO-Link master JSON dialect: 'iotcore' (ifm IoT-Core POST envelope,
    # default) or 'rest' (plain-REST GET). Empty = protocol default (iotcore).
    flavor: str = ""
    # MQTT / Sparkplug B / UNS
    topic: str = ""
    use_tls: bool = False
    # Mutual-TLS / certificate auth (paths only — never key material inline):
    # OPC-UA cert security mode + MQTT client certs. Empty = anonymous/no-cert.
    ca_cert: str = ""  # CA bundle to verify the peer (MQTT ca_certs)
    client_cert: str = ""  # our client certificate (OPC-UA + MQTT)
    client_key: str = ""  # our client private key
    server_cert: str = ""  # expected server certificate (OPC-UA, optional)
    # HART-IP: the field device's 5-byte unique long address as 10 hex digits
    # (spaces/colons/dashes between bytes allowed, e.g. "26 06 12 34 56").
    # Empty = discover it via a short-frame Command 0 poll; validated by the
    # HART connector codec at use time with a teaching error.
    long_address: str = ""
    # EtherCAT (pysoem/SOEM fieldbus master) — and PROFINET-DCP, which binds the
    # local interface by its IP via ``host`` (the NIC the DCP broadcast goes out on).
    nic: str = ""
    expected_slaves: int = 0
    # Connect/request timeout (seconds) threaded into every client builder so a
    # dead endpoint fails fast instead of hanging on the OS TCP timeout.
    timeout_s: float = DEFAULT_TIMEOUT_S
    tags: tuple[MonitorTag, ...] = ()

    def __post_init__(self) -> None:
        if self.protocol not in SUPPORTED_PROTOCOLS:
            raise ValueError(
                f"Endpoint '{self.name}' has unsupported protocol "
                f"'{self.protocol}'. Supported: {', '.join(SUPPORTED_PROTOCOLS)}. "
                f"Request more protocols via a GitHub issue/PR."
            )

    def password(self) -> str:
        """Resolve the endpoint password from the encrypted store (or env).

        May be empty (valid for anonymous OT endpoints).
        """
        return _resolve_secret(self.name)

    def tag_for(self, ref: str) -> MonitorTag | None:
        """Return the configured monitor tag for a node id / address, if any."""
        for t in self.tags:
            if t.ref == ref:
                return t
        return None


# Historian readers the optional per-site ``historian:`` block may select.
SUPPORTED_HISTORIAN_READERS = ("sqlite", "tdengine", "iotdb")

# Secret-store key holding the historian password (never stored in YAML).
HISTORIAN_SECRET_NAME = "historian"  # nosec B105 — a key name, not a secret


@dataclass(frozen=True)
class HistorianConfig:
    """Optional per-site historian READ source (A7).

    Declared as a top-level ``historian:`` block in ``config.yaml``::

        historian:
          reader: tdengine          # sqlite | tdengine | iotdb
          host: 10.0.0.20           # TSDB readers only
          port: 6030
          user: root
          database: iaiops          # TDengine db / IoTDB storage group / sqlite path
          db_path: ~/.iaiops/data.db   # sqlite reader only (optional override)

    The password (TSDB readers) is resolved from the encrypted secret store
    under the name ``historian`` — never stored here. Absent block ⇒ no
    historian read source; the RCA copilot then behaves exactly as before.
    """

    reader: str
    host: str = ""
    port: int = 0
    user: str = ""
    database: str = ""
    db_path: str = ""

    def __post_init__(self) -> None:
        if self.reader not in SUPPORTED_HISTORIAN_READERS:
            raise ValueError(
                f"historian.reader '{self.reader}' is unsupported. Supported: "
                f"{', '.join(SUPPORTED_HISTORIAN_READERS)}."
            )

    def password(self) -> str:
        """Resolve the historian password from the encrypted store (or env)."""
        return _resolve_secret(HISTORIAN_SECRET_NAME)

    def reader_opts(self) -> dict:
        """Non-empty connection kwargs for ``get_reader(self.reader, **opts)``."""
        opts: dict = {}
        if self.host:
            opts["host"] = self.host
        if self.port:
            opts["port"] = self.port
        if self.user:
            opts["user"] = self.user
        if self.database:
            opts["database"] = self.database
        if self.db_path:
            opts["db_path"] = self.db_path
        if self.reader != "sqlite":
            secret = self.password()
            if secret:
                opts["password"] = secret
        return opts


@dataclass(frozen=True)
class AppConfig:
    """Top-level application config."""

    targets: tuple[TargetConfig, ...] = ()
    historian: HistorianConfig | None = None

    def get_target(self, name: str) -> TargetConfig:
        for t in self.targets:
            if t.name == name:
                return t
        available = ", ".join(t.name for t in self.targets) or "(none)"
        raise KeyError(f"Endpoint '{name}' not found. Available: {available}")

    @property
    def default_target(self) -> TargetConfig:
        if not self.targets:
            raise ValueError(
                "No endpoints configured. Add an 'endpoints:' list to "
                "~/.iaiops/config.yaml (or run 'iaiops init')."
            )
        return self.targets[0]


def _parse_tags(raw_tags: list) -> tuple[MonitorTag, ...]:
    """Parse the optional ``tags`` list of a config endpoint."""
    out: list[MonitorTag] = []
    for t in raw_tags or []:
        ref = str(t.get("ref") or t.get("node_id") or t.get("address") or "").strip()
        if not ref:
            continue
        out.append(
            MonitorTag(
                ref=ref,
                label=str(t.get("label", "")),
                warn_high=_opt_float(t.get("warn_high")),
                alarm_high=_opt_float(t.get("alarm_high")),
                warn_low=_opt_float(t.get("warn_low")),
                alarm_low=_opt_float(t.get("alarm_low")),
            )
        )
    return tuple(out)


def _opt_float(value: object) -> float | None:
    """Coerce an optional threshold to float, tolerating None/blank."""
    if value is None or value == "":
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _default_port(protocol: str, given: object, use_tls: bool = False) -> int:
    """Resolve the endpoint port, defaulting per protocol."""
    if given not in (None, "", 0):
        try:
            return int(given)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            pass
    if protocol == "mqtt" and use_tls:
        return DEFAULT_MQTT_TLS_PORT
    return _DEFAULT_PORTS.get(protocol, DEFAULT_OPCUA_PORT)


def _modbus_transport(d: dict) -> str:
    """Resolve the Modbus transport: explicit 'transport', else inferred from serial."""
    given = str(d.get("transport", "") or "").strip().lower()
    if given in ("rtu", "serial"):
        return "rtu"
    if given == "tcp":
        return "tcp"
    # Infer: a serial port without an explicit transport implies RTU.
    if d.get("serial_port") or d.get("com_port"):
        return "rtu"
    return "tcp"


def _hart_transport(d: dict) -> str:
    """Resolve the HART-IP transport: 'tcp' only when explicitly requested, else 'udp'.

    HART-IP runs over both UDP and TCP on port 5094 with identical 8-byte framing;
    UDP is the historical default, so anything that is not an explicit 'tcp' (blank,
    'udp', or a typo) resolves to 'udp' rather than silently switching transports.
    """
    given = str(d.get("transport", "") or "").strip().lower()
    return "tcp" if given == "tcp" else "udp"


def _fins_transport(d: dict) -> str:
    """Resolve the FINS transport: 'tcp' only when explicitly requested, else 'udp'.

    FINS runs over UDP (the historical default, port 9600) and FINS/TCP (same
    port, extra 16-byte header + node handshake); anything that is not an
    explicit 'tcp' resolves to 'udp' rather than silently switching transports.
    """
    given = str(d.get("transport", "") or "").strip().lower()
    return "tcp" if given == "tcp" else "udp"


def _resolve_transport(protocol: str, d: dict) -> str:
    """Pick the per-protocol transport resolver (Modbus tcp/rtu vs HART/FINS udp/tcp)."""
    if protocol == "hart":
        return _hart_transport(d)
    if protocol == "fins":
        return _fins_transport(d)
    return _modbus_transport(d)


def _default_timeout_s() -> float:
    """Fleet-wide default connect timeout: IAIOPS_TIMEOUT_S env, else 10.0s."""
    raw = os.environ.get(TIMEOUT_ENV_VAR, "").strip()
    if raw:
        try:
            value = float(raw)
            if value > 0:
                return value
            _log.warning("Ignoring non-positive %s=%r.", TIMEOUT_ENV_VAR, raw)
        except ValueError:
            _log.warning(
                "Ignoring invalid %s=%r (expected seconds, e.g. 10).",
                TIMEOUT_ENV_VAR,
                raw,
            )
    return DEFAULT_TIMEOUT_S


def _parse_timeout_s(d: dict) -> float:
    """Per-endpoint 'timeout_s' (alias 'timeout'), else the fleet default."""
    given = d.get("timeout_s", d.get("timeout"))
    if given not in (None, ""):
        try:
            value = float(given)  # type: ignore[arg-type]
            if value > 0:
                return value
        except (TypeError, ValueError):
            pass
        _log.warning(
            "Endpoint %r has invalid timeout_s=%r; using the default.",
            d.get("name", "?"),
            given,
        )
    return _default_timeout_s()


def _as_bool(value: object) -> bool:
    """Coerce a YAML scalar to bool (tolerates 'true'/'1'/'yes')."""
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def load_config(config_path: Path | None = None) -> AppConfig:
    """Load config from YAML.

    Returns an empty config (no endpoints) when no file exists — the
    CLI/doctor then prints a teaching message rather than crashing.
    """
    path = config_path or CONFIG_FILE
    if not path.exists():
        return AppConfig()

    with open(path) as f:
        raw = yaml.safe_load(f) or {}

    # Accept either 'endpoints' or 'targets' as the top-level list key.
    entries = raw.get("endpoints", raw.get("targets", []))

    targets = tuple(_parse_target(d) for d in entries)
    return AppConfig(targets=targets, historian=_parse_historian(raw.get("historian")))


def load_config_env() -> AppConfig:
    """Load config honoring the ``IAIOPS_CONFIG`` path override (MCP/tool paths)."""
    override = os.environ.get("IAIOPS_CONFIG")
    return load_config(Path(override) if override else None)


def _parse_historian(raw: object) -> HistorianConfig | None:
    """Build the optional per-site historian READ block; absent/blank ⇒ None."""
    if not isinstance(raw, dict) or not str(raw.get("reader", "")).strip():
        return None
    return HistorianConfig(
        reader=str(raw["reader"]).strip().lower(),
        host=str(raw.get("host", "") or ""),
        port=int(raw.get("port", 0) or 0),
        user=str(raw.get("user", "") or ""),
        database=str(raw.get("database", "") or ""),
        db_path=str(raw.get("db_path", "") or ""),
    )


def _parse_target(d: dict) -> TargetConfig:
    """Build one immutable TargetConfig from a raw config dict."""
    protocol = d.get("protocol", "opcua")
    if protocol == "eip":  # normalize the accepted alias
        protocol = "ethernetip"
    use_tls = _as_bool(d.get("use_tls", False))
    return TargetConfig(
        name=d["name"],
        protocol=protocol,
        endpoint_url=d.get("endpoint_url", ""),
        host=d.get("host", "") or d.get("broker", ""),
        port=_default_port(protocol, d.get("port"), use_tls),
        unit_id=int(d.get("unit_id", 1) or 1),
        # Wire transport, resolved per protocol: Modbus tcp|rtu (a 'serial_port'/
        # 'com_port' alias implies rtu); HART-IP udp|tcp (udp default).
        transport=_resolve_transport(protocol, d),
        serial_port=str(d.get("serial_port", "") or d.get("com_port", "")),
        baudrate=int(d.get("baudrate", 19200) or 19200),
        parity=str(d.get("parity", "N") or "N").upper()[:1],
        stopbits=int(d.get("stopbits", 1) or 1),
        bytesize=int(d.get("bytesize", 8) or 8),
        security_mode=str(d.get("security_mode", "None")),
        security_policy=str(d.get("security_policy", "None")),
        username=str(d.get("username", "")),
        rack=int(d.get("rack", 0) or 0),
        # slot may legitimately be 0 (CompactLogix / many ControlLogix), so do
        # NOT collapse a 0 to the default with ``or``.
        slot=int(d["slot"]) if d.get("slot") not in (None, "") else 1,
        plctype=str(d.get("plctype", "Q") or "Q"),
        agent_url=str(d.get("agent_url", "")),
        flavor=str(d.get("flavor", "") or "").strip().lower(),
        topic=str(d.get("topic", "")),
        use_tls=use_tls,
        # TLS / mutual-auth certificate paths (accept common aliases).
        ca_cert=str(d.get("ca_cert", "") or d.get("ca_certs", "")),
        client_cert=str(d.get("client_cert", "") or d.get("certfile", "")),
        client_key=str(d.get("client_key", "") or d.get("keyfile", "")),
        server_cert=str(d.get("server_cert", "")),
        # HART-IP unique long address (optional; empty = Command 0 discovery).
        long_address=str(d.get("long_address", "") or ""),
        # EtherCAT: NIC interface name (accept 'interface' as an alias).
        nic=str(d.get("nic", "") or d.get("interface", "")),
        expected_slaves=int(d.get("expected_slaves", 0) or 0),
        timeout_s=_parse_timeout_s(d),
        tags=_parse_tags(d.get("tags", [])),
    )
