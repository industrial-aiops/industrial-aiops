"""A real secsgem GEM equipment, run as a standalone process.

Why a separate process rather than an in-test handler: ``GemEquipmentHandler``
does not survive repeated ``enable()`` / ``disable()`` in one interpreter. Sharing
one handler across tests made the SECS/GEM live suite fail non-deterministically
(the equipment logs ``WrongSourceStateError: Invalid source state for transition
'select': COMMUNICATING (expected NOT_COMMUNICATING)`` — it has not returned to
NOT_COMMUNICATING before the next ACTIVE connect lands), and creating a fresh one
per test hung the interpreter on teardown.

The energy repo's DNP3 live test reaches for the same shape for the same reason:
when a protocol library's shutdown is unreliable in a long-lived interpreter, give
it a process to own and kill the process.

Usage (the fixture in ``test_secsgem_live.py`` does this)::

    python tests/secsgem_equipment_harness.py <port>

Prints ``READY`` on stdout once the listener is up, then serves until killed.
"""

from __future__ import annotations

import sys
import time

SVID = 7001
SV_VALUE = 237
ECID = 8001
EC_VALUE = 412
ALID = 9001
ALARM_TEXT = "chamber over temperature"
ALARM_CODE = 0b10000000


def main(port: int) -> None:
    import secsgem.secs.variables as sv
    from secsgem.gem import Alarm, EquipmentConstant, GemEquipmentHandler, StatusVariable
    from secsgem.hsms import DeviceType, HsmsConnectMode, HsmsSettings

    settings = HsmsSettings(
        address="127.0.0.1",
        port=port,
        connect_mode=HsmsConnectMode.PASSIVE,
        device_type=DeviceType.EQUIPMENT,
        session_id=0,
    )
    handler = GemEquipmentHandler(settings)

    # Seeded by us, so an assertion cannot pass on secsgem's built-ins alone.
    handler.status_variables[SVID] = StatusVariable(
        SVID, "ChamberTemp", "degC", sv.U4, use_callback=False
    )
    handler.status_variables[SVID].value = SV_VALUE
    handler.equipment_constants[ECID] = EquipmentConstant(
        ECID, "MaxTemp", 0, 500, 300, "degC", sv.U4, use_callback=False
    )
    handler.equipment_constants[ECID].value = EC_VALUE
    handler.alarms[ALID] = Alarm(ALID, "OverTemp", ALARM_TEXT, ALARM_CODE, 100, 101)

    handler.enable()
    print("READY", flush=True)
    while True:
        time.sleep(3600)


if __name__ == "__main__":
    main(int(sys.argv[1]))
