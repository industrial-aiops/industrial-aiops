"""Defects an adversarial review of #258 found — each breaks the three-level
contract (D41) or a claim the docs make.

1. A device that ANSWERED with an error (Modbus exception: wrong address; IO-Link
   identity mismatch) was reported reachable=false — "the device is offline".
2. Short IO-Link process data (no pd_bits) raised a plain ValueError → unreachable.
3. An empty answer (legacy address, no registers) was reported decodable=true.
4. The skill said read-only while IAIOPS_MCP=sensor exposes mqtt_publish.
5. The CLI still said it contacts nothing; it exited 0 on a failed probe.
6. A ref refused before contact said decodable=false, against the docstring.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from iaiops.core.runtime.sensor import InvalidReadingError, decode_bits, parse_profile
from iaiops.core.runtime.sensor.probe import read_channel
from iaiops.core.runtime.session_factory import (
    OTConnectionError,
    OTNoReadingError,
    OTProtocolError,
)

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parent.parent

PROFILE = parse_profile(
    {
        "id": "force",
        "protocol": "modbus",
        "source": "manual",
        "verified": "bench",
        "channels": [
            {
                "name": "fz",
                "layout": {"table": "input", "address": 0, "type": "int16"},
                "unit": "N",
                "signal": "level",
            }
        ],
    }
)


@pytest.fixture
def bound(monkeypatch):
    monkeypatch.setattr("iaiops.core.runtime.sensor.binding.cached_profile", lambda path: PROFILE)
    return SimpleNamespace(
        name="cell", protocol="modbus", sensor_profile="force.yaml", port_profiles=()
    )


def _caps(monkeypatch, result):
    from iaiops.core.runtime import capabilities

    def read_ref(target, ref):
        if isinstance(result, Exception):
            raise result
        return result

    cap = capabilities.REGISTRY["modbus"]
    monkeypatch.setitem(
        capabilities.REGISTRY, "modbus", type(cap)(**{**cap.__dict__, "read_ref": read_ref})
    )


@pytest.mark.parametrize(
    "error",
    [
        OTProtocolError(
            "Modbus read at address 9999 failed: illegal data address", protocol="modbus"
        ),
        OTNoReadingError("A different sensor is on this port", protocol="iolink"),
    ],
)
def test_1_a_device_that_answered_with_an_error_is_reachable(monkeypatch, bound, error):
    _caps(monkeypatch, error)
    out = read_channel(bound, "ch:fz")
    assert out["levels"] == {"reachable": True, "decodable": False}
    assert str(error) in out["reason"]


def test_1_a_real_connection_failure_is_still_unreachable(monkeypatch, bound):
    _caps(monkeypatch, OTConnectionError("timed out", protocol="modbus"))
    assert read_channel(bound, "ch:fz")["levels"] == {"reachable": False, "decodable": None}


def test_2_short_process_data_is_not_a_measurement():
    channel = parse_profile(
        {
            "id": "t",
            "protocol": "iolink",
            "source": "manual",
            "verified": "bench",
            "channels": [
                {
                    "name": "distance",
                    "layout": {"bit_offset": 16, "bit_length": 16, "type": "uint"},
                    "unit": "mm",
                    "signal": "level",
                }
            ],
        }
    ).channel("distance")
    with pytest.raises(InvalidReadingError, match="16 bits"):
        decode_bits(channel, bytes([1, 2]))


def test_3_an_empty_answer_is_not_decodable(monkeypatch, bound):
    _caps(monkeypatch, {"value": None, "good": True})
    out = read_channel(bound, "40")
    assert out["levels"] == {"reachable": True, "decodable": False}
    assert "no value" in out["reason"]


def test_4_the_skill_does_not_claim_a_read_only_server():
    text = (ROOT / "skills" / "iaiops-sensor" / "SKILL.md").read_text("utf-8")
    assert "mqtt_publish" in text and "MOC" in text
    assert "Read-only; never writes device or config" not in text


def test_5_cli_help_no_longer_says_it_contacts_nothing():
    from iaiops.cli import sensor

    assert "Contacts nothing" not in (sensor.sensor_app.info.help or "")
    assert "neither contacts a device" not in (sensor.__doc__ or "")


@pytest.mark.parametrize(
    ("levels", "code"),
    [
        ({"reachable": True, "decodable": True}, 0),
        ({"reachable": True, "decodable": False}, 1),
        ({"reachable": False, "decodable": None}, 1),
        ({"reachable": None, "decodable": None}, 1),
    ],
)
def test_5_cli_exit_code_follows_the_levels(monkeypatch, levels, code):
    from typer.testing import CliRunner

    from iaiops.cli.sensor import sensor_app

    monkeypatch.setattr(
        "iaiops.core.runtime.sensor.probe.read_channel",
        lambda target, ref: {"levels": levels, "reason": "x", "value": 1.0},
    )
    monkeypatch.setattr(
        "iaiops.core.runtime.connection.ConnectionManager.from_config",
        classmethod(
            lambda cls, config=None: SimpleNamespace(target=lambda name: SimpleNamespace(name=name))
        ),
    )
    assert CliRunner().invoke(sensor_app, ["read", "cell", "ch:fz"]).exit_code == code


def test_6_a_ref_refused_before_contact_reports_no_levels_and_says_refused(monkeypatch, bound):
    _caps(monkeypatch, AssertionError("must not be contacted"))
    out = read_channel(bound, "ch:nope")
    assert out["levels"] == {"reachable": None, "decodable": None}
    assert out["refused"] is True and out["contacted"] is False


def test_a_profile_lost_after_a_good_read_keeps_the_reading(monkeypatch, bound):
    _caps(monkeypatch, {"value": 3.0, "good": True})

    def gone(target, ref):
        raise FileNotFoundError("force.yaml")

    monkeypatch.setattr("iaiops.core.runtime.sensor.probe._profile_context", gone)
    out = read_channel(bound, "ch:fz")
    assert out["levels"]["decodable"] is True and out["value"] == 3.0
    assert "profile" in out.get("note", "")


def test_a_deleted_profile_is_a_ref_problem_not_a_crash(monkeypatch):
    from iaiops.core.collect.reader import ref_problems

    def gone(path):
        raise FileNotFoundError(path)

    monkeypatch.setattr("iaiops.core.runtime.sensor.binding.cached_profile", gone)
    target = SimpleNamespace(
        name="cell", protocol="modbus", sensor_profile="force.yaml", port_profiles=()
    )
    problems = ref_problems(target, ("ch:fz",))
    assert problems and "force.yaml" in problems[0]


def test_file_tools_refuse_symlinks(tmp_path):
    import mcp_server.tools.sensor_tools as tools

    real = tmp_path / "real.yaml"
    real.write_text("id: x\n", "utf-8")
    link = tmp_path / "link.yaml"
    link.symlink_to(real)
    assert "symbolic link" in tools.sensor_profile_check(str(link))["error"]
