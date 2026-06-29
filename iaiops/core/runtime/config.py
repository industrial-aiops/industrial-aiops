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
    "opcua", "modbus", "s7", "mc", "mtconnect", "mqtt", "ethernetip", "eip", "ethercat",
)

DEFAULT_MODBUS_PORT = 502
DEFAULT_OPCUA_PORT = 4840
DEFAULT_S7_PORT = 102  # ISO-on-TCP (RFC1006)
DEFAULT_MC_PORT = 5007  # Mitsubishi MC 3E binary (common default)
DEFAULT_MQTT_PORT = 1883  # plain MQTT (8883 when TLS)
DEFAULT_MQTT_TLS_PORT = 8883
DEFAULT_EIP_PORT = 44818  # EtherNet/IP (CIP over TCP)

# Per-protocol default TCP port, used by load_config + the init wizard.
_DEFAULT_PORTS = {
    "opcua": DEFAULT_OPCUA_PORT,
    "modbus": DEFAULT_MODBUS_PORT,
    "s7": DEFAULT_S7_PORT,
    "mc": DEFAULT_MC_PORT,
    "mqtt": DEFAULT_MQTT_PORT,
    "ethernetip": DEFAULT_EIP_PORT,
}


def _check_dir_permissions() -> None:
    """Warn if the config dir is accessible beyond the owner (should be 700)."""
    if not CONFIG_DIR.exists():
        return
    try:
        mode = CONFIG_DIR.stat().st_mode
        if mode & (stat.S_IRWXG | stat.S_IRWXO):
            _log.warning(
                "Security warning: %s has permissions %s (should be 700). "
                "Run: chmod 700 %s",
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

    The password / MQTT password is resolved from the encrypted store, never
    stored here.
    """

    name: str
    protocol: str = "opcua"
    endpoint_url: str = ""
    host: str = ""
    port: int = 0
    unit_id: int = 1
    security_mode: str = "None"
    security_policy: str = "None"
    username: str = ""
    # S7comm (Siemens / 仿西门子)
    rack: int = 0
    slot: int = 1
    # Mitsubishi MC
    plctype: str = "Q"
    # MTConnect (HTTP)
    agent_url: str = ""
    # MQTT / Sparkplug B / UNS
    topic: str = ""
    use_tls: bool = False
    # EtherCAT (pysoem/SOEM fieldbus master)
    nic: str = ""
    expected_slaves: int = 0
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


@dataclass(frozen=True)
class AppConfig:
    """Top-level application config."""

    targets: tuple[TargetConfig, ...] = ()

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
    return AppConfig(targets=targets)


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
        security_mode=str(d.get("security_mode", "None")),
        security_policy=str(d.get("security_policy", "None")),
        username=str(d.get("username", "")),
        rack=int(d.get("rack", 0) or 0),
        # slot may legitimately be 0 (CompactLogix / many ControlLogix), so do
        # NOT collapse a 0 to the default with ``or``.
        slot=int(d["slot"]) if d.get("slot") not in (None, "") else 1,
        plctype=str(d.get("plctype", "Q") or "Q"),
        agent_url=str(d.get("agent_url", "")),
        topic=str(d.get("topic", "")),
        use_tls=use_tls,
        # EtherCAT: NIC interface name (accept 'interface' as an alias).
        nic=str(d.get("nic", "") or d.get("interface", "")),
        expected_slaves=int(d.get("expected_slaves", 0) or 0),
        tags=_parse_tags(d.get("tags", [])),
    )
