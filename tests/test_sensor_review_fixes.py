"""Defects an adversarial review of #248 found — each a plausible wrong value.

1. `hr:12:int16*` (the number forgotten) silently meant scale 1.
2. NaN / inf / overflowing scale, offset or range were accepted, and the
   finiteness check ran before scaling.
3. float32 was rounded to 6 decimals: 3.2e-9 became 0.0.
4. `modbus health` said overall "ok" when nothing could be classified.
5. A sentinel wider than its field loaded fine and could never match.
6. A device answering with too few registers raised a plain ValueError, which
   tears a held collection session down — it answered; that is a gap.
7. Bare addresses `int()` used to accept were refused; non-ASCII digits were not.
"""

from __future__ import annotations

import math
import struct

import pytest

import iaiops.core.runtime.connection as conn
from iaiops.connectors.modbus import ops
from iaiops.connectors.modbus.points import parse_point, read_point_value
from iaiops.core.runtime.config import MonitorTag, TargetConfig
from iaiops.core.runtime.sensor import InvalidReadingError, decode_registers, parse_profile

pytestmark = pytest.mark.unit


def _f32(value: float) -> list[int]:
    a, b, c, d = struct.pack(">f", value)
    return [(a << 8) | b, (c << 8) | d]


def _profile_channel(**extra):
    raw = {
        "id": "t",
        "protocol": "modbus",
        "source": "manual",
        "verified": "bench",
        "channels": [
            {
                "name": "c",
                "layout": {"table": "input", "address": 0, "type": "uint16"},
                "unit": "u",
                "signal": "level",
                **extra,
            }
        ],
    }
    return raw


def test_1_an_empty_scale_is_refused():
    with pytest.raises(ValueError, match="scale"):
        parse_point("hr:12:int16*")


@pytest.mark.parametrize("scale", ["nan", "inf", "-inf", "1e400"])
def test_2_non_finite_scale_is_refused(scale):
    with pytest.raises(ValueError, match="scale"):
        parse_point(f"hr:0:int16*{scale}")


@pytest.mark.parametrize(
    "extra",
    [{"scale": math.nan}, {"offset": math.inf}, {"range": [math.nan, 5]}, {"range": [0, math.inf]}],
)
def test_2_non_finite_profile_numbers_are_refused(extra):
    with pytest.raises(ValueError, match="finite"):
        parse_profile(_profile_channel(**extra))


def test_2_overflow_after_scaling_is_not_a_reading():
    raw = _profile_channel(scale=1e308)
    raw["channels"][0]["layout"] = {
        "table": "input",
        "address": 0,
        "type": "float32",
        "order": "ABCD",
    }
    channel = parse_profile(raw).channel("c")
    with pytest.raises(InvalidReadingError, match="finite"):
        decode_registers(channel, _f32(3.0e38))


def test_3_small_floats_keep_their_value():
    value = read_point_value(lambda t, a, n: _f32(3.2e-9)[:n], "ir:0:float32:ABCD")
    assert value == pytest.approx(3.2e-9, rel=1e-6)


def test_4_health_is_not_ok_when_nothing_could_be_classified(monkeypatch):
    class _Resp:
        def __init__(self, regs):
            self.registers = regs

        def isError(self):  # noqa: N802
            return False

    class _Client:
        def connect(self):
            return True

        def close(self):
            return None

        def read_holding_registers(self, address, *, count=1, device_id=1, **kw):
            return _Resp(_f32(math.nan)[:count])

        def read_input_registers(self, address, *, count=1, device_id=1, **kw):
            return _Resp(_f32(math.nan)[:count])

    monkeypatch.setattr(conn, "_build_modbus_client", lambda target: _Client())
    target = TargetConfig(
        name="plc1",
        protocol="modbus",
        host="127.0.0.1",
        tags=(MonitorTag(ref="ir:0:float32"), MonitorTag(ref="hr:1:float32:ABCD")),
    )
    out = ops.modbus_health_summary(target)
    assert out["counts"]["unknown"] == 2
    assert out["overall"] == "unknown"


def test_5_a_sentinel_wider_than_its_field_is_refused():
    with pytest.raises(ValueError, match="sentinel"):
        parse_profile(_profile_channel(invalid=[{"raw": 0xFFFFF, "meaning": "no target"}]))


def test_5_full_scale_must_be_positive():
    with pytest.raises(ValueError, match="full_scale"):
        parse_profile(_profile_channel(accuracy={"full_scale": 0, "linearity_pct": 1}))


def test_6_a_short_answer_is_not_a_reading():
    with pytest.raises(InvalidReadingError, match="2 register"):
        read_point_value(lambda t, a, n: [0x4000], "ir:0:float32:ABCD")


@pytest.mark.parametrize(("ref", "address"), [("40", 40), ("+40", 40), ("4_0", 40), ("040", 40)])
def test_7_bare_addresses_int_accepted_still_parse(ref, address):
    point = parse_point(ref)
    assert point.legacy and point.address == address


@pytest.mark.parametrize("ref", ["²", "٤٠", "-1"])
def test_7_non_ascii_or_negative_bare_addresses_are_refused_with_the_grammar(ref):
    with pytest.raises(ValueError, match="grammar|address"):
        parse_point(ref)


def test_7_a_threshold_override_keyed_by_the_int_still_applies(monkeypatch):
    class _Resp:
        registers = [95]

        def isError(self):  # noqa: N802
            return False

    class _Client:
        def connect(self):
            return True

        def close(self):
            return None

        def read_holding_registers(self, address, *, count=1, device_id=1, **kw):
            return _Resp()

    monkeypatch.setattr(conn, "_build_modbus_client", lambda target: _Client())
    target = TargetConfig(name="p", protocol="modbus", host="h", tags=(MonitorTag(ref="040"),))
    out = ops.modbus_health_summary(target, thresholds={"40": {"alarm_high": 90}})
    assert out["overall"] == "alarm"


def test_7_resume_rechecks_refs(tmp_path, monkeypatch):
    import yaml
    from typer.testing import CliRunner

    from iaiops.cli.collect import collect_app
    from iaiops.core.collect.plan import CollectionPlan
    from iaiops.core.collect.session import Session

    path = tmp_path / "config.yaml"
    path.write_text(
        yaml.safe_dump({"targets": [{"name": "s", "protocol": "modbus", "host": "h"}]}), "utf-8"
    )
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("IAIOPS_CONFIG", str(path))
    import iaiops.core.collect.session as session_mod

    monkeypatch.setattr(
        session_mod, "session_path", lambda run_id, base_dir=None: tmp_path / f"{run_id}.json"
    )
    from datetime import UTC, datetime

    now = datetime.now(UTC).isoformat()
    session = Session(
        run_id="s-old",
        plan=CollectionPlan(endpoint="s", tags=("ir:0:float32",), duration_s=3600),
        started_at=now,
    )
    monkeypatch.setattr("iaiops.core.collect.session.find_resumable", lambda endpoint, now: session)

    def _must_not_run(*args, **kwargs):  # a mutant must fail here, not sample for an hour
        raise AssertionError("collection started on a plan with an unreadable ref")

    monkeypatch.setattr("iaiops.core.collect.runner.run_collection", _must_not_run)
    result = CliRunner().invoke(collect_app, ["run", "s", "--duration", "1h", "--resume"])
    assert result.exit_code == 1
    assert "Cannot resume" in result.output and "order" in result.output


@pytest.mark.parametrize("ref", ["hr:٤٠", "ir:²:uint16"])
def test_7_typed_addresses_are_ascii_digits(ref):
    with pytest.raises(ValueError, match="address"):
        parse_point(ref)
