"""Connection management for OT endpoints (vendor-neutral, multi-protocol).

No protocol holds a long-lived persistent session here: a client is opened,
used, and closed per call. ``opcua_session`` / ``modbus_session`` / etc. are
assembled from :func:`iaiops.core.runtime.session_factory.make_session`, which
enforces the shared lifecycle for every protocol: they build the right
client from a :class:`TargetConfig`, connect, yield the live client, and always
tear down, translating client failures into a teaching ``OTConnectionError``.
Each protocol's build/translate helpers live in its connector package
(``iaiops.connectors.<proto>.transport``) and are re-exported here; the client
*factories* stay late-bound (``lambda``) against THIS module's globals so tests
keep monkeypatching ``connection._build_<proto>_*`` without a live PLC.

READ-FIRST: reads are non-destructive. The few write/command tools are gated by
the governance harness (high risk_tier, dry-run + double-confirm, undo capture).
"""

from __future__ import annotations

from iaiops.connectors.bacnet import transport as _bacnet_tx
from iaiops.connectors.eip import transport as _eip_tx
from iaiops.connectors.ethercat import transport as _ethercat_tx
from iaiops.connectors.fins import transport as _fins_tx
from iaiops.connectors.mc import transport as _mc_tx
from iaiops.connectors.modbus import transport as _modbus_tx
from iaiops.connectors.opcua import transport as _opcua_tx
from iaiops.connectors.profinet import transport as _profinet_tx
from iaiops.connectors.s7 import transport as _s7_tx
from iaiops.connectors.secsgem import transport as _secsgem_tx
from iaiops.connectors.sparkplug import transport as _mqtt_tx
from iaiops.core.runtime.config import AppConfig, TargetConfig, load_config
from iaiops.core.runtime.session_factory import OTConnectionError, make_session

__all__ = [
    "ConnectionManager", "OTConnectionError", "bacnet_session", "eip_session",
    "ethercat_master", "fins_session", "make_session", "mc_session", "modbus_session",
    "mqtt_session", "opcua_session", "profinet_dcp", "s7_session",
    "secsgem_session",
]

# Back-compat re-exports: the documented monkeypatch points for tests
# (``monkeypatch.setattr(connection, "_build_*", …)``) and still imported by
# a few modules (e.g. opcua diagnostics).
_build_opcua_client = _opcua_tx._build_opcua_client
_translate_opcua = _opcua_tx._translate_opcua
_is_modbus_rtu = _modbus_tx._is_modbus_rtu
_modbus_endpoint_str = _modbus_tx._modbus_endpoint_str
_build_modbus_client = _modbus_tx._build_modbus_client
_build_modbus_serial_client = _modbus_tx._build_modbus_serial_client
_translate_modbus = _modbus_tx._translate_modbus
_build_s7_client = _s7_tx._build_s7_client
_translate_s7 = _s7_tx._translate_s7
_build_mc_client = _mc_tx._build_mc_client
_translate_mc = _mc_tx._translate_mc
_build_fins_client = _fins_tx._build_fins_client
_translate_fins = _fins_tx._translate_fins
_build_mqtt_client = _mqtt_tx._build_mqtt_client
_translate_mqtt = _mqtt_tx._translate_mqtt
_build_eip_client = _eip_tx._build_eip_client
_translate_eip = _eip_tx._translate_eip
_build_ethercat_master = _ethercat_tx._build_ethercat_master
_translate_ethercat = _ethercat_tx._translate_ethercat
_build_secsgem_host = _secsgem_tx._build_secsgem_host
_translate_secsgem = _secsgem_tx._translate_secsgem
_build_profinet_dcp = _profinet_tx._build_profinet_dcp
_translate_profinet = _profinet_tx._translate_profinet
_build_bacnet_network = _bacnet_tx._build_bacnet_network
_translate_endpoint_error = _bacnet_tx._translate_endpoint_error

# Session assembly. The ``build=lambda ...`` indirection resolves the factory
# through THIS module's globals at call time, keeping the patch points working.

opcua_session = make_session(
    protocol="opcua",
    build=lambda target: _build_opcua_client(target),
    connect=lambda client, target: client.connect(),
    close=lambda client: client.disconnect(),
    translate=_translate_opcua,
)

modbus_session = make_session(
    protocol="modbus",
    build=lambda target: _build_modbus_client(target),
    connect=_modbus_tx._connect_modbus,
    close=lambda client: client.close(),
    translate=_translate_modbus,
)

s7_session = make_session(
    protocol="s7",
    build=lambda target: _build_s7_client(target),
    connect=lambda client, target: client.connect(),
    close=lambda client: client.disconnect(),
    translate=_translate_s7,
)

mc_session = make_session(
    protocol="mc",
    build=lambda target: _build_mc_client(target),
    connect=_mc_tx._connect_mc,
    close=lambda client: client.close(),
    translate=_translate_mc,
)

fins_session = make_session(
    protocol="fins",
    build=lambda target: _build_fins_client(target),
    connect=_fins_tx._connect_fins,
    close=lambda client: client.close(),
    translate=_translate_fins,
)

mqtt_session = make_session(
    protocol="mqtt",
    build=lambda target: _build_mqtt_client(target),
    connect=_mqtt_tx._connect_mqtt,
    close=_mqtt_tx._close_mqtt,
    translate=_translate_mqtt,
)

eip_session = make_session(
    protocol="ethernetip",
    accept=("ethernetip", "eip"),
    build=lambda target: _build_eip_client(target),
    connect=lambda client, target: client.open(),
    close=lambda client: client.close(),
    translate=_translate_eip,
    name="eip_session",
)

ethercat_master = make_session(  # ethercat_master(target, map_pdo=True) maps PDOs too
    protocol="ethercat",
    build=lambda target: _build_ethercat_master(target),
    connect=_ethercat_tx._open_ethercat,
    prepare=_ethercat_tx._prepare_ethercat,
    close=lambda master: master.close(),
    translate=_translate_ethercat,
    name="ethercat_master",
)

# ``secsgem_session(target, timeout_s=10.0)`` waits for the communicating state.
secsgem_session = make_session(
    protocol="secsgem",
    validate=_secsgem_tx._require_secsgem_host,
    build=lambda target: _build_secsgem_host(target),
    connect=lambda handler, target: handler.enable(),
    prepare=_secsgem_tx._wait_communicating,
    close=lambda handler: handler.disable(),
    translate=_translate_secsgem,
)

# Built INSIDE the translated block: DCP(ip) binds an L2 raw socket in its
# constructor, so a no-CAP_NET_RAW PermissionError must teach, not raise raw.
profinet_dcp = make_session(
    protocol="profinet",
    build=lambda target: _build_profinet_dcp(target),
    build_in_session=True,
    close=_profinet_tx._close_profinet,
    translate=_translate_profinet,
    name="profinet_dcp",
)

# Built INSIDE the translated block: BAC0.lite(ip=...) binds UDP/47808 in its
# constructor, so a bind/permission failure is translated, not raised raw.
bacnet_session = make_session(
    protocol="bacnet",
    build=lambda target: _build_bacnet_network(target),
    build_in_session=True,
    close=_bacnet_tx._close_bacnet,
    translate=_bacnet_tx._translate_bacnet,
)


class ConnectionManager:
    """Resolves OT endpoint targets from an AppConfig."""

    def __init__(self, config: AppConfig) -> None:
        self._config = config

    @classmethod
    def from_config(cls, config: AppConfig | None = None) -> ConnectionManager:
        return cls(config or load_config())

    @property
    def config(self) -> AppConfig:
        return self._config

    def target(self, target_name: str | None = None) -> TargetConfig:
        """Return an endpoint by name, or the default (first) endpoint."""
        if target_name:
            return self._config.get_target(target_name)
        return self._config.default_target

    def session(self, target_name: str | None = None):
        """Return the protocol session for an endpoint (MTConnect: none, stateless HTTP)."""
        target = self.target(target_name)
        builders = {
            "modbus": modbus_session,
            "s7": s7_session,
            "mc": mc_session,
            "fins": fins_session,
            "mqtt": mqtt_session,
            "ethernetip": eip_session,
            "eip": eip_session,
            "secsgem": secsgem_session,
        }
        builder = builders.get(target.protocol, opcua_session)
        return builder(target)

    def list_targets(self) -> list[str]:
        return [t.name for t in self._config.targets]
