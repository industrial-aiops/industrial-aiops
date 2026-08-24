"""A Modbus TCP line to demonstrate against — including the parts that go wrong.

Not a mock. A real pymodbus TCP server, so the demo drives the same code path a
plant would: `iaiops collect` opens a real socket, issues real FC03 reads and
decodes real responses.

Two processes, on purpose:

* **the server** (this file, ``serve``) holds the registers and answers requests
* **the driver** (``drive``) changes the run-state register over Modbus, the way
  a PLC program changes its own status word

Splitting them means an outage can be simulated by **killing the server
process** — a genuine disconnection with a genuine refused connection, rather
than a flag that makes the collector pretend. A demo that fakes the failure
proves nothing about how the tool handles it, and how it handles it is the whole
claim: blind time must not be reported as downtime.

Registers (holding):
  0  — run state: 2 = running, 0 = stopped, 1 = idle, 3 = fault
  10 — production counter, advancing while running
  11 — GOOD counter, advancing slightly slower: about one part in REJECT_EVERY is
       scrapped. A line with no rejects at all would let the demo report a
       perfect Quality factor, which is the one number a buyer will not believe
       and the one this tool exists not to invent.
"""

from __future__ import annotations

import argparse
import socket
import time
import warnings

warnings.filterwarnings("ignore")

RUN_STATE_ADDR = 0
COUNTER_ADDR = 10
GOOD_COUNTER_ADDR = 11
STOPPED, IDLE, RUNNING, FAULT = 0, 1, 2, 3

#: One part in this many is scrapped, so Quality is a real measurement rather
#: than a constant 100%.
REJECT_EVERY = 25


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def serve(port: int, bind: str = "127.0.0.1") -> None:
    """Answer Modbus TCP until killed. Killing this IS the outage.

    Binds to LOOPBACK by default. A demo should not put an unauthenticated
    Modbus server on a network where something might take it for a real device
    — Modbus has no authentication, and a write reaches the registers. Exposing
    it is an explicit choice (``--bind 0.0.0.0``), made only on a lab network.
    """
    from pymodbus.datastore import (
        ModbusDeviceContext,
        ModbusSequentialDataBlock,
        ModbusServerContext,
    )
    from pymodbus.server import StartTcpServer

    # 1-based store: base 1 seeds protocol address 0.
    context = ModbusServerContext(
        devices=ModbusDeviceContext(hr=ModbusSequentialDataBlock(1, [0] * 64)),
        single=True,
    )
    StartTcpServer(context=context, address=(bind, port))


def script(total_s: float) -> list[tuple[float, int, str]]:
    """``(start_second, state, label)`` — a compressed shift.

    The SHAPE is the point, not the durations: a real assessment runs for days,
    this runs for a minute and contains the same three things the measurement
    has to get right — several minor stoppages, one long one, and (added by the
    runner) a real disconnection.
    """
    u = total_s / 100.0
    return [
        (0 * u, RUNNING, "running"),
        (16 * u, STOPPED, "minor stop"),
        (19 * u, RUNNING, "running"),
        (34 * u, IDLE, "minor stop — IDLE, which is not production"),
        (37 * u, RUNNING, "running"),
        (58 * u, FAULT, "LONG stop — fault"),
        (72 * u, RUNNING, "running"),
        (88 * u, STOPPED, "minor stop"),
        (91 * u, RUNNING, "running"),
    ]


def drive(
    port: int,
    duration_s: float,
    host: str = "127.0.0.1",
    counter_start: int = 0,
) -> None:
    """Change the run-state register over Modbus, as a PLC program would.

    Reconnects silently: the server is expected to disappear part-way through,
    and the driver failing at that moment would make the line look stopped when
    it is only unobserved — the exact confusion this demo exists to disprove.
    """
    from pymodbus.client import ModbusTcpClient

    steps = script(duration_s)
    started = time.monotonic()
    counter = int(counter_start)
    good = int(counter_start)
    index = 0
    last = ""
    client = ModbusTcpClient(host, port=port, timeout=1)
    client.connect()

    while True:
        elapsed = time.monotonic() - started
        if elapsed >= duration_s:
            break
        while index + 1 < len(steps) and steps[index + 1][0] <= elapsed:
            index += 1
        _, state, label = steps[index]
        if label != last:
            print(f"  [line] t={elapsed:5.1f}s  {label}", flush=True)
            last = label
        if state == RUNNING:
            counter += 1
            if counter % REJECT_EVERY:
                good += 1
        try:
            if not client.connected:
                client.connect()
            client.write_register(address=RUN_STATE_ADDR, value=state, device_id=1)
            client.write_register(address=COUNTER_ADDR, value=counter % 65535, device_id=1)
            client.write_register(address=GOOD_COUNTER_ADDR, value=good % 65535, device_id=1)
        except Exception:  # noqa: BLE001 — the server is meant to vanish mid-run
            pass
        time.sleep(0.1)
    client.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("mode", choices=["serve", "drive"])
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--duration", type=float, default=90.0)
    ap.add_argument(
        "--bind",
        default="127.0.0.1",
        help="Server bind address. Loopback by default — an unauthenticated "
        "Modbus server does not belong on a shared network.",
    )
    ap.add_argument("--host", default="127.0.0.1", help="Where the driver writes.")
    ap.add_argument(
        "--counter-start",
        type=int,
        default=0,
        help="Initial production count. Start near 65535 to exercise a real rollover — "
        "the case that turns max-minus-min into 65,000 phantom parts.",
    )
    args = ap.parse_args()
    if args.mode == "serve":
        serve(args.port, args.bind)
    else:
        drive(args.port, args.duration, args.host, args.counter_start)
