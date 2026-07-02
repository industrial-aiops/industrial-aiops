"""Connection management for OT endpoints (vendor-neutral, multi-protocol).

No protocol holds a long-lived persistent session here: a client is opened,
used, and closed per call. ``opcua_session`` / ``modbus_session`` / ``s7_session``
/ ``mc_session`` / ``mqtt_session`` are context managers that build the right
client from a :class:`TargetConfig`, connect, yield the live client, and always
disconnect. (MTConnect is stateless HTTP — its ops fetch directly.) Nothing
risky is cached.

All client failures are translated centrally into a teaching ``OTConnectionError``
— an agent should see "could not connect to <endpoint>" rather than a raw
driver traceback. The client *factories* are module-level functions so tests can
monkeypatch them (inject a mock client) without a live PLC.

READ-FIRST: reads are non-destructive. The few write/command tools are gated by
the governance harness (high risk_tier, dry-run + double-confirm, undo capture).
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from iaiops.core.runtime.config import (
    DEFAULT_SECSGEM_PORT,
    AppConfig,
    TargetConfig,
    load_config,
)


class OTConnectionError(Exception):
    """An OT endpoint call failed; carries a teaching message + optional host."""

    def __init__(self, message: str, *, endpoint: str = "", protocol: str = "") -> None:
        self.endpoint = endpoint
        self.protocol = protocol
        super().__init__(message)


# ─── OPC-UA ──────────────────────────────────────────────────────────────────


def _build_opcua_client(target: TargetConfig) -> Any:
    """Construct (but do not connect) an asyncua sync Client for ``target``.

    Separated out so tests can monkeypatch this with a fake client factory.
    """
    try:
        from asyncua.sync import Client
    except ImportError as exc:  # pragma: no cover — exercised only without asyncua
        raise OTConnectionError(
            "The 'asyncua' package is not installed. Install the OPC-UA "
            "connector: 'pip install iaiops[opcua]'."
        ) from exc

    if not target.endpoint_url:
        raise OTConnectionError(
            f"OPC-UA endpoint '{target.name}' has no endpoint_url. Add "
            f"'endpoint_url: opc.tcp://host:4840' to its config entry.",
            endpoint=target.name,
            protocol="opcua",
        )
    client = Client(target.endpoint_url)
    username = target.username
    password = target.password()
    if username:
        client.set_user(username)
    if password:
        client.set_password(password)
    # Mutual-TLS / application-certificate security. When a client cert + key are
    # configured, apply asyncua's security string
    # "Policy,Mode,cert,key[,server_cert]". No cert configured → anonymous /
    # username-password path is UNCHANGED (back-compat).
    if target.client_cert and target.client_key:
        policy = (
            target.security_policy
            if target.security_policy and target.security_policy != "None"
            else "Basic256Sha256"
        )
        mode = (
            target.security_mode
            if target.security_mode and target.security_mode != "None"
            else "SignAndEncrypt"
        )
        sec = f"{policy},{mode},{target.client_cert},{target.client_key}"
        if target.server_cert:
            sec += f",{target.server_cert}"
        client.set_security_string(sec)
    return client


@contextmanager
def opcua_session(target: TargetConfig) -> Iterator[Any]:
    """Connect to an OPC-UA endpoint, yield the sync client, always disconnect."""
    if target.protocol != "opcua":
        raise OTConnectionError(
            f"Endpoint '{target.name}' is protocol '{target.protocol}', not opcua.",
            endpoint=target.name,
            protocol=target.protocol,
        )
    client = _build_opcua_client(target)
    try:
        client.connect()
    except Exception as exc:  # noqa: BLE001 — translate any connect failure
        raise _translate_opcua(exc, target) from exc
    try:
        yield client
    except OTConnectionError:
        raise
    except Exception as exc:  # noqa: BLE001 — translate any in-session failure
        raise _translate_opcua(exc, target) from exc
    finally:
        try:
            client.disconnect()
        except Exception:  # noqa: BLE001 — disconnect must not mask the real error
            pass


def _translate_opcua(exc: Exception, target: TargetConfig) -> OTConnectionError:
    """Map an asyncua exception to a teaching ``OTConnectionError``."""
    name = type(exc).__name__
    detail = str(exc).strip()[:200]
    endpoint = target.endpoint_url or target.name
    if "BadUserAccessDenied" in name or "BadIdentityToken" in detail:
        return OTConnectionError(
            f"OPC-UA authentication failed for '{target.name}' ({endpoint}). Check "
            f"the username and the stored password (see 'iaiops doctor'). {detail}",
            endpoint=endpoint,
            protocol="opcua",
        )
    if isinstance(exc, (ConnectionError, OSError, TimeoutError)) or "Timeout" in name:
        return OTConnectionError(
            f"Could not reach OPC-UA endpoint '{target.name}' ({endpoint}). Check the "
            f"endpoint_url, that the server is running, and network/firewall. Point at "
            f"a local simulator to test. {detail}",
            endpoint=endpoint,
            protocol="opcua",
        )
    return OTConnectionError(
        f"OPC-UA operation on '{target.name}' ({endpoint}) failed: {detail}",
        endpoint=endpoint,
        protocol="opcua",
    )


# ─── Modbus-TCP ──────────────────────────────────────────────────────────────


def _is_modbus_rtu(target: TargetConfig) -> bool:
    """True when a Modbus endpoint uses the serial (RTU) transport."""
    return target.transport == "rtu" or bool(target.serial_port)


def _modbus_endpoint_str(target: TargetConfig) -> str:
    """Human-readable endpoint locator for a Modbus target (serial or TCP)."""
    if _is_modbus_rtu(target):
        return f"{target.serial_port or '?'}@{target.baudrate}"
    return f"{target.host}:{target.port or 502}"


def _build_modbus_client(target: TargetConfig) -> Any:
    """Construct (but do not connect) a pymodbus client for ``target``.

    Builds a ``ModbusSerialClient`` when the endpoint uses the RTU (serial)
    transport, otherwise a ``ModbusTcpClient``. The same read ops (holding /
    input / coils / discrete) work over either. Separated out so tests can
    monkeypatch this with a mock client — and so the serial client construction
    can be verified without live hardware.
    """
    if _is_modbus_rtu(target):
        return _build_modbus_serial_client(target)

    try:
        from pymodbus.client import ModbusTcpClient
    except ImportError as exc:  # pragma: no cover — exercised only without pymodbus
        raise OTConnectionError(
            "The 'pymodbus' package is not installed. Install the Modbus "
            "connector: 'pip install iaiops[modbus]'."
        ) from exc

    if not target.host:
        raise OTConnectionError(
            f"Modbus endpoint '{target.name}' has no host. Add 'host: <ip>' to its "
            f"config entry (or set 'transport: rtu' + 'serial_port:' for serial).",
            endpoint=target.name,
            protocol="modbus",
        )
    return ModbusTcpClient(target.host, port=target.port or 502)


def _build_modbus_serial_client(target: TargetConfig) -> Any:
    """Construct (but do not connect) a pymodbus ModbusSerialClient (Modbus-RTU).

    ``ModbusSerialClient`` defaults to the RTU framer; we pass the serial line
    params (baudrate / parity / stopbits / bytesize) from the endpoint config.
    The live serial round-trip needs real hardware (待核实 — not CI-verifiable);
    this construction is unit-tested by monkeypatching the pymodbus client.
    """
    try:
        from pymodbus.client import ModbusSerialClient
    except ImportError as exc:  # pragma: no cover — exercised only without pymodbus
        raise OTConnectionError(
            "The 'pymodbus' package is not installed. Install the Modbus "
            "connector: 'pip install iaiops[modbus]' (serial needs pyserial too).",
            endpoint=target.name,
            protocol="modbus",
        ) from exc

    if not target.serial_port:
        raise OTConnectionError(
            f"Modbus-RTU endpoint '{target.name}' has no serial_port. Add "
            f"'serial_port: /dev/ttyUSB0' (or a COM port) to its config entry.",
            endpoint=target.name,
            protocol="modbus",
        )
    return ModbusSerialClient(
        target.serial_port,
        baudrate=target.baudrate or 19200,
        parity=(target.parity or "N")[:1],
        stopbits=target.stopbits or 1,
        bytesize=target.bytesize or 8,
    )


@contextmanager
def modbus_session(target: TargetConfig) -> Iterator[Any]:
    """Connect to a Modbus-TCP endpoint, yield the client, always close it."""
    if target.protocol != "modbus":
        raise OTConnectionError(
            f"Endpoint '{target.name}' is protocol '{target.protocol}', not modbus.",
            endpoint=target.name,
            protocol=target.protocol,
        )
    client = _build_modbus_client(target)
    try:
        connected = client.connect()
    except Exception as exc:  # noqa: BLE001 — translate any connect failure
        raise _translate_modbus(exc, target) from exc
    if connected is False:
        where = _modbus_endpoint_str(target)
        if _is_modbus_rtu(target):
            detail = (
                f"Could not open Modbus-RTU serial line '{target.name}' ({where}). "
                f"Check the serial_port, baudrate/parity/stopbits, cabling and that no "
                f"other process holds the port. Live serial needs real hardware."
            )
        else:
            detail = (
                f"Could not connect to Modbus endpoint '{target.name}' ({where}). Check "
                f"the host/port and that the PLC's Modbus-TCP server is enabled. Point "
                f"at a local simulator to test."
            )
        raise OTConnectionError(detail, endpoint=where, protocol="modbus")
    try:
        yield client
    except OTConnectionError:
        raise
    except Exception as exc:  # noqa: BLE001 — translate any in-session failure
        raise _translate_modbus(exc, target) from exc
    finally:
        try:
            client.close()
        except Exception:  # noqa: BLE001 — close must not mask the real error
            pass


def _translate_modbus(exc: Exception, target: TargetConfig) -> OTConnectionError:
    """Map a pymodbus exception to a teaching ``OTConnectionError``."""
    detail = str(exc).strip()[:200]
    endpoint = _modbus_endpoint_str(target)
    return OTConnectionError(
        f"Modbus operation on '{target.name}' ({endpoint}) failed: {detail}",
        endpoint=endpoint,
        protocol="modbus",
    )


# ─── S7comm (Siemens / 仿西门子 国产 PLC, ISO-on-TCP via pyS7) ────────────────


def _build_s7_client(target: TargetConfig) -> Any:
    """Construct (but do not connect) a pyS7 S7Client for ``target``.

    Module-level so tests can monkeypatch it with a fake client. pyS7 is pure
    Python (no native libsnap7), so the venv installs cleanly everywhere.
    """
    try:
        from pyS7 import S7Client
    except ImportError as exc:  # pragma: no cover — exercised only without pyS7
        raise OTConnectionError(
            "The 'pyS7' package is not installed. Install the S7comm "
            "connector: 'pip install iaiops[s7]'."
        ) from exc

    if not target.host:
        raise OTConnectionError(
            f"S7 endpoint '{target.name}' has no host. Add 'host: <ip>' to its "
            f"config entry (rack/slot default 0/1 for S7-1200/1500).",
            endpoint=target.name,
            protocol="s7",
        )
    return S7Client(
        target.host, rack=target.rack, slot=target.slot, port=target.port or 102
    )


@contextmanager
def s7_session(target: TargetConfig) -> Iterator[Any]:
    """Connect to an S7 PLC, yield the pyS7 client, always disconnect."""
    if target.protocol != "s7":
        raise OTConnectionError(
            f"Endpoint '{target.name}' is protocol '{target.protocol}', not s7.",
            endpoint=target.name,
            protocol=target.protocol,
        )
    client = _build_s7_client(target)
    try:
        client.connect()
    except Exception as exc:  # noqa: BLE001 — translate any connect failure
        raise _translate_s7(exc, target) from exc
    try:
        yield client
    except OTConnectionError:
        raise
    except Exception as exc:  # noqa: BLE001 — translate any in-session failure
        raise _translate_s7(exc, target) from exc
    finally:
        try:
            client.disconnect()
        except Exception:  # noqa: BLE001 — disconnect must not mask the real error
            pass


def _translate_s7(exc: Exception, target: TargetConfig) -> OTConnectionError:
    """Map a pyS7 exception to a teaching ``OTConnectionError``."""
    detail = str(exc).strip()[:200]
    endpoint = f"{target.host}:{target.port or 102} rack={target.rack} slot={target.slot}"
    return OTConnectionError(
        f"S7 operation on '{target.name}' ({endpoint}) failed: {detail}. Check the "
        f"host, rack/slot (0/1 for S7-1200/1500, 0/2 for many S7-300/400), and that "
        f"PUT/GET access is enabled on the CPU. Point at a local S7 simulator to test.",
        endpoint=endpoint,
        protocol="s7",
    )


# ─── Mitsubishi MC (Q/L/iQ-R, 3E binary via pymcprotocol) ─────────────────────


def _build_mc_client(target: TargetConfig) -> Any:
    """Construct (but do not connect) a pymcprotocol Type3E client for ``target``.

    Module-level so tests can monkeypatch it. pymcprotocol is pure Python.
    """
    try:
        import pymcprotocol
    except ImportError as exc:  # pragma: no cover — exercised only without the lib
        raise OTConnectionError(
            "The 'pymcprotocol' package is not installed. Install the "
            "Mitsubishi MC connector: 'pip install iaiops[mc]'."
        ) from exc

    if not target.host:
        raise OTConnectionError(
            f"MC endpoint '{target.name}' has no host. Add 'host: <ip>' to its "
            f"config entry (plctype Q|L|QnA|iQ-R|iQ-L).",
            endpoint=target.name,
            protocol="mc",
        )
    return pymcprotocol.Type3E(plctype=target.plctype or "Q")


@contextmanager
def mc_session(target: TargetConfig) -> Iterator[Any]:
    """Connect to a Mitsubishi PLC over MC 3E, yield the client, always close it."""
    if target.protocol != "mc":
        raise OTConnectionError(
            f"Endpoint '{target.name}' is protocol '{target.protocol}', not mc.",
            endpoint=target.name,
            protocol=target.protocol,
        )
    client = _build_mc_client(target)
    try:
        client.connect(target.host, target.port or 5007)
    except Exception as exc:  # noqa: BLE001 — translate any connect failure
        raise _translate_mc(exc, target) from exc
    try:
        yield client
    except OTConnectionError:
        raise
    except Exception as exc:  # noqa: BLE001 — translate any in-session failure
        raise _translate_mc(exc, target) from exc
    finally:
        try:
            client.close()
        except Exception:  # noqa: BLE001 — close must not mask the real error
            pass


def _translate_mc(exc: Exception, target: TargetConfig) -> OTConnectionError:
    """Map a pymcprotocol exception to a teaching ``OTConnectionError``."""
    detail = str(exc).strip()[:200]
    endpoint = f"{target.host}:{target.port or 5007} ({target.plctype})"
    return OTConnectionError(
        f"MC operation on '{target.name}' ({endpoint}) failed: {detail}. Check the "
        f"host/port, the MC 3E binary 'SLMP/MC' server is open on the Ethernet "
        f"module, and the plctype. Point at a GX Simulator / MC sim to test.",
        endpoint=endpoint,
        protocol="mc",
    )


# ─── MQTT (Sparkplug B / UNS via paho-mqtt) ──────────────────────────────────


def _build_mqtt_client(target: TargetConfig) -> Any:
    """Construct (but do not connect) a paho-mqtt Client for ``target``.

    Module-level so tests can monkeypatch it. paho-mqtt is pure Python. TLS and
    username/password (password from the encrypted store) are applied here.
    """
    try:
        import paho.mqtt.client as mqtt
    except ImportError as exc:  # pragma: no cover — exercised only without paho
        raise OTConnectionError(
            "The 'paho-mqtt' package is not installed. Install the "
            "MQTT/Sparkplug connector: 'pip install iaiops[sparkplug]'."
        ) from exc

    if not target.host:
        raise OTConnectionError(
            f"MQTT endpoint '{target.name}' has no broker host. Add 'host: <broker>' "
            f"(or 'broker:') to its config entry.",
            endpoint=target.name,
            protocol="mqtt",
        )
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    if target.username:
        client.username_pw_set(target.username, target.password() or None)
    # TLS: enabled by use_tls or by any cert path. A CA bundle verifies the broker;
    # a client cert+key give mutual auth. With none, tls_set() uses the system trust
    # store (server-auth only) — unchanged from before.
    if target.use_tls or target.ca_cert or target.client_cert:
        tls_kwargs: dict[str, str] = {}
        if target.ca_cert:
            tls_kwargs["ca_certs"] = target.ca_cert
        if target.client_cert and target.client_key:
            tls_kwargs["certfile"] = target.client_cert
            tls_kwargs["keyfile"] = target.client_key
        client.tls_set(**tls_kwargs)
    return client


@contextmanager
def mqtt_session(target: TargetConfig) -> Iterator[Any]:
    """Connect to an MQTT broker, yield the connected client, always disconnect.

    The caller is responsible for ``loop_start()``/``subscribe`` semantics; this
    just opens and tears down the connection cleanly.
    """
    if target.protocol != "mqtt":
        raise OTConnectionError(
            f"Endpoint '{target.name}' is protocol '{target.protocol}', not mqtt.",
            endpoint=target.name,
            protocol=target.protocol,
        )
    client = _build_mqtt_client(target)
    port = target.port or (8883 if target.use_tls else 1883)
    try:
        client.connect(target.host, port)
        client.loop_start()
    except Exception as exc:  # noqa: BLE001 — translate any connect failure
        raise _translate_mqtt(exc, target) from exc
    try:
        yield client
    except OTConnectionError:
        raise
    except Exception as exc:  # noqa: BLE001 — translate any in-session failure
        raise _translate_mqtt(exc, target) from exc
    finally:
        try:
            client.loop_stop()
            client.disconnect()
        except Exception:  # noqa: BLE001 — teardown must not mask the real error
            pass


def _translate_mqtt(exc: Exception, target: TargetConfig) -> OTConnectionError:
    """Map a paho-mqtt exception to a teaching ``OTConnectionError``."""
    detail = str(exc).strip()[:200]
    endpoint = f"{target.host}:{target.port or (8883 if target.use_tls else 1883)}"
    return OTConnectionError(
        f"MQTT operation on '{target.name}' ({endpoint}) failed: {detail}. Check the "
        f"broker host/port, TLS/credentials, and that the broker is reachable. Point "
        f"at a local mosquitto broker to test.",
        endpoint=endpoint,
        protocol="mqtt",
    )


# ─── EtherNet/IP (Rockwell / Allen-Bradley Logix, CIP via pycomm3) ────────────


def _build_eip_client(target: TargetConfig) -> Any:
    """Construct (but do not connect) a pycomm3 LogixDriver for ``target``.

    Module-level so tests can monkeypatch it with a fake driver. pycomm3 is pure
    Python (no native deps). The CIP path is ``host`` or ``host/slot`` (the slot
    is the controller's chassis slot — 0 for most CompactLogix, the CPU slot for
    a ControlLogix chassis).
    """
    try:
        from pycomm3 import LogixDriver
    except ImportError as exc:  # pragma: no cover — exercised only without pycomm3
        raise OTConnectionError(
            "The 'pycomm3' package is not installed. Install the EtherNet/IP "
            "connector: 'pip install iaiops[eip]'."
        ) from exc

    if not target.host:
        raise OTConnectionError(
            f"EtherNet/IP endpoint '{target.name}' has no host. Add 'host: <ip>' to "
            f"its config entry (and 'slot:' for a ControlLogix chassis CPU slot).",
            endpoint=target.name,
            protocol="ethernetip",
        )
    path = f"{target.host}/{target.slot}" if target.slot else target.host
    return LogixDriver(path)


@contextmanager
def eip_session(target: TargetConfig) -> Iterator[Any]:
    """Connect to a Logix controller over CIP, yield the driver, always close it."""
    if target.protocol not in ("ethernetip", "eip"):
        raise OTConnectionError(
            f"Endpoint '{target.name}' is protocol '{target.protocol}', not ethernetip.",
            endpoint=target.name,
            protocol=target.protocol,
        )
    client = _build_eip_client(target)
    try:
        client.open()
    except Exception as exc:  # noqa: BLE001 — translate any connect failure
        raise _translate_eip(exc, target) from exc
    try:
        yield client
    except OTConnectionError:
        raise
    except Exception as exc:  # noqa: BLE001 — translate any in-session failure
        raise _translate_eip(exc, target) from exc
    finally:
        try:
            client.close()
        except Exception:  # noqa: BLE001 — close must not mask the real error
            pass


def _translate_eip(exc: Exception, target: TargetConfig) -> OTConnectionError:
    """Map a pycomm3 exception to a teaching ``OTConnectionError``."""
    detail = str(exc).strip()[:200]
    endpoint = f"{target.host} slot={target.slot}"
    return OTConnectionError(
        f"EtherNet/IP operation on '{target.name}' ({endpoint}) failed: {detail}. "
        f"Check the host, the controller slot (0 for CompactLogix, the CPU slot for "
        f"ControlLogix), that EtherNet/IP (TCP 44818) is reachable, and that this is "
        f"a Logix controller (PLC-5/SLC PCCC is not supported). Point at a CIP/Logix "
        f"simulator to test.",
        endpoint=endpoint,
        protocol="ethernetip",
    )


# ─── EtherCAT (fieldbus master via pysoem / SOEM — OPTIONAL extra) ────────────


def _build_ethercat_master(target: TargetConfig) -> Any:
    """Construct (but do not open) a pysoem Master for ``target``.

    ``pysoem`` is an OPTIONAL dependency (``pip install iaiops[ethercat]``).
    It is imported LAZILY here so the package installs and imports cleanly
    WITHOUT it — every EtherCAT tool then degrades to a teaching error instead
    of crashing. EtherCAT is hard-real-time: it needs **Linux + root/CAP_NET_RAW
    + a dedicated NIC + real slave hardware**; there is NO software simulator and
    macOS is effectively unsupported. Module-level so tests monkeypatch it with a
    fake master (the only way to exercise this without a live bus).
    """
    try:
        import pysoem
    except ImportError as exc:  # pragma: no cover — exercised only without pysoem
        raise OTConnectionError(
            "The 'pysoem' package is not installed. EtherCAT is an OPTIONAL extra: "
            "'pip install iaiops[ethercat]'. It also requires Linux, root or "
            "CAP_NET_RAW, a dedicated NIC, and real EtherCAT slaves on the bus — "
            "there is NO software simulator and macOS is unsupported.",
            endpoint=target.name,
            protocol="ethercat",
        ) from exc

    nic = target.nic or target.host
    if not nic:
        raise OTConnectionError(
            f"EtherCAT endpoint '{target.name}' has no NIC. Add 'nic: <iface>' "
            f"(e.g. 'nic: eth1') — the dedicated interface cabled to the EtherCAT "
            f"bus — to its config entry.",
            endpoint=target.name,
            protocol="ethercat",
        )
    return pysoem.Master()


@contextmanager
def ethercat_master(target: TargetConfig, *, map_pdo: bool = False) -> Iterator[Any]:
    """Open the EtherCAT master on the NIC, config the bus, yield it, always close.

    Always runs ``open(nic)`` + ``config_init()`` (cheap bus enumeration). When
    ``map_pdo`` is True it also runs ``config_map()`` so the process-data image is
    addressable (needed for PDO reads / OP-state). Never raises a raw pysoem
    traceback — failures become a teaching ``OTConnectionError``.
    """
    if target.protocol != "ethercat":
        raise OTConnectionError(
            f"Endpoint '{target.name}' is protocol '{target.protocol}', not ethercat.",
            endpoint=target.name,
            protocol=target.protocol,
        )
    master = _build_ethercat_master(target)
    nic = target.nic or target.host
    try:
        master.open(nic)
    except Exception as exc:  # noqa: BLE001 — translate any open failure
        raise _translate_ethercat(exc, target) from exc
    try:
        # config_init returns the number of slaves found on the bus (0 = none).
        master.config_init(False)
        if map_pdo:
            master.config_map()
        yield master
    except OTConnectionError:
        raise
    except Exception as exc:  # noqa: BLE001 — translate any in-session failure
        raise _translate_ethercat(exc, target) from exc
    finally:
        try:
            master.close()
        except Exception:  # noqa: BLE001 — close must not mask the real error
            pass


def _translate_ethercat(exc: Exception, target: TargetConfig) -> OTConnectionError:
    """Map a pysoem / OS exception to a teaching ``OTConnectionError``."""
    detail = str(exc).strip()[:200]
    nic = target.nic or target.host or "?"
    lowered = detail.lower()
    if isinstance(exc, PermissionError) or "permitted" in lowered or "permission" in lowered:
        return OTConnectionError(
            f"EtherCAT master '{target.name}' (nic={nic}) lacks raw-socket permission. "
            f"Run as root or grant CAP_NET_RAW (e.g. 'sudo setcap cap_net_raw+ep "
            f"$(readlink -f $(which python))'). EtherCAT needs Linux + a dedicated "
            f"NIC + real slaves. {detail}",
            endpoint=nic,
            protocol="ethercat",
        )
    return OTConnectionError(
        f"EtherCAT master '{target.name}' (nic={nic}) failed: {detail}. Check the NIC "
        f"name (e.g. eth1), that you are root / have CAP_NET_RAW, the cabling, and "
        f"that real EtherCAT slaves are on the bus. There is NO software simulator "
        f"(macOS unsupported) — validate on Linux with hardware.",
        endpoint=nic,
        protocol="ethercat",
    )


# ─── SECS/GEM (semiconductor / display fab equipment, HSMS via secsgem) ───────


def _build_secsgem_host(target: TargetConfig) -> Any:
    """Construct (but do not enable) a secsgem GEM *host* handler for ``target``.

    We are the HOST connecting (HSMS ACTIVE) to the equipment's passive port.
    ``secsgem`` is an OPTIONAL extra (``pip install iaiops[secsgem]``). Module-level
    so tests can monkeypatch it with a fake handler.
    """
    try:
        from secsgem.gem import GemHostHandler
        from secsgem.hsms import DeviceType, HsmsConnectMode, HsmsSettings
    except ImportError as exc:  # pragma: no cover — exercised only without secsgem
        raise OTConnectionError(
            "The 'secsgem' package is not installed. Install the SECS/GEM "
            "connector: 'pip install iaiops[secsgem]'."
        ) from exc

    settings = HsmsSettings(
        address=target.host,
        port=target.port or DEFAULT_SECSGEM_PORT,
        connect_mode=HsmsConnectMode.ACTIVE,
        device_type=DeviceType.HOST,
        session_id=target.unit_id,
    )
    return GemHostHandler(settings)


@contextmanager
def secsgem_session(target: TargetConfig, *, timeout_s: float = 10.0) -> Iterator[Any]:
    """Enable a GEM host link, wait until communicating, yield the handler, disable."""
    if target.protocol != "secsgem":
        raise OTConnectionError(
            f"Endpoint '{target.name}' is protocol '{target.protocol}', not secsgem.",
            endpoint=target.name,
            protocol=target.protocol,
        )
    if not target.host:
        raise OTConnectionError(
            f"SECS/GEM endpoint '{target.name}' has no host. Add 'host: <ip>' and "
            f"optionally 'port: 5000' (HSMS default) to its config entry.",
            endpoint=target.name,
            protocol="secsgem",
        )
    handler = _build_secsgem_host(target)
    try:
        handler.enable()
    except Exception as exc:  # noqa: BLE001 — translate any enable/connect failure
        raise _translate_secsgem(exc, target) from exc
    try:
        if not handler.waitfor_communicating(timeout_s):
            raise OTConnectionError(
                f"SECS/GEM '{target.name}' did not reach the communicating state "
                f"within {timeout_s}s (equipment offline or not PASSIVE/listening).",
                endpoint=target.name,
                protocol="secsgem",
            )
        yield handler
    except OTConnectionError:
        raise
    except Exception as exc:  # noqa: BLE001 — translate any in-session failure
        raise _translate_secsgem(exc, target) from exc
    finally:
        try:
            handler.disable()
        except Exception:  # noqa: BLE001 — disable must not mask the real error
            pass


def _translate_secsgem(exc: Exception, target: TargetConfig) -> OTConnectionError:
    """Map a secsgem/HSMS exception to a teaching ``OTConnectionError``."""
    name = type(exc).__name__
    detail = str(exc).strip()[:200]
    where = f"{target.host}:{target.port or DEFAULT_SECSGEM_PORT}"
    if isinstance(exc, (ConnectionError, OSError, TimeoutError)) or "timeout" in name.lower():
        return OTConnectionError(
            f"Could not reach SECS/GEM equipment '{target.name}' ({where}). Check the "
            f"host/port (HSMS default 5000), that the equipment is online and configured "
            f"as PASSIVE/listening, and the session (device) id. {detail}",
            endpoint=where,
            protocol="secsgem",
        )
    return OTConnectionError(
        f"SECS/GEM operation on '{target.name}' ({where}) failed: {detail}",
        endpoint=where,
        protocol="secsgem",
    )


# ─── PROFINET (DCP discovery/identify via pnio-dcp — OPTIONAL extra, read-only) ─


def _build_profinet_dcp(target: TargetConfig) -> Any:
    """Construct a pnio-dcp ``DCP`` bound to the local interface for ``target``.

    ``pnio-dcp`` is an OPTIONAL dependency (``pip install iaiops[profinet]``),
    imported LAZILY so the package installs/imports without it. PROFINET-DCP is a
    layer-2 (raw Ethernet) discovery protocol: the ``DCP`` is bound to the LOCAL
    interface identified by its IP (``host``), and an IdentifyAll broadcast finds
    every PROFINET station on that segment. It needs raw-socket access
    (root / admin / CAP_NET_RAW). This is discovery + identify ONLY — no RT cyclic
    process data. Module-level so tests monkeypatch it with a fake DCP.
    """
    try:
        from pnio_dcp import DCP
    except ImportError as exc:  # pragma: no cover — exercised only without pnio-dcp
        raise OTConnectionError(
            "The 'pnio-dcp' package is not installed. PROFINET is an OPTIONAL extra: "
            "'pip install iaiops[profinet]'. It also needs layer-2 raw-socket access "
            "(root/admin/CAP_NET_RAW) on the NIC connected to the PROFINET subnet. "
            "Read-only DCP discovery/identify only — no RT cyclic data.",
            endpoint=target.name,
            protocol="profinet",
        ) from exc

    ip = target.host or target.nic
    if not ip:
        raise OTConnectionError(
            f"PROFINET endpoint '{target.name}' has no host. Add 'host: <local-ip>' "
            f"— the IP of THIS machine's interface on the PROFINET subnet (the DCP "
            f"broadcast goes out on it) — to its config entry.",
            endpoint=target.name,
            protocol="profinet",
        )
    return DCP(ip)


@contextmanager
def profinet_dcp(target: TargetConfig) -> Iterator[Any]:
    """Open a PROFINET-DCP handle on the local interface, yield it, always close.

    Read-only: callers do IdentifyAll / Identify / Get. Never raises a raw pnio-dcp
    traceback — failures become a teaching ``OTConnectionError``.
    """
    if target.protocol != "profinet":
        raise OTConnectionError(
            f"Endpoint '{target.name}' is protocol '{target.protocol}', not profinet.",
            endpoint=target.name,
            protocol=target.protocol,
        )
    # Build INSIDE the try: pnio_dcp.DCP(ip) binds an L2 raw socket in its
    # constructor, so the common no-root / no-CAP_NET_RAW PermissionError must be
    # routed through the teaching translator, not raised raw.
    dcp = None
    try:
        dcp = _build_profinet_dcp(target)
        yield dcp
    except OTConnectionError:
        raise
    except Exception as exc:  # noqa: BLE001 — translate any in-session failure
        raise _translate_profinet(exc, target) from exc
    finally:
        close = getattr(dcp, "close", None)
        if callable(close):
            try:
                close()
            except Exception:  # noqa: BLE001 — close must not mask the real error
                pass


def _translate_profinet(exc: Exception, target: TargetConfig) -> OTConnectionError:
    """Map a pnio-dcp / OS exception to a teaching ``OTConnectionError``."""
    detail = str(exc).strip()[:200]
    ip = target.host or target.nic or "?"
    lowered = detail.lower()
    if isinstance(exc, PermissionError) or "permitted" in lowered or "permission" in lowered:
        return OTConnectionError(
            f"PROFINET-DCP on '{target.name}' (local ip={ip}) lacks raw-socket "
            f"permission. Run as root/admin or grant CAP_NET_RAW. PROFINET-DCP is "
            f"layer-2 and needs the NIC on the PROFINET subnet. {detail}",
            endpoint=ip,
            protocol="profinet",
        )
    return OTConnectionError(
        f"PROFINET-DCP on '{target.name}' (local ip={ip}) failed: {detail}. Check the "
        f"host is THIS machine's IP on the PROFINET subnet, that you have raw-socket "
        f"access, and that stations are powered on the segment. Validate against a "
        f"PROFINET device or a DCP simulator.",
        endpoint=ip,
        protocol="profinet",
    )


# ─── Building edition: BACnet/IP (facility / HVAC) via BAC0 — OPTIONAL extra ───


def _build_bacnet_network(target: TargetConfig) -> Any:
    """Construct (and connect) a BAC0 network bound to the local interface.

    ``BAC0`` (over bacpypes3) is an OPTIONAL extra (``pip install iaiops[bacnet]``)
    imported LAZILY. Modern BAC0 (2024+) is async-first: ``BAC0.lite(ip=...)`` must
    be built inside a running event loop and ``who_is`` / ``read`` / ``readRange``
    are coroutines. So we construct BAC0 on a dedicated background loop and return
    a synchronous facade (:class:`~iaiops.core.runtime.bacnet_async.BacnetSyncNetwork`)
    that marshals every call onto that loop — the same bridge pattern asyncua's sync
    client uses. This keeps the broad pin (``BAC0>=2023.6,<2026``) and the sync ops
    unchanged: sync-era and async-first builds both work through the facade.

    ``lite(ip=...)`` binds THIS machine's BACnet/IP interface (``host``, optionally
    ``ip/mask``); remote devices are addressed per call. Module-level so tests
    monkeypatch it with a fake network object.
    """
    try:
        import BAC0
    except ImportError as exc:  # pragma: no cover — only without BAC0
        raise OTConnectionError(
            "The 'BAC0' package is not installed. BACnet is an OPTIONAL extra: "
            "'pip install iaiops[bacnet]'.",
            endpoint=target.name, protocol="bacnet",
        ) from exc
    if not target.host:
        raise OTConnectionError(
            f"BACnet endpoint '{target.name}' has no host. Add 'host: <local-ip>' "
            f"(THIS machine's BACnet/IP interface, optionally '<ip>/<mask>').",
            endpoint=target.name, protocol="bacnet",
        )
    from iaiops.core.runtime.bacnet_async import build_sync_network

    lite = getattr(BAC0, "lite", None) or BAC0.connect
    return build_sync_network(lite, target.host)


@contextmanager
def bacnet_session(target: TargetConfig) -> Iterator[Any]:
    """Bring up a BAC0 BACnet/IP network, yield it, always disconnect."""
    if target.protocol != "bacnet":
        raise OTConnectionError(
            f"Endpoint '{target.name}' is protocol '{target.protocol}', not bacnet.",
            endpoint=target.name, protocol=target.protocol,
        )
    # Build INSIDE the try: BAC0.lite(ip=...) brings up the stack and binds
    # UDP/47808 in the constructor, so a bind/permission failure must be
    # translated, not raised raw (consistent with the other session builders).
    net = None
    try:
        net = _build_bacnet_network(target)
        yield net
    except OTConnectionError:
        raise
    except Exception as exc:  # noqa: BLE001 — translate any in-session failure
        raise _translate_endpoint_error(exc, target, "bacnet", target.port or 47808) from exc
    finally:
        disconnect = getattr(net, "disconnect", None)
        if callable(disconnect):
            try:
                disconnect()
            except Exception:  # noqa: BLE001 — disconnect must not mask the real error
                pass


def _translate_endpoint_error(
    exc: Exception, target: TargetConfig, protocol: str, port: int
) -> OTConnectionError:
    """Map a preview/optional-protocol library/OS exception (BACnet) to a teaching error."""
    detail = str(exc).strip()[:200]
    where = f"{target.host}:{port}"
    return OTConnectionError(
        f"{protocol.upper()} operation on '{target.name}' ({where}) failed: {detail}. "
        f"Check host/port/addressing and that the device is reachable. Preview — "
        f"validate against live gear or a protocol simulator.",
        endpoint=where, protocol=protocol,
    )


# ─── manager ─────────────────────────────────────────────────────────────────


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
        """Return the right protocol session context manager for an endpoint.

        MTConnect is stateless HTTP and has no session (its ops fetch directly).
        """
        target = self.target(target_name)
        builders = {
            "modbus": modbus_session,
            "s7": s7_session,
            "mc": mc_session,
            "mqtt": mqtt_session,
            "ethernetip": eip_session,
            "eip": eip_session,
            "secsgem": secsgem_session,
        }
        builder = builders.get(target.protocol, opcua_session)
        return builder(target)

    def list_targets(self) -> list[str]:
        return [t.name for t in self._config.targets]
