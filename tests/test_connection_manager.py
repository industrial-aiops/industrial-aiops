"""ConnectionManager protocol-routing tests (no live devices).

``ConnectionManager.session`` must route each stateful protocol to its own
session builder and REFUSE protocols whose connectors are stateless/per-call
(bacnet/ethercat/profinet/hart/mtconnect) — never silently fall back to the
OPC UA session, whose guard would then produce the misleading error
"Endpoint 'x' is protocol 'bacnet', not opcua".
"""

from __future__ import annotations

import pytest

from iaiops.core.runtime.config import AppConfig, TargetConfig
from iaiops.core.runtime.connection import ConnectionManager, OTConnectionError


def _manager(*targets: TargetConfig) -> ConnectionManager:
    return ConnectionManager(AppConfig(targets=targets))


@pytest.mark.unit
def test_session_routes_mapped_protocols_to_their_builders():
    manager = _manager(
        TargetConfig(name="press1", protocol="s7", host="10.0.0.1"),
        TargetConfig(name="ua1", protocol="opcua", host="10.0.0.2"),
    )
    # Builders are context managers; obtaining one performs no I/O.
    assert manager.session("press1").__class__.__name__ == "_GeneratorContextManager"
    assert manager.session("ua1").__class__.__name__ == "_GeneratorContextManager"


@pytest.mark.unit
@pytest.mark.parametrize("protocol", ["bacnet", "ethercat", "profinet", "hart", "mtconnect"])
def test_session_rejects_stateless_protocols_with_teaching_error(protocol: str):
    manager = _manager(TargetConfig(name="ep1", protocol=protocol, host="10.0.0.5"))
    with pytest.raises(OTConnectionError, match="stateful session") as exc_info:
        manager.session("ep1")
    message = str(exc_info.value)
    assert protocol in message
    assert "not opcua" not in message  # the old misleading fallback error
    assert exc_info.value.endpoint == "ep1"
    assert exc_info.value.protocol == protocol
