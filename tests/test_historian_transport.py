"""A configured TDengine historian must be reachable without a vendor tarball.

`TDengineReader` supports three transports — native (`libtaos`), REST and
WebSocket (both served by taosAdapter on 6041) — but `HistorianConfig` could only
express reader/host/port/user/database. So `get_reader("tdengine", **opts)` always
took the default, `native`, and native needs `libtaos`: a vendor download that is
not on PyPI.

The effect on a real site: configure a TDengine historian, `pip install iaiops`,
and the RCA copilot answers

    The native TDengine client (libtaos) could not be loaded

for every incident — with nothing in the config able to say "use REST instead".
The capability was there and unreachable, which is the same as absent.

Found by configuring a real historian end to end against a live taosd, which is
the only place it could show: every unit test mocks the reader, and the live TSDB
tests construct the sink directly with `transport=` rather than going through
config.
"""

from __future__ import annotations

import pytest

from iaiops.core.runtime.config import HistorianConfig

pytestmark = pytest.mark.unit


class TestTheTransportIsExpressible:
    def test_a_historian_can_declare_rest(self):
        assert HistorianConfig(reader="tdengine", transport="rest").transport == "rest"

    def test_it_reaches_the_reader(self):
        opts = HistorianConfig(reader="tdengine", host="h", transport="rest").reader_opts()
        assert opts["transport"] == "rest"

    def test_the_default_is_unchanged_for_existing_configs(self):
        """Every config written before this stays byte-identical in behaviour."""
        assert "transport" not in HistorianConfig(reader="tdengine", host="h").reader_opts()

    def test_sqlite_does_not_carry_a_transport(self):
        """It has no wire at all; passing one would be noise the reader rejects."""
        opts = HistorianConfig(reader="sqlite", db_path="/tmp/x.db", transport="rest").reader_opts()
        assert "transport" not in opts

    @pytest.mark.parametrize("transport", ["native", "rest", "ws", "websocket", "taosrest"])
    def test_the_accepted_transports_match_the_connector(self, transport):
        assert HistorianConfig(reader="tdengine", transport=transport).transport

    def test_an_unknown_transport_is_refused_with_the_list(self):
        """A typo must not silently fall back to native and then fail at the
        first incident with a message about a missing C library."""
        with pytest.raises(ValueError) as excinfo:
            HistorianConfig(reader="tdengine", transport="htttp")
        message = str(excinfo.value)
        assert "rest" in message and "native" in message


class TestItParsesFromYaml:
    def test_a_transport_in_the_block_survives(self, tmp_path):
        from iaiops.core.runtime.config import load_config

        path = tmp_path / "config.yaml"
        path.write_text(
            "endpoints: []\n"
            "historian:\n"
            "  reader: tdengine\n"
            "  host: 10.0.0.5\n"
            "  port: 6041\n"
            "  database: iaiops\n"
            "  transport: rest\n",
            "utf-8",
        )
        path.chmod(0o600)
        config = load_config(path)
        assert config.historian.transport == "rest"
        assert config.historian.reader_opts()["transport"] == "rest"

    def test_a_block_without_one_still_loads(self, tmp_path):
        from iaiops.core.runtime.config import load_config

        path = tmp_path / "config.yaml"
        path.write_text(
            "endpoints: []\nhistorian:\n  reader: tdengine\n  host: 10.0.0.5\n", "utf-8"
        )
        path.chmod(0o600)
        assert load_config(path).historian.transport == ""
