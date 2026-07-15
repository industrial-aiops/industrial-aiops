"""CI-lint of the air-gapped compose (docs/AIRGAP.md + deploy/airgap/compose.yaml).

Pins the properties the guide sells: the on-box LLM is unreachable from outside the
host (internal network, no published ports, pinned image), iaiops keeps the hardened
posture and the version-pinned signed image, and the doc itself keeps the honesty
markers for the not-yet-live-verified tiers.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

import yaml

REPO = Path(__file__).resolve().parent.parent
COMPOSE = REPO / "deploy" / "airgap" / "compose.yaml"


def _project_version() -> str:
    with (REPO / "pyproject.toml").open("rb") as fh:
        return tomllib.load(fh)["project"]["version"]


def _compose() -> dict[str, Any]:
    return yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))


class TestIaiopsService:
    def test_uses_published_pinned_image(self) -> None:
        expected = (
            f"ghcr.io/industrial-aiops/iaiops:{_project_version()}" + "-${IAIOPS_MCP:-factory}"
        )
        assert _compose()["services"]["iaiops"]["image"] == expected

    def test_keeps_hardened_posture(self) -> None:
        service = _compose()["services"]["iaiops"]
        assert service["read_only"] is True
        assert service["cap_drop"] == ["ALL"]
        assert service["security_opt"] == ["no-new-privileges:true"]
        assert service["user"] == "10001:10001"

    def test_mcp_port_is_loopback_bound(self) -> None:
        ports = _compose()["services"]["iaiops"]["ports"]
        assert all(str(p).startswith("127.0.0.1:") for p in ports)


class TestOllamaService:
    def test_image_is_version_pinned(self) -> None:
        image = _compose()["services"]["ollama"]["image"]
        _, _, tag = image.partition(":")
        assert tag and tag != "latest", f"ollama image must be pinned, got {image!r}"

    def test_publishes_no_ports(self) -> None:
        # The LLM must be reachable only from iaiops on the internal network.
        assert "ports" not in _compose()["services"]["ollama"]

    def test_sits_only_on_the_internal_network(self) -> None:
        compose = _compose()
        assert compose["services"]["ollama"]["networks"] == ["llm"]
        assert compose["networks"]["llm"]["internal"] is True

    def test_iaiops_can_reach_it(self) -> None:
        assert "llm" in _compose()["services"]["iaiops"]["networks"]


class TestHonestyMarkers:
    def test_airgap_doc_keeps_the_pending_verifications(self) -> None:
        doc = (REPO / "docs" / "AIRGAP.md").read_text(encoding="utf-8")
        # Tiers 2/3 live passes are not verified yet — the doc must keep saying so
        # until a real pass is recorded (repo honesty discipline).
        assert "待核实" in doc
