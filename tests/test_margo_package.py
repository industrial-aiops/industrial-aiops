"""CI-lint of the Margo application package against the pinned profile bundles.

The Margo skeleton under ``deploy/margo/`` (descriptor + Dockerfile + deploy-ready
compose) and the ``publish-image`` workflow all hardcode the released version and
the five edition profiles. These tests pin the whole chain to a single source of
truth so a release bump or a profile-menu change cannot silently drift:

* descriptor ``metadata.version`` == ``pyproject.toml`` version,
* descriptor profile options == workflow build matrix == pip extras, and every
  option is a real ``NAMED_PROFILES`` entry,
* ``packageLocation`` / ``keyLocation`` point at the current release asset and the
  committed cosign public key,
* the packaged compose references the published, version-pinned GHCR image with
  the same hardened posture as the dev compose (non-root, read-only, no caps),
* every descriptor parameter pointer is an env var the packaged compose wires.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path
from typing import Any

import yaml

from mcp_server.profiles import NAMED_PROFILES

REPO = Path(__file__).resolve().parent.parent
MARGO_DIR = REPO / "deploy" / "margo"


def _project_version() -> str:
    with (REPO / "pyproject.toml").open("rb") as fh:
        return tomllib.load(fh)["project"]["version"]


def _load_yaml(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _descriptor() -> dict[str, Any]:
    return _load_yaml(MARGO_DIR / "margo.yaml")


def _descriptor_profiles() -> list[str]:
    schemas = _descriptor()["configuration"]["schema"]
    profile = next(s for s in schemas if s["name"] == "profileSchema")
    return profile["options"]


class TestDescriptorVersion:
    def test_matches_pyproject(self) -> None:
        assert _descriptor()["metadata"]["version"] == _project_version()

    def test_dockerfile_default_matches_pyproject(self) -> None:
        dockerfile = (MARGO_DIR / "Dockerfile").read_text(encoding="utf-8")
        match = re.search(r"^ARG IAIOPS_VERSION=(\S+)$", dockerfile, re.MULTILINE)
        assert match is not None, "Dockerfile must default ARG IAIOPS_VERSION"
        assert match.group(1) == _project_version()


class TestProfileBundles:
    def test_descriptor_options_are_real_profiles(self) -> None:
        unknown = set(_descriptor_profiles()) - set(NAMED_PROFILES)
        assert not unknown, f"descriptor offers profiles missing from NAMED_PROFILES: {unknown}"

    def test_descriptor_options_are_pip_extras(self) -> None:
        with (REPO / "pyproject.toml").open("rb") as fh:
            extras = tomllib.load(fh)["project"]["optional-dependencies"]
        missing = set(_descriptor_profiles()) - set(extras)
        assert not missing, f"descriptor profiles without a same-named pip extra: {missing}"

    def test_workflow_matrix_matches_descriptor(self) -> None:
        workflow = _load_yaml(REPO / ".github" / "workflows" / "publish-image.yml")
        matrix = workflow["jobs"]["build"]["strategy"]["matrix"]["profile"]
        assert sorted(matrix) == sorted(_descriptor_profiles())


class TestPackageLocation:
    def test_package_location_pins_current_release(self) -> None:
        version = _project_version()
        component = _descriptor()["deploymentProfiles"][0]["components"][0]
        location = component["properties"]["packageLocation"]
        expected = (
            "https://github.com/industrial-aiops/industrial-aiops/releases/download/"
            f"v{version}/iaiops-margo-package-{version}.tar.gz"
        )
        assert location == expected

    def test_key_location_points_at_committed_public_key(self) -> None:
        component = _descriptor()["deploymentProfiles"][0]["components"][0]
        key_location = component["properties"]["keyLocation"]
        assert key_location.endswith("/main/deploy/margo/cosign.pub")
        pub = MARGO_DIR / "cosign.pub"
        assert pub.exists(), "deploy/margo/cosign.pub must be committed (keyLocation target)"
        assert "BEGIN PUBLIC KEY" in pub.read_text(encoding="utf-8")


class TestPackagedCompose:
    def _service(self) -> dict[str, Any]:
        return _load_yaml(MARGO_DIR / "package.compose.yaml")["services"]["iaiops"]

    def test_references_published_pinned_image(self) -> None:
        expected = (
            f"ghcr.io/industrial-aiops/iaiops:{_project_version()}" + "-${IAIOPS_MCP:-factory}"
        )
        assert self._service()["image"] == expected

    def test_has_no_build_section(self) -> None:
        # The package deploys on hosts with no source tree — it must never try to build.
        assert "build" not in self._service()

    def test_keeps_hardened_posture(self) -> None:
        service = self._service()
        assert service["read_only"] is True
        assert service["cap_drop"] == ["ALL"]
        assert service["security_opt"] == ["no-new-privileges:true"]
        assert service["user"] == "10001:10001"

    def test_parameter_pointers_are_wired(self) -> None:
        environment = self._service()["environment"]
        pointers = {
            target["pointer"]
            for param in _descriptor()["parameters"].values()
            for target in param["targets"]
        }
        missing = pointers - set(environment)
        assert not missing, f"descriptor parameters not wired in package compose env: {missing}"
