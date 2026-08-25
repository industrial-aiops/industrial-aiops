"""The Siemens Industrial Edge bundle must not name a version we did not release.

`deploy/margo/` has had a version guard since it was written, and `deploy/siemens-ie/`
did not — so when 0.23.0 shipped, the Industrial Edge README, the submission form
and the compose file were still pinned to **0.22.0** in six places, including the
`cosign verify` command a reviewer would paste and the "Version" row of the
submission itself.

It survived because the bundle sat on an **unmerged branch** while the release
bumped everything on `main`: a version sweep cannot reach a branch it cannot see,
and the only thing that would have caught it on merge is a test. This is that test.

The stakes are not cosmetic. This directory is a **submission to a third party**.
An image tag that resolves to nothing, or a signature command that verifies the
wrong artifact, is a reviewer's first impression of whether this project knows
what it published.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[1]
IE_DIR = REPO / "deploy" / "siemens-ie"

#: Every file in the bundle that can name a version.
BUNDLE = ("README.md", "SUBMISSION.md", "docker-compose.yaml")

#: `x.y.z`, optionally as an image tag suffix. Deliberately broad — the point is to
#: find a version ANYWHERE in these files, not only where one is expected — but not
#: so broad that it reads `127.0.0` out of `127.0.0.1`, which the first version did.
#: The lookarounds refuse a match that is part of a longer dotted run.
_VERSION = re.compile(r"(?<![\d.])(\d+\.\d+\.\d+)(?![\d.])")


def _project_version() -> str:
    with (REPO / "pyproject.toml").open("rb") as fh:
        return tomllib.load(fh)["project"]["version"]


def _text(name: str) -> str:
    return (IE_DIR / name).read_text(encoding="utf-8")


@pytest.mark.skipif(not IE_DIR.exists(), reason="the Industrial Edge bundle is not present")
class TestTheBundleNamesTheVersionWeShipped:
    @pytest.mark.parametrize("name", BUNDLE)
    def test_the_file_exists(self, name):
        assert (IE_DIR / name).is_file()

    @pytest.mark.parametrize("name", BUNDLE)
    def test_every_version_it_names_is_the_project_version(self, name):
        """Not "the version appears somewhere" — EVERY version-looking string must
        match. A file that mentioned 0.23.0 once and 0.22.0 five times would pass
        the weaker check, which is roughly what happened."""
        want = _project_version()
        found = {v for v in _VERSION.findall(_text(name)) if not v.startswith("0.0.")}
        stale = found - {want}
        assert not stale, f"{name} names {sorted(stale)}, but the project is at {want}"

    def test_the_compose_pins_a_published_image_tag(self):
        """An unpinned or `latest` tag makes the submitted artifact unreproducible —
        the reviewer and the author would be looking at different bytes."""
        compose = _text("docker-compose.yaml")
        assert f"ghcr.io/industrial-aiops/iaiops:{_project_version()}-" in compose
        assert ":latest" not in compose

    def test_the_verify_command_points_at_the_same_image(self):
        """A `cosign verify` line naming a different tag than the compose pulls is
        worse than none: it reads as proof while proving something else."""
        version = _project_version()
        for name in ("README.md", "docker-compose.yaml"):
            body = _text(name)
            if "cosign verify" not in body:
                continue
            for line in body.splitlines():
                if "cosign verify" in line and "iaiops:" in line:
                    assert f"iaiops:{version}-" in line, f"{name}: {line.strip()}"

    def test_it_names_a_real_edition_profile(self):
        """A tag suffix that is not a built profile resolves to nothing at all."""
        from mcp_server.profiles import NAMED_PROFILES

        tags = re.findall(r"iaiops:\d+\.\d+\.\d+-([a-z0-9]+)", _text("docker-compose.yaml"))
        assert tags, "the compose names no image tag"
        for tag in tags:
            assert tag in NAMED_PROFILES, f"{tag!r} is not a profile in NAMED_PROFILES"

    def test_the_guard_can_actually_see_a_stale_version(self):
        """The guard's own smoke test. A version regex that matched nothing would
        make every assertion above vacuously true — which is the failure mode of a
        check written to protect against a mistake already made."""
        stale = "Pull ghcr.io/industrial-aiops/iaiops:0.1.0-factory and verify it."
        found = {v for v in _VERSION.findall(stale) if not v.startswith("0.0.")}
        assert found == {"0.1.0"}

    def test_the_guard_does_not_read_a_version_out_of_an_ip_address(self):
        """The complement, and not hypothetical: the first version of this regex
        flagged `127.0.0` out of the compose's `127.0.0.1` bind and would have been
        "fixed" by loosening the assertion instead of the pattern."""
        assert _VERSION.findall("ports: 127.0.0.1:8080 and 10.0.0.1") == []
