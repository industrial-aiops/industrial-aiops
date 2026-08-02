"""A PROFINET-DCP station on a real wire — the responder half of the live test.

`pnio-dcp` speaks DCP over a **layer-2 raw socket**: no IP, no TCP, an Ethernet
frame with ether-type 0x8892 addressed to the PROFINET multicast MAC. There is no
software PROFINET device to test against, which is why this connector had been
mock-only — but the missing half is a *responder*, not a device: DCP Identify /
Get / Set are request-response over Ethernet, and a raw socket on the other end of
a veth pair can answer them.

This module is that responder, written from the DCP block layout (IEC 61158-6-10 /
PROFINET DCP): Ethernet header, then

    FrameID(2) ServiceID(1) ServiceType(1) XID(4) ResponseDelay(2) DataLength(2)

followed by DCP blocks

    Option(1) Suboption(1) BlockLength(2) [BlockInfo(2)] Value(BlockLength-2)

each padded to an even length (the pad is **not** counted in BlockLength). The
Set *response* block is the exception with no BlockInfo — its three value bytes
are the echoed option, the echoed suboption and the block error.

What this buys: `pnio-dcp` — a third-party implementation nobody here wrote — is
what parses these frames. That makes the live test **rung 2b** in
`docs/VERIFICATION-RECORD.md`: a real wire, judged by someone else's client, with
the device side ours. It is not rung 3 and never will be; a real ERTEC/Siemens
station is the only thing that gets there.
"""

from __future__ import annotations

import socket
import struct
import threading

ETHER_TYPE = 0x8892
FRAME_ID_IDENTIFY_RESPONSE = 0xFEFF
FRAME_ID_GET_SET = 0xFEFD

SERVICE_GET = 3
SERVICE_SET = 4
SERVICE_IDENTIFY = 5
TYPE_REQUEST = 0
TYPE_RESPONSE_SUCCESS = 1

OPT_IP = 1
SUB_IP_PARAMETER = 2
OPT_DEVICE = 2
SUB_DEVICE_FAMILY = 1
SUB_NAME_OF_STATION = 2
SUB_DEVICE_ID = 3
SUB_DEVICE_ROLE = 4
OPT_CONTROL = 5
SUB_CONTROL_RESPONSE = 4
OPT_ALL = 0xFF

# DCP set block errors (spec): 0 = ok, 1 = option unsupported.
ERR_OK = 0
ERR_OPTION_UNSUPPORTED = 1

_DCP_HEADER = ">HBBIHH"
_DCP_HEADER_LEN = struct.calcsize(_DCP_HEADER)
_ETH_HEADER_LEN = 14
_RECV_TIMEOUT_S = 0.5


def _mac_bytes(mac: str) -> bytes:
    return bytes(int(part, 16) for part in mac.split(":"))


def _mac_string(raw: bytes) -> str:
    return ":".join(f"{byte:02x}" for byte in raw)


def _ip_bytes(dotted: str) -> bytes:
    return bytes(int(part) for part in dotted.split("."))


def _ip_string(raw: bytes) -> str:
    return ".".join(str(byte) for byte in raw)


def _block(opt: int, subopt: int, value: bytes, block_info: bytes = b"\x00\x00") -> bytes:
    """One DCP block: BlockLength counts BlockInfo + value, padding is outside it."""
    body = block_info + value
    frame = struct.pack(">BBH", opt, subopt, len(body)) + body
    return frame + (b"\x00" if len(body) % 2 else b"")


class DCPStation:
    """A single PROFINET station answering DCP on one interface.

    Runs in a background thread on an ``AF_PACKET`` socket. Everything it reports
    is held here so a test can assert that what the connector read is what this
    station holds — and, after a DCP Set, that it changed.
    """

    def __init__(
        self,
        interface: str,
        *,
        name_of_station: str = "iaiops-virt-plc",
        ip: str = "10.77.0.20",
        netmask: str = "255.255.255.0",
        gateway: str = "10.77.0.1",
        family: str = "IAIOPS-VIRTUAL",
        vendor_id: int = 0x002A,
        device_id: int = 0x0301,
        device_role: int = 0x01,  # IO device
    ) -> None:
        self.interface = interface
        self.name_of_station = name_of_station
        self.ip = ip
        self.netmask = netmask
        self.gateway = gateway
        self.family = family
        self.vendor_id = vendor_id
        self.device_id = device_id
        self.device_role = device_role
        self.requests: list[tuple[int, int]] = []  # (service_id, service_type) seen

        self._socket = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(ETHER_TYPE))
        self._socket.settimeout(_RECV_TIMEOUT_S)
        self._socket.bind((interface, 0))
        self.mac = _mac_string(self._socket.getsockname()[4][:6])
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve, name=f"dcp-station-{interface}")
        self._thread.daemon = True

    # ─── lifecycle ──────────────────────────────────────────────────────────

    def start(self) -> DCPStation:
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=5)
        self._socket.close()

    def __enter__(self) -> DCPStation:
        return self.start()

    def __exit__(self, *_exc: object) -> None:
        self.stop()

    # ─── wire loop ──────────────────────────────────────────────────────────

    def _serve(self) -> None:
        while not self._stop.is_set():
            try:
                frame = self._socket.recv(0xFFFF)
            except (TimeoutError, socket.timeout):  # noqa: UP041 — 3.11 compatibility
                continue
            except OSError:  # socket closed under us during teardown
                return
            try:
                self._handle(frame)
            except (struct.error, ValueError, IndexError):
                # A malformed frame is the counterparty's problem, not a reason to
                # take the station down mid-test.
                continue

    def _handle(self, frame: bytes) -> None:
        if len(frame) < _ETH_HEADER_LEN + _DCP_HEADER_LEN:
            return
        source = _mac_string(frame[6:12])
        if source == self.mac:
            return  # our own transmission, looped back by AF_PACKET
        (ether_type,) = struct.unpack(">H", frame[12:14])
        if ether_type != ETHER_TYPE:
            return

        dcp = frame[_ETH_HEADER_LEN:]
        _frame_id, service_id, service_type, xid, _delay, length = struct.unpack(
            _DCP_HEADER, dcp[:_DCP_HEADER_LEN]
        )
        if service_type != TYPE_REQUEST:
            return
        self.requests.append((service_id, service_type))
        blocks = dcp[_DCP_HEADER_LEN : _DCP_HEADER_LEN + length]

        if service_id == SERVICE_IDENTIFY:
            self._respond(
                source, xid, FRAME_ID_IDENTIFY_RESPONSE, SERVICE_IDENTIFY, self._identity()
            )
        elif service_id == SERVICE_GET:
            self._respond(source, xid, FRAME_ID_GET_SET, SERVICE_GET, self._get(blocks))
        elif service_id == SERVICE_SET:
            self._respond(source, xid, FRAME_ID_GET_SET, SERVICE_SET, self._set(blocks))

    def _respond(
        self, destination: str, xid: int, frame_id: int, service_id: int, blocks: bytes
    ) -> None:
        header = struct.pack(
            _DCP_HEADER, frame_id, service_id, TYPE_RESPONSE_SUCCESS, xid, 0, len(blocks)
        )
        frame = (
            (_mac_bytes(destination) + _mac_bytes(self.mac) + struct.pack(">H", ETHER_TYPE))
            + header
            + blocks
        )
        # Ethernet's 60-byte minimum: the kernel pads on transmit, but a short
        # frame here would be an easy way to make a real switch drop the answer.
        self._socket.send(frame.ljust(60, b"\x00"))

    # ─── DCP services ───────────────────────────────────────────────────────

    def _identity(self) -> bytes:
        """The Identify-Ok blocks a station returns for IdentifyAll (option ALL)."""
        return (
            _block(OPT_DEVICE, SUB_DEVICE_FAMILY, self.family.encode())
            + _block(OPT_DEVICE, SUB_NAME_OF_STATION, self.name_of_station.encode())
            + _block(OPT_DEVICE, SUB_DEVICE_ID, struct.pack(">HH", self.vendor_id, self.device_id))
            + _block(OPT_DEVICE, SUB_DEVICE_ROLE, struct.pack(">BB", self.device_role, 0))
            + self._ip_block()
        )

    def _ip_block(self) -> bytes:
        return _block(
            OPT_IP,
            SUB_IP_PARAMETER,
            _ip_bytes(self.ip) + _ip_bytes(self.netmask) + _ip_bytes(self.gateway),
        )

    def _get(self, blocks: bytes) -> bytes:
        """Answer a unicast DCP Get — the request block is just option+suboption."""
        opt, subopt = blocks[0], blocks[1]
        if (opt, subopt) == (OPT_DEVICE, SUB_NAME_OF_STATION):
            return _block(OPT_DEVICE, SUB_NAME_OF_STATION, self.name_of_station.encode())
        if (opt, subopt) == (OPT_IP, SUB_IP_PARAMETER):
            return self._ip_block()
        if (opt, subopt) == (OPT_ALL, OPT_ALL):
            return self._identity()
        return _block(OPT_DEVICE, SUB_DEVICE_FAMILY, self.family.encode())

    def _set(self, blocks: bytes) -> bytes:
        """Apply a DCP Set and answer with a Control/Response block.

        The value is preceded by a 2-byte BlockQualifier (permanent/temporary),
        which this station accepts either way — a device that stores only
        temporarily is still a device that changed.
        """
        opt, subopt, length = struct.unpack(">BBH", blocks[:4])
        value = blocks[4 : 4 + length]
        error = ERR_OK
        if (opt, subopt) == (OPT_DEVICE, SUB_NAME_OF_STATION):
            self.name_of_station = value[2:].rstrip(b"\x00").decode()
        elif (opt, subopt) == (OPT_IP, SUB_IP_PARAMETER):
            self.ip = _ip_string(value[2:6])
            self.netmask = _ip_string(value[6:10])
            self.gateway = _ip_string(value[10:14])
        else:
            error = ERR_OPTION_UNSUPPORTED
        return _block(
            OPT_CONTROL, SUB_CONTROL_RESPONSE, bytes([opt, subopt, error]), block_info=b""
        )


__all__ = ["DCPStation"]
