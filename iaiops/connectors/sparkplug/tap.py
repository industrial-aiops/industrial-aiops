"""MQTT / Sparkplug B as a data SOURCE — the tap a UNS site needs.

Every other protocol here is POLLED: ask the device, get an answer or an error.
MQTT is PUSHED. That one difference is the whole design, because the obvious
implementation — keep the last value each topic sent, hand it back when asked —
fails in the direction this repo keeps having to unlearn:

    A publisher dies. Nothing arrives. The cache keeps answering with the last
    value it ever saw. Availability reads 100% on a line that stopped, forever,
    and every consumer of that number agrees with every other one.

That is the same shape as an MTConnect agent reporting its own ``Agent`` device
as AVAILABLE whenever it is answering, and it is worse here: a UNS is subscribed
to by many consumers at once, so one stale cache is wrong in several systems
simultaneously and each looks independently confirmed.

So this module refuses more than it answers. A point is a reading only when:

1. **It has been seen at all.** Never-published is not zero and not null.
2. **It is fresh**, against ``stale_after_s`` — which the SITE must declare (see
   below). Older than that and it is :class:`OTNoReadingError`, which the collector
   records as a gap: a window where collection was blind, never as downtime.
3. **Its publisher is alive**, where the protocol lets us know. Sparkplug's
   NDEATH/DDEATH (the broker's Last-Will) and the primary-host STATE topic are a
   real liveness signal, and a dead node's metrics stop being readings the moment
   the will fires — cache or no cache.

**The two guarantees are not the same, and the endpoint must say which it has.**
Sparkplug gives staleness AND death. Plain MQTT gives staleness only: there is no
death signal in the protocol, so a quiet topic and a dead publisher are
indistinguishable and this module says so rather than implying it noticed.

**Why ``stale_after_s`` has no default.** A value that stopped updating and a
value that is simply constant are identical on the wire — a tank level that has
not moved in an hour publishes exactly like a gateway that died an hour ago. Only
the site knows how often a point is meant to be published. Guessing it here would
put a guess underneath every availability figure the product later reports, which
is the same reason ``run_state`` refuses to default ``running_when``. So it is
required, and collection from an MQTT endpoint refuses without it.

Read-only: this module subscribes and decodes. It publishes nothing.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from iaiops.core.brain._shared import s
from iaiops.core.runtime.session_factory import OTConnectionError, OTNoReadingError

#: Separates the Sparkplug node from the metric inside one ``ref``:
#: ``group/edge[/device]:metric``. The node half is exactly what
#: ``sparkplug_live_schema`` reports, so a point list from there is usable as
#: config refs without translation.
REF_SEP = ":"

#: A plain-MQTT ref is the topic itself, and its payload is whatever the
#: publisher sent. JSON objects are looked up by this key when present, so a
#: ``{"value": 12.5, "ts": ...}`` payload — the commonest UNS envelope — reads as
#: 12.5 rather than as a dict nothing downstream can chart.
JSON_VALUE_KEYS = ("value", "v", "val")

#: Epoch bounds a plant timestamp must fall inside (2001-09-09 .. 2065). Outside
#: them the number is not a time — a counter, an id — and inventing a date from it
#: would be worse than having none.
_EPOCH_FLOOR_S, _EPOCH_CEIL_S = 1_000_000_000, 3_000_000_000

MAX_CACHED_POINTS = 20000


@dataclass(frozen=True)
class _Reading:
    """One observed publish. ``received_at`` is monotonic — wall-clock moving
    under us must not turn a fresh point stale or a stale point fresh."""

    value: Any
    source_ts: str
    received_at: float
    #: Wall-clock arrival of THIS publish. Used as the observation time when the
    #: payload states none, so re-reading the cache cannot look like a new
    #: observation: 96 rows once held 20 publishes, and every analysis downstream
    #: read the poller's rate as the data's rate.
    arrived_iso: str = ""


class UnsTap:
    """A live subscription with a last-value cache that knows when to refuse.

    Built once per collection run and held open (``session_read``), because the
    alternative — connect, subscribe, wait, disconnect, per point per tick — is
    both slower and less honest: it can only ever see what arrives inside its own
    short window, so a point published every 30s would read as permanently
    missing at a 5s interval.
    """

    def __init__(self, client: Any, target: Any) -> None:
        self._client = client
        self._lock = threading.Lock()
        self._points: dict[str, _Reading] = {}
        #: Sparkplug node id → why it is not alive (empty string = alive).
        self._dead: dict[str, str] = {}
        #: Sparkplug node id → {alias: name}, learned from that node's BIRTH.
        #: Without it every NDATA is dropped and the BIRTH values are served as
        #: current forever — see :meth:`_record_sparkplug`.
        self._aliases: dict[str, dict[int, str]] = {}
        self.endpoint = str(getattr(target, "name", ""))
        self.stale_after_s = float(getattr(target, "stale_after_s", 0.0) or 0.0)
        if self.stale_after_s <= 0:
            raise OTConnectionError(
                f"MQTT endpoint '{self.endpoint}' has no `stale_after_s`, so there "
                "is no way to tell a point that STOPPED updating from one that is "
                "simply constant — they look identical on the wire. Without it the "
                "last value would be served forever after a publisher dies and "
                "availability would read 100% on a stopped line. Set "
                "`stale_after_s:` on the endpoint to a little longer than the "
                "slowest point's publish interval.",
                endpoint=self.endpoint,
                protocol="mqtt",
            )

    # --- subscription side ------------------------------------------------

    def on_message(self, topic: str, payload: bytes) -> None:
        """Record one publish. Never raises — a bad payload is one lost point."""
        try:
            self._record(topic, payload)
        except Exception:  # noqa: BLE001 — one odd publisher must not end a run
            return

    def _record(self, topic: str, payload: bytes) -> None:
        from iaiops.connectors.sparkplug import ops

        parsed = ops._parse_sparkplug_topic(topic)
        if parsed:
            self._record_sparkplug(parsed, payload)
            return
        value, ts = _plain_value(payload)
        self._put(s(topic, 200), value, ts)

    def _record_sparkplug(self, parsed: dict, payload: bytes) -> None:
        from iaiops.connectors.sparkplug import ops

        kind = str(parsed.get("message_type", "")).upper()
        node = f"{parsed['group_id']}/{parsed['edge_node_id']}"
        if parsed.get("device_id"):
            node = f"{node}/{parsed['device_id']}"

        if kind in ("NDEATH", "DDEATH"):
            # The broker published the node's Last Will: it is gone. Every metric
            # under it stops being a reading NOW, which is the whole reason
            # Sparkplug is a stronger guarantee than plain MQTT.
            with self._lock:
                self._dead[node] = f"{kind} received — the broker published this node's Last Will"
            return
        if kind in ("NBIRTH", "DBIRTH"):
            with self._lock:
                self._dead.pop(node, None)

        # Resolve aliases. A real EoN node names its metrics ONCE, in the BIRTH,
        # and every NDATA afterwards carries the alias alone — so decoding
        # without the map leaves `name` empty on every update, the loop below
        # skips them all, and the cache keeps serving the BIRTH values.
        #
        # That failure is invisible to a synthetic test that always sends names,
        # and it defeats this module's whole point rather than merely losing
        # data: the periodic re-BIRTH keeps refreshing `received_at`, so the
        # stale BIRTH value passes the freshness check and reads as a live one.
        # Caught against a spec-correct edge node on the lab network, where a
        # counter sitting at 200 read as 0 and looked perfectly fresh.
        if kind in ("NBIRTH", "DBIRTH"):
            with self._lock:
                if kind == "NBIRTH":
                    # The spec restarts a node's aliases at NBIRTH; keeping the
                    # old map would resolve a reused alias to the wrong metric.
                    self._aliases[node] = {}
                self._aliases.setdefault(node, {}).update(_alias_map(payload))
                # A BIRTH carries the node's FULL metric state, so it REPLACES
                # what we hold rather than adding to it. Without this a metric
                # the node has REMOVED keeps being served from cache as a
                # current reading — the same reason `sparkplug_live_schema`
                # rebuilds its schema from scratch on every BIRTH instead of
                # unioning, so that a removal cannot hide a real schema drift.
                # The BIRTH being processed repopulates everything still there.
                self._forget_locked(node, whole_node=kind == "NBIRTH")
        with self._lock:
            alias_map = dict(self._aliases.get(node) or {})

        decoded = ops.decode_sparkplug_payload(payload, alias_map)
        if decoded.get("encoding") != "sparkplug_b":
            return
        for metric in decoded.get("metrics") or ():
            name = str(metric.get("name") or "")
            if not name:
                continue
            self._put(
                f"{node}{REF_SEP}{s(name, 96)}",
                metric.get("value"),
                _iso_ts(metric.get("timestamp")),
            )

    def _forget_locked(self, node: str, *, whole_node: bool) -> None:
        """Drop cached points for ``node``. Caller holds the lock.

        ``whole_node`` also drops its DEVICES' points: an NBIRTH restarts the
        edge node, and every device beneath it is re-announced by its own DBIRTH.
        """
        prefixes = [f"{node}{REF_SEP}"] + ([f"{node}/"] if whole_node else [])
        for ref in [r for r in self._points if any(r.startswith(p) for p in prefixes)]:
            del self._points[ref]

    def _put(self, ref: str, value: Any, source_ts: str) -> None:
        with self._lock:
            if ref not in self._points and len(self._points) >= MAX_CACHED_POINTS:
                return
            self._points[ref] = _Reading(
                value, source_ts, time.monotonic(), datetime.now(UTC).isoformat()
            )

    # --- read side --------------------------------------------------------

    def read(self, ref: str) -> tuple[Any, str]:
        """The current value of ``ref``, or refuse. Never returns a stale value."""
        wanted = str(ref or "").strip()
        if not wanted:
            raise OTNoReadingError("An MQTT ref is required (a topic, or node:metric).")
        node = wanted.split(REF_SEP)[0] if REF_SEP in wanted else ""
        with self._lock:
            dead = self._dead.get(node, "")
            point = self._points.get(wanted)
            known = len(self._points)

        if dead:
            raise OTNoReadingError(
                f"{wanted!r} belongs to Sparkplug node {node!r}, which is DEAD: "
                f"{dead}. Its last value is still in the cache and is deliberately "
                "not returned — serving it is how a stopped line reads as running.",
                endpoint=self.endpoint,
                protocol="mqtt",
            )
        if point is None:
            raise OTNoReadingError(
                f"Nothing has been published on {wanted!r} since this run "
                f"subscribed ({known} other point(s) have arrived). Never-published "
                "is not zero. Check the ref against `iaiops mqtt live-schema` "
                "(Sparkplug) or `iaiops mqtt browse` (plain MQTT).",
                endpoint=self.endpoint,
                protocol="mqtt",
            )
        age = time.monotonic() - point.received_at
        if age > self.stale_after_s:
            raise OTNoReadingError(
                f"{wanted!r} was last published {age:.1f}s ago, past this "
                f"endpoint's stale_after_s of {self.stale_after_s:.1f}s. Returning "
                "the cached value would be indistinguishable from a live reading.",
                endpoint=self.endpoint,
                protocol="mqtt",
            )
        return point.value, point.source_ts or point.arrived_iso


def _iso_ts(raw: Any) -> str:
    """A device timestamp as ISO-8601 text, or "" when it is not a time.

    Sparkplug states timestamps as epoch MILLISECONDS (spec §6.4.1), and the
    commonest JSON envelope states `ts` in epoch seconds or milliseconds. Passed
    through as text, those reach the store as `1789521121683` — which sorts and
    filters only among themselves: `oee measure` found 0 usable samples in a store
    holding 74, `export --since` returned nothing, and `store prune` offered to
    delete minutes-old rows because "1789…" is lexically less than "2026-…".
    Reproduced against a real mosquitto broker on the lab network.
    """
    if isinstance(raw, bool) or raw is None:
        return ""
    text = str(raw).strip()
    if not text:
        return ""
    try:
        number = float(text)
    except ValueError:
        try:  # already a stated date?
            return datetime.fromisoformat(text.replace("Z", "+00:00")).isoformat()
        except ValueError:
            return ""
    seconds = number / 1000.0 if number >= _EPOCH_FLOOR_S * 1000 else number
    if not _EPOCH_FLOOR_S <= seconds <= _EPOCH_CEIL_S:
        return ""
    return datetime.fromtimestamp(seconds, UTC).isoformat()


def _alias_map(payload: bytes) -> dict[int, str]:
    """alias→name from a BIRTH payload, via the connector's own learner.

    Delegated rather than re-derived: ``_SparkplugModel`` has resolved aliases
    correctly all along, and a second implementation here is how the two would
    drift on the next spec detail.
    """
    from iaiops.connectors.sparkplug import ops

    node: dict[str, Any] = {"alias_map": {}}
    ops._SparkplugModel._learn_aliases(ops._SparkplugModel(), node, payload)
    return dict(node["alias_map"])


def _plain_value(payload: bytes) -> tuple[Any, str]:
    """Decode a plain-MQTT payload: a bare scalar, or a JSON envelope.

    A payload we cannot read is returned as text rather than guessed at — the
    collector marks non-numeric values as such and nothing downstream charts them.
    """
    try:
        text = payload.decode("utf-8").strip()
    except UnicodeDecodeError:
        return None, ""
    if not text:
        return None, ""
    if text[:1] in "{[":
        try:
            doc = json.loads(text)
        except ValueError:
            return text[:200], ""
        if isinstance(doc, dict):
            for key in JSON_VALUE_KEYS:
                if key in doc:
                    return doc[key], _iso_ts(doc.get("timestamp") or doc.get("ts"))
            return text[:200], ""
        return text[:200], ""
    for cast in (int, float):
        try:
            return cast(text), ""
        except ValueError:
            continue
    return text[:200], ""


__all__ = ["REF_SEP", "UnsTap"]
