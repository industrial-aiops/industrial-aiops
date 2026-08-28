"""One version, everywhere it is written down.

A release bumps a number in a dozen files, and the ones nobody guards are the
ones that get left behind. Historically that has been `server.json` (the publish
workflow validates only line 10, not the second occurrence on line 15),
`uv.lock`, and both READMEs' `cosign verify` lines — every one of which a
customer reads or a tool consumes.

Two failure modes, both real:

* **Stale** — a file still names the previous release. The README then tells a
  customer to `cosign verify` an image tag that the release did not produce.
* **Coincidental** — a THIRD-PARTY version that happens to equal ours. `uv.lock`
  pins `thrift 0.23.0`; a blind find-and-replace during the 0.24.0 bump would
  have pinned a thrift release that does not exist. So this checks *our* strings,
  named individually, rather than sweeping for a number.
"""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit


def _root() -> Path:
    return Path(__file__).resolve().parents[1]


def _version() -> str:
    with (_root() / "pyproject.toml").open("rb") as handle:
        return tomllib.load(handle)["project"]["version"]


#: Files that name the version in prose or config, and how to find every mention.
#: `uv.lock` is deliberately absent from this sweep — see `test_uv_lock_*` below,
#: which pins the iaiops block only.
_IMAGE_TAG = re.compile(r"ghcr\.io/industrial-aiops/iaiops:(\d+\.\d+\.\d+)")

_TAGGED_FILES = (
    "README.md",
    "README.zh-CN.md",
    "deploy/airgap/compose.yaml",
    "deploy/margo/package.compose.yaml",
    "deploy/siemens-ie/README.md",
    "deploy/siemens-ie/SUBMISSION.md",
    "deploy/siemens-ie/docker-compose.yaml",
)


@pytest.mark.parametrize("name", _TAGGED_FILES)
def test_every_image_tag_matches_the_project_version(name):
    """A stale tag in a README is an instruction to verify an image that the
    release never built."""
    text = (_root() / name).read_text("utf-8")
    stale = sorted({v for v in _IMAGE_TAG.findall(text) if v != _version()})
    assert not stale, f"{name} still names iaiops {', '.join(stale)}; project is {_version()}"


def test_server_json_agrees_everywhere_it_says_a_version():
    """BOTH occurrences. The publish workflow validates line 10 only, so the
    second one has no other guard at all."""
    data = json.loads((_root() / "server.json").read_text("utf-8"))
    found = {data["version"]} | {p["version"] for p in data.get("packages", []) if "version" in p}
    assert found == {_version()}, found


def test_the_uv_lock_pins_this_version_of_iaiops():
    text = (_root() / "uv.lock").read_text("utf-8")
    match = re.search(r'\[\[package\]\]\nname = "iaiops"\nversion = "([^"]+)"', text)
    assert match, "no iaiops package block in uv.lock"
    assert match.group(1) == _version()


def test_a_coincidental_third_party_version_is_not_swept_along():
    """The complement, and the reason this file checks named strings instead of
    grepping for a number: `thrift` was 0.23.0 at the same time we were, and a
    blind replace would have pinned a thrift release that does not exist."""
    text = (_root() / "uv.lock").read_text("utf-8")
    assert "thrift-0.23.0.tar.gz" in text, "the thrift pin was rewritten by a version bump"


def test_the_margo_descriptor_and_its_package_url_agree():
    """Two places: the descriptor's own `version:` and the release URL it points
    at. Matched by their surrounding text rather than by "anything dotted" — the
    first version of this test flagged `127.0.0.1/32`, an ALLOWED-CALLER CIDR, as
    a stale release. A guard that cries wolf stops being read."""
    text = (_root() / "deploy/margo/margo.yaml").read_text("utf-8")
    declared = re.findall(r'^\s*version:\s*"([^"]+)"', text, re.MULTILINE)
    in_url = re.findall(r"/download/v(\d+\.\d+\.\d+)/iaiops-margo-package-(\d+\.\d+\.\d+)", text)
    assert declared, "margo.yaml declares no version"
    assert in_url, "margo.yaml has no package download URL"
    found = set(declared) | {v for pair in in_url for v in pair}
    assert found == {_version()}, f"margo.yaml names {sorted(found)}; project is {_version()}"


def test_the_changelog_has_a_section_for_this_version():
    """A release with no notes is one nobody can review, and `## Unreleased`
    left open at tag time is how a version ships with its notes still filed
    under the next one."""
    text = (_root() / "CHANGELOG.md").read_text("utf-8")
    assert re.search(
        rf"^## {re.escape(_version())} — \d{{4}}-\d{{2}}-\d{{2}}", text, re.MULTILINE
    ), f"CHANGELOG.md has no `## {_version()} — <date>` heading"
