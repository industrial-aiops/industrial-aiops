"""The whole pipeline against a real device: scan → store → report.

Every other test drives one stage with the next one faked. This runs the actual
product end to end — a real pymodbus server answering a real FC43 identification
over a real socket, swept by the real sweeper, identified by the real probe,
written to a real SQLite file, and rendered into the real HTML — and asserts
that a vendor name typed into the server's identity block comes out the far end
in the report.

It needs a container for one specific reason: the port allowlist permits 502 and
nothing else, and binding 502 needs root. That constraint is the product working
as designed, so the test bends rather than the allowlist.

The vendor string is deliberately non-ASCII. The one real decoding bug found in
this work was an ASCII-first Modbus identity decoder that flagged 汇川 as
undecodable, and it survived every test whose fixtures were ASCII — because the
fake and the parser agreed with each other and were both wrong.
"""

from __future__ import annotations

import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

pytestmark = [pytest.mark.integration]

_IMAGE = "python:3.12-slim"

_SCENARIO = textwrap.dedent(
    """
    import sys, threading, time
    sys.path.insert(0, "/work")

    from pymodbus.datastore import (
        ModbusDeviceContext, ModbusSequentialDataBlock, ModbusServerContext,
    )
    from pymodbus.pdu.device import ModbusDeviceIdentification
    from pymodbus.server import StartTcpServer

    VENDOR, PRODUCT, REVISION = "汇川 Inovance", "AM401-CPU1608TP", "2.1.7"

    identity = ModbusDeviceIdentification()
    identity.VendorName = VENDOR
    identity.ProductCode = PRODUCT
    identity.MajorMinorRevision = REVISION

    store = ModbusDeviceContext(hr=ModbusSequentialDataBlock(1, [7] * 16))
    context = ModbusServerContext(devices=store, single=True)

    threading.Thread(
        target=StartTcpServer,
        kwargs={"context": context, "identity": identity, "address": ("127.0.0.1", 502)},
        daemon=True,
    ).start()
    time.sleep(2.0)

    from iaiops.core.discovery.report import render_html
    from iaiops.core.discovery.runner import run_scan
    from iaiops.core.discovery.types import Authorization, PacingPolicy, ScanPlan
    from iaiops.core.sink.scan_store import list_scans, load_scan, save_scan

    plan = ScanPlan(
        site="Container Line 1",
        hosts=("127.0.0.1",),
        profile="inventory",
        pacing=PacingPolicy(connects_per_second=50, max_concurrency=2,
                            per_host_gap_ms=0, identify_gap_ms=0),
        authorization=Authorization(approved_by="test harness", ticket="E2E-1"),
    )

    result = run_scan(plan)
    # Diagnostics BEFORE the assertions. "partial" alone does not say whether the
    # device stayed silent or the probe could not load, and those are opposite
    # diagnoses — printing first makes a container failure readable in one run.
    print("VERDICT", result.verdict)
    print("WIRE", result.wire_summary)
    print("NOTES", result.notes)
    for h in result.hosts:
        print("HOST", h.ip, [(p.port, p.state) for p in h.ports])
        for c in h.protocols:
            print("   CANDIDATE", c.protocol, c.confidence, c.evidence, "|", c.detail)

    assert result.verdict == "ok", (result.verdict, result.notes)
    host = result.hosts[0]
    assert host.ip == "127.0.0.1"
    assert any(p.port == 502 and p.state == "open" for p in host.ports), host.ports

    modbus = [c for c in host.protocols if c.protocol == "modbus"]
    assert modbus, host.protocols
    # The detail rides into the failure message: "port_only" alone does not say
    # whether the DEVICE stayed silent or this container simply could not load
    # the probe, and those are opposite diagnoses.
    assert modbus[0].confidence == "confirmed", (modbus[0].evidence, modbus[0].detail)
    assert host.identity["modbus"]["vendor"] == VENDOR, host.identity
    assert host.identity["modbus"]["model"] == PRODUCT, host.identity
    assert host.identity["modbus"]["firmware"] == REVISION, host.identity

    # Every port the sweep touched must have been on the allowlist, and 502 must
    # have been asked exactly once by the identify stage.
    assert result.wire_summary["modbus_fc43"] == 1, result.wire_summary
    assert set(result.wire_summary) <= {"tcp_connect", "modbus_fc43"}, result.wire_summary

    scan_id = save_scan(result, "/tmp/e2e.db")
    assert len(list_scans("/tmp/e2e.db")) == 1
    stored = load_scan(scan_id, "/tmp/e2e.db")
    assert stored["hosts"][0]["vendor"] == VENDOR, stored["hosts"][0]
    assert stored["hosts"][0]["open_ports"] == [502]
    assert stored["hosts"][0]["identity_from"] == "modbus"

    html = render_html(stored)
    assert VENDOR in html, "the vendor did not survive to the report"
    assert PRODUCT in html
    assert "What this scan touched" in html
    assert html.index("What this scan touched") < html.index("&middot; Devices")
    assert "http://" not in html and "https://" not in html

    # Re-storing the same survey must not manufacture a second one.
    save_scan(result, "/tmp/e2e.db")
    assert len(list_scans("/tmp/e2e.db")) == 1

    print("E2E_OK", scan_id, len(html))

    # ── and now the same thing through the COMMAND ──────────────────────────
    # The library working does not mean the command works, and the command is
    # the only part a person ever touches. Everything above could pass while
    # `iaiops scan run` is broken by a bad flag name, a missing registration or
    # an exception class the CLI does not translate.
    from typer.testing import CliRunner

    from iaiops.cli._root import app

    cli = CliRunner()

    preview = cli.invoke(app, ["scan", "plan", "--targets", "127.0.0.1"])
    assert preview.exit_code == 0, preview.output
    assert "nothing has been sent" in preview.output.lower()

    run = cli.invoke(
        app,
        [
            "scan", "run", "--yes",
            "--targets", "127.0.0.1",
            "--site", "Container Line 1",
            "--db", "/tmp/cli.db",
            "--report", "/tmp/cli-survey.html",
        ],
    )
    assert run.exit_code == 0, run.output
    assert VENDOR in run.output, run.output

    cli_html = open("/tmp/cli-survey.html", encoding="utf-8").read()
    assert VENDOR in cli_html
    assert PRODUCT in cli_html
    assert "What this scan touched" in cli_html

    listed = cli.invoke(app, ["scan", "list", "--db", "/tmp/cli.db"])
    assert listed.exit_code == 0, listed.output
    assert "Container Line 1" in listed.output

    rerender = cli.invoke(
        app, ["scan", "report", "--out", "/tmp/cli-again.html", "--db", "/tmp/cli.db"]
    )
    assert rerender.exit_code == 0, rerender.output
    assert VENDOR in open("/tmp/cli-again.html", encoding="utf-8").read()

    print("CLI_OK", len(cli_html))
    """
)


def _docker_available() -> bool:
    if not shutil.which("docker"):
        return False
    return subprocess.run(["docker", "info"], capture_output=True).returncode == 0


@pytest.mark.skipif(
    not _docker_available(), reason="docker unavailable — needs a container runtime"
)
def test_scan_store_and_report_against_a_real_modbus_device(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parent.parent
    (tmp_path / "scenario.py").write_text(_SCENARIO, encoding="utf-8")

    script = (
        "set -e\n"
        # iaiops's own base deps too: TargetConfig pulls in yaml + dotenv, and without
        # them the probe fails as "unavailable" and the scan reports port_only —
        # a result that looks like a silent device rather than a missing library.
        "pip install -q 'pymodbus>=3.5,<4' pyyaml python-dotenv cryptography "
        "typer rich 'mcp[cli]' >/dev/null 2>&1 "
        "|| { echo NO_PYMODBUS; exit 2; }\n"
        "python3 /probe/scenario.py\n"
    )
    proc = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "-v",
            f"{repo_root}:/work:ro",
            "-v",
            f"{tmp_path}:/probe:ro",
            _IMAGE,
            "sh",
            "-c",
            script,
        ],
        capture_output=True,
        text=True,
        timeout=600,
    )
    output = proc.stdout + proc.stderr
    if proc.returncode == 2 or "NO_PYMODBUS" in output:
        pytest.skip("could not install pymodbus in the container (no network?)")
    assert proc.returncode == 0, output
    assert "E2E_OK" in output, output
    assert "CLI_OK" in output, output
