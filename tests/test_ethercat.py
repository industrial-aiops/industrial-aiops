"""EtherCAT ops tests against a MOCKED pysoem master.

EtherCAT cannot be simulated in software — it needs Linux + root/CAP_NET_RAW + a
dedicated NIC + real slaves. So the pysoem ``Master`` is faked by monkeypatching
``connection._build_ethercat_master``, exercising bus scan, slave detail, CoE SDO
read, PDO snapshot, and the MOC-gated SDO write + AL-state change (dry-run +
before/state capture for undo) WITHOUT any hardware.
"""

from __future__ import annotations

import pytest

import iaiops.core.runtime.connection as conn
from iaiops.connectors.ethercat import ops
from iaiops.core.runtime.config import TargetConfig

# pysoem AL-state codes
INIT, PREOP, SAFEOP, OP = 1, 2, 4, 8


class _FakeSM:
    def __init__(self, start, length, flags=0):
        self.start_addr = start
        self.sm_length = length
        self.sm_flags = flags


class _FakeFMMU:
    def __init__(self, log_start, log_length, fmmu_type=1):
        self.log_start = log_start
        self.log_length = log_length
        self.fmmu_type = fmmu_type


class _FakeSlave:
    def __init__(self, name, man, pid, rev, addr, state):
        self.name = name
        self.man = man
        self.id = pid
        self.rev = rev
        self.config_addr = addr
        self.state = state
        self.input = b"\x01\x02\x03\x04"
        self.output = b"\x00\x00"
        self._sdo = {(0x1018, 1): b"\x9a\x02\x00\x00", (0x607A, 0): b"\xe8\x03\x00\x00"}
        self.sm = [_FakeSM(0x1000, 8), _FakeSM(0x1400, 16)] + [_FakeSM(0, 0)] * 6
        self.fmmu = [_FakeFMMU(0x00010000, 4)] + [_FakeFMMU(0, 0)] * 7
        self.od = []
        self.written: dict = {}
        self.state_written = False

    def sdo_read(self, index, subindex, size=None):
        return self._sdo.get((index, subindex), b"")

    def sdo_write(self, index, subindex, data, ca=False):
        self.written[(index, subindex)] = bytes(data)
        self._sdo[(index, subindex)] = bytes(data)

    def write_state(self):
        self.state_written = True

    def state_check(self, code, timeout):
        self.state = code
        return code


class _FakeMaster:
    def __init__(self, slaves):
        self.slaves = slaves
        self.expected_wkc = 3
        self.state = SAFEOP
        self.opened = None
        self.mapped = False
        self.state_written = False

    def open(self, nic):
        self.opened = nic

    def config_init(self, usetable=False):
        return len(self.slaves)

    def config_map(self):
        self.mapped = True
        return 6

    def read_state(self):
        return min((s.state for s in self.slaves), default=self.state)

    def send_processdata(self):
        pass

    def receive_processdata(self, timeout):
        return 3

    def write_state(self):
        self.state_written = True

    def state_check(self, code, timeout):
        self.state = code
        return code

    def close(self):
        self.opened = None


@pytest.fixture
def ec_target(monkeypatch):
    slaves = [
        _FakeSlave("EK1100", 2, 0x044C2C52, 0x00110000, 1001, OP),
        _FakeSlave("EL2008", 2, 0x07D83052, 0x00100000, 1002, OP),
    ]
    master = _FakeMaster(slaves)
    monkeypatch.setattr(conn, "_build_ethercat_master", lambda target: master)
    target = TargetConfig(name="bus1", protocol="ethercat", nic="eth1", expected_slaves=2)
    return target, master


@pytest.mark.unit
def test_master_state(ec_target):
    target, _ = ec_target
    out = ops.ethercat_master_state(target)
    assert out["master_state"] == "OP"
    assert out["slaves_found"] == 2
    assert out["slaves_expected"] == 2
    assert out["slave_count_ok"] is True
    assert out["expected_working_counter"] == 3


@pytest.mark.unit
def test_slaves_scan(ec_target):
    target, _ = ec_target
    out = ops.ethercat_slaves(target)
    assert out["slave_count"] == 2
    first = out["slaves"][0]
    assert first["name"] == "EK1100"
    assert first["vendor_id"] == 2
    assert first["config_addr"] == 1001
    assert first["state"] == "OP"


@pytest.mark.unit
def test_slave_info(ec_target):
    target, _ = ec_target
    out = ops.ethercat_slave_info(target, 1)
    assert out["name"] == "EL2008"
    assert out["input_bytes"] == 4
    assert len(out["sync_managers"]) == 2
    assert out["sync_managers"][0]["start_addr"] == 0x1000
    assert len(out["fmmus"]) == 1


@pytest.mark.unit
def test_read_sdo(ec_target):
    target, _ = ec_target
    out = ops.ethercat_read_sdo(target, 0, 0x1018, 1)
    assert out["index"] == "0x1018"
    assert out["hex"] == "9a020000"
    assert out["as_uint"] == 666  # 0x029a little-endian


@pytest.mark.unit
def test_read_pdo(ec_target):
    target, _ = ec_target
    out = ops.ethercat_read_pdo(target, 0)
    assert out["working_counter"] == 3
    assert out["input_hex"] == "01020304"
    assert out["input_byte_length"] == 4


@pytest.mark.unit
def test_write_sdo_dry_run_does_not_write(ec_target):
    target, master = ec_target
    out = ops.ethercat_write_sdo(target, 1, 0x607A, "f4010000", dry_run=True)
    assert out["dry_run"] is True
    assert out["before"] == "e8030000"  # captured BEFORE value
    assert out["would_write"] == "f4010000"
    assert master.slaves[1].written == {}


@pytest.mark.unit
def test_write_sdo_applied_captures_before(ec_target):
    target, master = ec_target
    out = ops.ethercat_write_sdo(target, 1, 0x607A, "f4010000", dry_run=False)
    assert out["applied"] is True
    assert out["before"] == "e8030000"
    assert master.slaves[1].written[(0x607A, 0)] == bytes.fromhex("f4010000")


@pytest.mark.unit
def test_write_sdo_rejects_non_hex(ec_target):
    target, _ = ec_target
    with pytest.raises(ValueError, match="hex string"):
        ops.ethercat_write_sdo(target, 1, 0x607A, "not-hex", dry_run=True)


@pytest.mark.unit
def test_set_state_dry_run_captures_current(ec_target):
    target, master = ec_target
    out = ops.ethercat_set_state(target, "PREOP", slave=0, dry_run=True)
    assert out["dry_run"] is True
    assert out["before"] == "OP"
    assert out["would_request"] == "PREOP"
    assert master.slaves[0].state_written is False  # nothing changed


@pytest.mark.unit
def test_set_state_applied(ec_target):
    target, master = ec_target
    out = ops.ethercat_set_state(target, "SAFEOP", slave=0, dry_run=False)
    assert out["applied"] is True
    assert out["before"] == "OP"
    assert out["requested"] == "SAFEOP"
    assert out["reached"] == "SAFEOP"
    assert master.slaves[0].state == SAFEOP


@pytest.mark.unit
def test_set_state_master_scope(ec_target):
    target, master = ec_target
    out = ops.ethercat_set_state(target, "INIT", slave=-1, dry_run=False)
    assert out["scope"] == "master"
    assert out["reached"] == "INIT"
    assert master.state == INIT


@pytest.mark.unit
def test_set_state_rejects_unknown_state(ec_target):
    target, _ = ec_target
    with pytest.raises(ValueError, match="Unknown EtherCAT state"):
        ops.ethercat_set_state(target, "BOGUS", slave=0, dry_run=True)


@pytest.mark.unit
def test_sdo_undo_descriptor_restores_before():
    from mcp_server.tools.ethercat_tools import _sdo_undo

    params = {"endpoint": "bus1", "slave": 1, "index": "0x607A", "subindex": 0}
    result = {"applied": True, "before": "e8030000"}
    undo = _sdo_undo(params, result)
    assert undo["tool"] == "ethercat_write_sdo"
    assert undo["params"]["value"] == "e8030000"
    assert undo["params"]["dry_run"] is False


@pytest.mark.unit
def test_state_undo_descriptor_restores_before():
    from mcp_server.tools.ethercat_tools import _state_undo

    params = {"endpoint": "bus1", "slave": 0}
    result = {"applied": True, "before": "OP", "scope": "slave[0]"}
    undo = _state_undo(params, result)
    assert undo["tool"] == "ethercat_set_state"
    assert undo["params"]["state"] == "OP"


@pytest.mark.unit
def test_state_undo_skips_uninvertible():
    from mcp_server.tools.ethercat_tools import _state_undo

    # NONE / error states are not cleanly re-requestable → no undo.
    assert _state_undo({}, {"applied": True, "before": "NONE", "scope": "master"}) is None
    assert _state_undo({}, {"applied": False}) is None


@pytest.mark.unit
def test_no_slaves_gives_teaching_error(monkeypatch):
    master = _FakeMaster([])
    monkeypatch.setattr(conn, "_build_ethercat_master", lambda target: master)
    target = TargetConfig(name="bus1", protocol="ethercat", nic="eth1")
    with pytest.raises(conn.OTConnectionError, match="No EtherCAT slaves"):
        ops.ethercat_slave_info(target, 0)
