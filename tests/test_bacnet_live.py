"""Live BACnet/IP integration: a REAL virtual device vs. the connector ops.

Stands up an in-process virtual BACnet/IP device with ``bacpypes3`` (a
DeviceObject + NetworkPortObject + analog/binary Value objects bound to a real
UDP socket) and drives the *real* connector ops (``bacnet_discover`` /
``bacnet_read_property`` / ``bacnet_read_points``) against it through the actual
BAC0/bacpypes3 stack — no mocking. A genuine Who-Is discover + present-value read
round-trip is asserted.

BACnet/IP discovery is UDP broadcast; loopback does not carry it, so the device
and the connector must sit on two IPs of one real subnet. The test is therefore
gated on two env vars supplied by the Docker harness (see
``scripts``/``docs/PREVIEW-VERIFICATION.md``):

* ``IAIOPS_BACNET_CLIENT_IP`` — ``<ip>/<mask>`` the connector (BAC0) binds.
* ``IAIOPS_BACNET_DEVICE_IP`` — ``<ip>/<mask>`` the virtual device binds.

Both must be distinct addresses on one subnet. When unset (ordinary CI / a dev
laptop where BACnet broadcast is unavailable) the test SKIPS cleanly — it never
fabricates a pass. It is ``integration``-marked; it only turns green as a real
assertion when the broadcast round-trip actually succeeds.
"""

from __future__ import annotations

import asyncio
import os
import threading
from typing import Any

import pytest

# BACnet is an OPTIONAL extra — skip the whole module if the stack is absent.
pytest.importorskip("bacpypes3")
pytest.importorskip("BAC0")

from iaiops.connectors.bacnet import ops  # noqa: E402
from iaiops.core.runtime.config import TargetConfig  # noqa: E402
from iaiops.core.runtime.connection import OTConnectionError  # noqa: E402

DEVICE_ID = 599
AV_INSTANCE = 1
AV_VALUE = 21.5
BV_INSTANCE = 1
BACNET_PORT = 47808
_READY_TIMEOUT_S = 10.0

CLIENT_IP = os.environ.get("IAIOPS_BACNET_CLIENT_IP", "")
DEVICE_IP = os.environ.get("IAIOPS_BACNET_DEVICE_IP", "")

_requires_two_ips = pytest.mark.skipif(
    not (CLIENT_IP and DEVICE_IP),
    reason=(
        "live BACnet needs two IPs on one subnet (IAIOPS_BACNET_CLIENT_IP + "
        "IAIOPS_BACNET_DEVICE_IP); broadcast is unavailable otherwise"
    ),
)


def _device_bind_addr() -> str:
    """NetworkPortObject address for the device: ``<ip>/<mask>:<port>``."""
    return f"{DEVICE_IP}:{BACNET_PORT}"


class _VirtualDevice:
    """A real bacpypes3 BACnet/IP device running its asyncio loop in a thread."""

    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._app: Any = None
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._error = ""

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        if not self._ready.wait(_READY_TIMEOUT_S):
            raise RuntimeError(self._error or "virtual BACnet device did not start")
        if self._error:
            raise RuntimeError(self._error)

    def _run(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        try:
            self._app = loop.run_until_complete(self._build())
        except Exception as exc:  # noqa: BLE001 — surface bind/UDP failures
            self._error = f"{type(exc).__name__}: {exc}"
            self._ready.set()
            return
        self._ready.set()
        loop.run_forever()

    async def _build(self) -> Any:
        from bacpypes3.app import Application
        from bacpypes3.local.analog import AnalogValueObject
        from bacpypes3.local.binary import BinaryValueObject
        from bacpypes3.local.device import DeviceObject
        from bacpypes3.local.networkport import NetworkPortObject

        objects = [
            DeviceObject(
                objectIdentifier=("device", DEVICE_ID),
                objectName="VirtAHU",
                vendorIdentifier=999,
            ),
            NetworkPortObject(
                _device_bind_addr(),
                objectIdentifier=("network-port", 1),
                objectName="np1",
            ),
            AnalogValueObject(
                objectIdentifier=("analog-value", AV_INSTANCE),
                objectName="Temp",
                presentValue=AV_VALUE,
            ),
            BinaryValueObject(
                objectIdentifier=("binary-value", BV_INSTANCE),
                objectName="Fan",
                presentValue="active",
            ),
        ]
        return Application.from_object_list(objects)

    def stop(self) -> None:
        loop = self._loop
        if loop is not None:
            app = self._app

            def _shutdown() -> None:
                close = getattr(app, "close", None)
                if callable(close):
                    try:
                        close()
                    except Exception:  # noqa: BLE001 — teardown must not raise
                        pass
                loop.stop()

            try:
                loop.call_soon_threadsafe(_shutdown)
            except Exception:  # noqa: BLE001 — loop may already be gone
                pass
        if self._thread is not None:
            self._thread.join(timeout=5.0)


@pytest.fixture()
def virtual_device() -> Any:
    """Yield a live virtual BACnet/IP device, or skip if UDP bind is unavailable."""
    device = _VirtualDevice()
    try:
        device.start()
    except Exception as exc:  # noqa: BLE001 — bind refused → environment, not a bug
        pytest.skip(f"virtual BACnet/IP device unavailable: {exc}")
    try:
        yield device
    finally:
        device.stop()


@_requires_two_ips
@pytest.mark.integration
def test_bacnet_discover_read_round_trip(virtual_device: _VirtualDevice) -> None:
    """Real Who-Is discover + present-value read round-trip through the connector.

    The connector binds its own BAC0/bacpypes3 stack on ``CLIENT_IP`` and
    broadcasts Who-Is on the shared subnet; the virtual device on ``DEVICE_IP``
    answers I-Am, and the connector reads back the analog/binary present-values.
    """
    target = TargetConfig(name="virt-ahu", protocol="bacnet", host=CLIENT_IP)

    try:
        discovered = ops.bacnet_discover(target)
    except OTConnectionError as exc:  # pragma: no cover — env, reported not asserted
        pytest.skip(f"connector could not open a live BACnet session: {exc}")

    devices = discovered.get("devices", [])
    device_ids = {d.get("device_id") for d in devices}
    assert DEVICE_ID in device_ids, f"virtual device {DEVICE_ID} not discovered; got {device_ids}"
    match = next(d for d in devices if d.get("device_id") == DEVICE_ID)
    address = match["address"]

    reading = ops.bacnet_read_property(
        target, address=address, object_type="analogValue", instance=AV_INSTANCE
    )
    assert reading.get("value") == pytest.approx(AV_VALUE)

    points = ops.bacnet_read_points(target, address=address, device_id=DEVICE_ID)
    present = {
        (p["object_type"], p["instance"]): p.get("present_value") for p in points.get("points", [])
    }
    assert present.get(("analogValue", AV_INSTANCE)) == pytest.approx(AV_VALUE)


@_requires_two_ips
@pytest.mark.integration
def test_bacnet_write_reports_what_the_device_actually_did(
    virtual_device: _VirtualDevice,
) -> None:
    """The WRITE path over a real BACnet/IP wire — previously mock-only, and it
    found that ``applied: True`` was an unverified claim.

    ``bacnet_write_property`` is a **high-risk** governed write on a building
    controller. Driving it live showed that BAC0's ``write()`` returns ``None`` and
    raises nothing **whether the device honoured the request or silently dropped
    it** — against this live bacpypes3 device the present-value never moved, and
    nothing in the connector's return said so.

    So the connector now reads the value back and reports it (``after`` /
    ``verified``) instead of asserting success. It deliberately does **not** judge a
    mismatch as failure: on a commandable object a higher priority legitimately
    holds the value. Reporting is the honest primitive; judging would need the
    priority scheme, which only the operator has.

    What this test pins is therefore the *reporting*, not a value change — the
    virtual device does not accept the write, which is precisely the case where an
    unverified ``applied: True`` would mislead someone.
    """
    target = TargetConfig(name="virt-ahu", protocol="bacnet", host=CLIENT_IP)

    try:
        discovered = ops.bacnet_discover(target)
    except OTConnectionError as exc:  # pragma: no cover — env, reported not asserted
        pytest.skip(f"connector could not open a live BACnet session: {exc}")
    match = next(
        (d for d in discovered.get("devices", []) if d.get("device_id") == DEVICE_ID), None
    )
    assert match is not None, f"virtual device {DEVICE_ID} not discovered"
    address = match["address"]

    def _present() -> float:
        return ops.bacnet_read_property(
            target, address=address, object_type="analogValue", instance=AV_INSTANCE
        )["value"]

    original = _present()
    assert original == pytest.approx(AV_VALUE)

    # A dry run must not reach the device — checked by reading back, not by trusting
    # the returned dict.
    preview = ops.bacnet_write_property(
        target,
        address=address,
        object_type="analogValue",
        instance=AV_INSTANCE,
        value=99.0,
        dry_run=True,
    )
    assert preview.get("dry_run") is True
    assert "after" not in preview, "a dry run performed a read-back verification"
    assert _present() == pytest.approx(original), "a dry run reached the device"

    applied = ops.bacnet_write_property(
        target,
        address=address,
        object_type="analogValue",
        instance=AV_INSTANCE,
        value=99.0,
        dry_run=False,
    )

    # The BEFORE capture is what an operator would write back to undo, so it must be
    # what the device actually held.
    assert applied.get("before") == pytest.approx(original), (
        f"the captured BEFORE ({applied.get('before')}) is not what the device held "
        f"({original}) — an undo built from it would restore the wrong value"
    )

    # The read-back is reported, whatever it says.
    assert "after" in applied, "the write did not report a read-back"
    assert "verified" in applied

    # Cross-check the reported ``after`` against an independent read WHEN the device
    # answers one. Not asserted unconditionally: on a loaded CI runner this extra
    # round-trip times out with NoResponseFromController while the connector's own
    # in-session read-back succeeded. Failing the build on that would be testing the
    # runner's UDP latency, not the connector.
    observed: float | None = None
    try:
        observed = _present()
    except OTConnectionError:
        pass
    if observed is not None:
        assert applied["after"] == pytest.approx(observed), (
            "the reported 'after' is not what the device holds"
        )

    if applied["after"] == pytest.approx(99.0):
        assert applied["verified"] is True
    else:
        # This device does not take the write. The point of the fix is that the
        # caller is TOLD, instead of reading applied:true and believing it.
        assert applied["verified"] is False
        assert applied.get("verify_note"), "an unverified write carried no explanation"
        assert "priority" in applied["verify_note"].lower()
