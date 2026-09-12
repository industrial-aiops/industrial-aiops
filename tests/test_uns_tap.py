"""MQTT/Sparkplug as a data SOURCE — and the refusals that make it honest.

Every other protocol here is polled; MQTT is pushed, and the obvious last-value
cache fails in one specific direction: a publisher dies, nothing arrives, the
cache keeps answering, and availability reads 100% on a line that stopped. A UNS
makes that worse than usual because many consumers subscribe at once, so one
stale cache is wrong in several systems simultaneously and each looks
independently confirmed.

So what is tested here is mostly what the tap REFUSES to return, and that each
refusal reaches the collector as a GAP (collection was blind) rather than as a
reading or as a torn-down connection.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import pytest

from iaiops.connectors.sparkplug.tap import REF_SEP, UnsTap, _plain_value
from iaiops.core.runtime.session_factory import OTConnectionError, OTNoReadingError

pytestmark = pytest.mark.unit


@dataclass
class _Target:
    name: str = "uns-1"
    protocol: str = "mqtt"
    stale_after_s: float = 30.0
    topic: str = "#"
    timeout_s: float = 5.0
    tags: tuple = field(default_factory=tuple)


def _tap(**kw):
    return UnsTap(client=object(), target=_Target(**kw))


class TestItRefusesToInventAReading:
    def test_a_point_never_published_is_not_zero(self):
        tap = _tap()
        with pytest.raises(OTNoReadingError, match="Nothing has been published"):
            tap.read("plant/line1/temp")

    def test_a_stale_point_is_refused_not_served_from_cache(self):
        """The whole feature. Serving the cache here is how a stopped line reads
        as running, and every subscriber agrees with every other one."""
        tap = _tap(stale_after_s=0.05)
        tap.on_message("plant/line1/temp", b"42.5")
        assert tap.read("plant/line1/temp")[0] == 42.5
        time.sleep(0.08)
        with pytest.raises(OTNoReadingError, match="stale_after_s"):
            tap.read("plant/line1/temp")

    def test_the_refusal_is_a_connection_subclass_so_existing_handlers_keep_working(self):
        assert issubclass(OTNoReadingError, OTConnectionError)

    def test_an_endpoint_without_stale_after_s_refuses_to_build_at_all(self):
        """No default is possible: a value that STOPPED updating and one that is
        simply constant are identical on the wire. Guessing would put the guess
        underneath every availability figure the product later reports."""
        with pytest.raises(OTConnectionError, match="no `stale_after_s`"):
            _tap(stale_after_s=0)


class TestSparkplugDeathIsTheStrongerGuarantee:
    def _birth(self, tap, metrics):
        from iaiops.connectors.sparkplug import ops

        payload = _encode(metrics)
        tap.on_message("spBv1.0/g1/NBIRTH/edge1", payload)
        assert ops  # the decoder is what we are exercising

    def test_a_dead_node_stops_being_a_reading_immediately(self):
        """NDEATH is the broker publishing the node's Last Will. The cached value
        is still there and is deliberately not returned."""
        tap = _tap(stale_after_s=300)
        tap.on_message("spBv1.0/g1/NBIRTH/edge1", _encode([("Run", 1)]))
        ref = f"g1/edge1{REF_SEP}Run"
        assert tap.read(ref)[0] == 1
        tap.on_message("spBv1.0/g1/NDEATH/edge1", b"")
        with pytest.raises(OTNoReadingError, match="DEAD"):
            tap.read(ref)

    def test_a_rebirth_makes_it_a_reading_again(self):
        tap = _tap(stale_after_s=300)
        tap.on_message("spBv1.0/g1/NBIRTH/edge1", _encode([("Run", 1)]))
        tap.on_message("spBv1.0/g1/NDEATH/edge1", b"")
        tap.on_message("spBv1.0/g1/NBIRTH/edge1", _encode([("Run", 0)]))
        assert tap.read(f"g1/edge1{REF_SEP}Run")[0] == 0

    def test_plain_mqtt_has_no_death_signal_and_the_module_says_so(self):
        """Not a gap in the implementation — a gap in the protocol. The docstring
        must keep saying which of the two guarantees an endpoint gets, because a
        reader who assumes the stronger one will trust a quiet topic."""
        import iaiops.connectors.sparkplug.tap as tap_mod

        doc = " ".join((tap_mod.__doc__ or "").split())  # the docstring wraps
        assert "no death signal in the protocol" in doc
        assert "staleness only" in doc


class TestPayloadDecoding:
    @pytest.mark.parametrize(
        ("payload", "expected"),
        [
            (b"42", 42),
            (b"42.5", 42.5),
            (b'{"value": 12.5}', 12.5),
            (b'{"v": 3}', 3),
            (b"RUNNING", "RUNNING"),
        ],
    )
    def test_common_uns_payload_shapes(self, payload, expected):
        assert _plain_value(payload)[0] == expected

    def test_an_undecodable_payload_is_not_a_number(self):
        assert _plain_value(b"\xff\xfe\x00")[0] is None

    def test_a_json_envelope_without_a_value_key_is_not_guessed_at(self):
        value, _ = _plain_value(b'{"temperature": 12.5}')
        assert value != 12.5, "picking the only number in an unknown envelope is a guess"


class TestItReachesTheCollectorAsAGap:
    def test_a_stale_point_becomes_a_gap_and_does_not_tear_down_the_session(self):
        """A stale point is not a connection fault. Tearing the session down here
        would drop the live subscription and its cache every time one slow metric
        went quiet, and `break` would skip every remaining ref in the same tick.
        """
        from iaiops.core.collect import runner as runner_mod

        src = runner_mod.__file__ or ""
        text = open(src).read()
        assert "except OTNoReadingError as exc:" in text
        head = text.index("except OTNoReadingError as exc:")
        tail = text.index("except Exception as exc:", head)
        # Executable lines only — the branch's own comment explains what it must
        # NOT do, and matching that prose would pass for the wrong reason.
        code = [
            line.split("#", 1)[0].strip()
            for line in text[head:tail].splitlines()
            if line.split("#", 1)[0].strip()
        ]
        branch = " ".join(code)
        assert "tracker.failure" in branch, "a refused read is still a gap"
        assert "_close()" not in branch, "a healthy subscription must not be torn down"
        assert "break" not in branch, "the other refs in this tick must still be read"


def _encode(metrics):
    """A real Sparkplug B payload, via the vendored protobuf the product ships."""
    from iaiops.connectors.sparkplug import sparkplug_b_pb2 as pb

    payload = pb.Payload()
    payload.timestamp = int(time.time() * 1000)
    for name, value in metrics:
        m = payload.metrics.add()
        m.name = name
        m.timestamp = payload.timestamp
        m.datatype = 3  # Int32
        m.int_value = int(value)
    return payload.SerializeToString()


class TestTheRegistryKeepsBothReadPaths:
    """Losing `session_read` is silent and expensive, so it gets its own guard.

    `can_collect` keys off `monitor_read` alone, so dropping `session_read` leaves
    MQTT looking collectable while collection quietly falls back to
    reconnect-per-read: a broker connection opened per point per tick, each able
    to see only what lands inside its own short window. A point published every
    30s would then read as permanently missing at a 5s interval — a regression
    that no live test and no `can_collect` assertion would notice.
    """

    def test_mqtt_registers_a_session_read(self):
        from iaiops.core.runtime.capabilities import UNSUPPORTED, get_capabilities

        cap = get_capabilities("mqtt")
        assert cap.session_read is not UNSUPPORTED
        assert cap.session_builder is not UNSUPPORTED

    def test_mqtt_registers_a_one_shot_read_so_can_collect_is_true(self):
        from iaiops.core.collect.reader import can_collect
        from iaiops.core.runtime.capabilities import UNSUPPORTED, get_capabilities

        assert get_capabilities("mqtt").monitor_read is not UNSUPPORTED
        assert can_collect("mqtt")

    def test_the_session_builder_is_the_subscribing_one(self):
        """`mqtt_session` yields a bare connected client with no subscription and
        no cache; reading from it would answer nothing, forever."""
        from iaiops.core.runtime.capabilities import get_capabilities

        # `_session(attr)` late-binds by NAME, so the closure is what records
        # which session MQTT collection opens.
        builder = get_capabilities("mqtt").session_builder
        bound = {
            cell.cell_contents
            for cell in (builder.__closure__ or ())
            if isinstance(cell.cell_contents, str)
        }
        assert "mqtt_tap_session" in bound, bound


class TestAliasOnlyNdataIsResolved:
    """A real EoN node names each metric ONCE, in the BIRTH, and every NDATA
    afterwards carries the alias alone.

    Decoding NDATA without the alias map leaves `name` empty, every update is
    skipped, and the cache keeps serving the BIRTH values — and because a node
    re-BIRTHs periodically, that stale value keeps passing the freshness check
    and reads as live. A counter actually sitting at 200 read as 0 and looked
    perfectly fresh.

    Every other test in this file sends names on every message, which is what
    hid it. Found against a spec-correct edge node on the lab network.
    """

    def _birth(self, aliases):
        from iaiops.connectors.sparkplug import sparkplug_b_pb2 as pb

        p = pb.Payload()
        p.timestamp = 1
        for name, alias in aliases.items():
            m = p.metrics.add()
            m.name = name
            m.alias = alias
            m.timestamp = 1
            m.datatype = 3
            m.int_value = 0
        return p.SerializeToString()

    def _data(self, values, aliases):
        from iaiops.connectors.sparkplug import sparkplug_b_pb2 as pb

        p = pb.Payload()
        p.timestamp = 2
        for name, value in values:
            m = p.metrics.add()
            m.alias = aliases[name]  # alias ONLY — no name, exactly as the spec has it
            m.timestamp = 2
            m.datatype = 3
            m.int_value = int(value)
        return p.SerializeToString()

    def test_a_counter_sent_by_alias_reaches_the_reader(self):
        aliases = {"Run": 1, "Good": 2}
        tap = _tap(stale_after_s=300)
        tap.on_message("spBv1.0/g/NBIRTH/e", self._birth(aliases))
        tap.on_message("spBv1.0/g/NDATA/e", self._data([("Good", 200)], aliases))
        value, _ = tap.read(f"g/e{REF_SEP}Good")
        assert value == 200, "alias-only NDATA was dropped and the BIRTH value served"

    def test_the_birth_value_is_not_served_as_current_after_an_update(self):
        """The shape that made this dangerous rather than merely lossy."""
        aliases = {"Good": 2}
        tap = _tap(stale_after_s=300)
        tap.on_message("spBv1.0/g/NBIRTH/e", self._birth(aliases))
        assert tap.read(f"g/e{REF_SEP}Good")[0] == 0
        tap.on_message("spBv1.0/g/NDATA/e", self._data([("Good", 200)], aliases))
        assert tap.read(f"g/e{REF_SEP}Good")[0] != 0

    def test_a_rebirth_resets_the_alias_map_rather_than_merging_it(self):
        """The spec restarts a node's aliases at NBIRTH. Keeping the old map
        would resolve a reused alias to the metric it used to mean."""
        tap = _tap(stale_after_s=300)
        tap.on_message("spBv1.0/g/NBIRTH/e", self._birth({"Old": 1}))
        tap.on_message("spBv1.0/g/NBIRTH/e", self._birth({"New": 1}))
        tap.on_message("spBv1.0/g/NDATA/e", self._data([("New", 7)], {"New": 1}))
        assert tap.read(f"g/e{REF_SEP}New")[0] == 7
        with pytest.raises(OTNoReadingError):
            tap.read(f"g/e{REF_SEP}Old")

    def test_an_alias_dropped_by_a_rebirth_stops_resolving(self):
        """The alias RESET, isolated from the cache drop.

        BIRTH1 declares two metrics; BIRTH2 declares only one. Merging the maps
        would leave alias 2 pointing at a metric the node no longer has, so a
        later NDATA on that alias would be filed under a name that is gone.
        """
        aliases1 = {"Kept": 1, "Dropped": 2}
        tap = _tap(stale_after_s=300)
        tap.on_message("spBv1.0/g/NBIRTH/e", self._birth(aliases1))
        tap.on_message("spBv1.0/g/NBIRTH/e", self._birth({"Kept": 1}))
        tap.on_message("spBv1.0/g/NDATA/e", self._data([("Dropped", 5)], aliases1))
        with pytest.raises(OTNoReadingError):
            tap.read(f"g/e{REF_SEP}Dropped")

    def test_an_nbirth_also_forgets_the_nodes_devices(self):
        """An NBIRTH restarts the edge node, and every device beneath it is
        re-announced by its own DBIRTH. Keeping a device's points across it
        serves readings for a device that may not come back."""
        tap = _tap(stale_after_s=300)
        tap.on_message("spBv1.0/g/DBIRTH/e/d1", self._birth({"Temp": 1}))
        assert tap.read(f"g/e/d1{REF_SEP}Temp")[0] == 0
        tap.on_message("spBv1.0/g/NBIRTH/e", self._birth({"Run": 1}))
        with pytest.raises(OTNoReadingError):
            tap.read(f"g/e/d1{REF_SEP}Temp")
