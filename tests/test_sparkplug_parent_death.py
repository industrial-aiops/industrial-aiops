"""External Tahu payload regression; offline replay, not broker/TCK validation."""

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from iaiops.connectors.sparkplug.tap import UnsTap
from iaiops.core.runtime.session_factory import OTNoReadingError

DATA = Path(__file__).parent / "data/sparkplug-node-death"


def replay(tap, index):
    manifest = json.loads((DATA / "result.json").read_text())
    frame = manifest["frames"][index]
    data = (DATA / frame["file"]).read_bytes()
    assert hashlib.sha256(data).hexdigest() == frame["sha256"]
    tap.on_message(frame["topic"], data)


def test_parent_node_death_refuses_device_cache_and_preserves_other_nodes():
    target = SimpleNamespace(name="fixture", stale_after_s=300)
    tap = UnsTap(client=object(), target=target)
    replay(tap, 0)
    replay(tap, 1)
    assert tap.read("lab/node/device:Run")[0] == 1
    # An independent node must remain readable.
    for i in [0, 1]:
        manifest = json.loads((DATA / "result.json").read_text())
        frame = manifest["frames"][i]
        tap.on_message(
            frame["topic"].replace("/node", "/other"), (DATA / frame["file"]).read_bytes()
        )
    replay(tap, 2)
    with pytest.raises(OTNoReadingError, match="DEAD"):
        tap.read("lab/node/device:Run")
    assert tap.read("lab/other/device:Run")[0] == 1
    replay(tap, 1)  # Device BIRTH cannot make a dead parent live.
    with pytest.raises(OTNoReadingError, match="DEAD"):
        tap.read("lab/node/device:Run")
    replay(tap, 0)  # Parent BIRTH clears cached device points.
    with pytest.raises(OTNoReadingError):
        tap.read("lab/node/device:Run")
    replay(tap, 1)
    assert tap.read("lab/node/device:Run")[0] == 1
