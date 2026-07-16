"""MTConnect operations (royalty-free standard for ALL CNC machine tools).

MTConnect is a **read-only by specification** standard: a machine-tool *agent*
exposes a REST interface returning XML — ``/probe`` (the device model), ``/current``
(latest values), ``/sample`` (a bounded stream of observations), and ``/assets``.
This module speaks plain HTTP (``requests``) + ``xml.etree`` (no heavy SDK) and is
vendor-neutral across Fanuc / Siemens / Haas / Mazak / Okuma controllers that
ship an MTConnect agent.

The HTTP fetch is a module-level function (``_http_get``) so tests can inject a
static XML fixture without a live agent. All agent-returned text is sanitized.

Incremental streaming (``mtconnect_stream``) is done by **client-side polling**:
each round issues ``/sample?from=<seq>&count=<n>`` and advances by the Streams
header's ``nextSequence``, always bounded by ``max_samples`` / ``duration_s`` /
``MAX_STREAM_POLLS``. This is deliberately NOT the agent's server-push multipart
``interval`` mode (that holds the socket open indefinitely — unsuitable for a
request/response tool); ``interval_ms`` here is client-side poll spacing.
"""

from __future__ import annotations

import time
import xml.etree.ElementTree as ET  # noqa: N817 — conventional ET alias
from typing import Any

from iaiops.core.brain._shared import num, s

MAX_OBSERVATIONS = 500
DEFAULT_SAMPLE_COUNT = 100
MAX_SAMPLE_COUNT = 500
_HTTP_TIMEOUT_S = 10

# Bounds for the incremental long-poll stream (mtconnect_stream). Every one of
# these is a hard ceiling — the loop can NEVER run unbounded.
MAX_STREAM_SAMPLES = 2000  # total observation budget across all poll rounds
MAX_STREAM_POLLS = 60  # hard iteration cap (independent of time/samples)
MAX_STREAM_DURATION_S = 120.0  # wall-clock ceiling for a whole stream call
DEFAULT_STREAM_DURATION_S = 30.0
MIN_STREAM_INTERVAL_MS = 0  # 0 == back-to-back polling (still bounded)
MAX_STREAM_INTERVAL_MS = 10_000
DEFAULT_STREAM_INTERVAL_MS = 1000

# Indirection so tests can stub the inter-poll sleep without real wall-clock waits.
_sleep = time.sleep

# Agent documents are bounded (count-capped /sample pages); cap the body at
# 4 MiB — well past any legitimate page, a hard ceiling against a hostile or
# broken agent streaming an unbounded body (mirrors the BAS connector's cap).
MAX_RESPONSE_BYTES = 4_194_304
_CHUNK_BYTES = 8192

# DataItem ids/types whose latest value an OEE snapshot cares about.
_OEE_AVAILABILITY = "AVAILABILITY"
_OEE_EXECUTION = "EXECUTION"
_OEE_MODE = "CONTROLLERMODE"
_OEE_PROGRAM = "PROGRAM"


def _guard_dtd(head: str, url: str) -> None:
    """Reject XML carrying a DTD/entity declaration (XXE / billion-laughs defense).

    MTConnect documents never carry a DTD or entity declarations, so any is
    refused before parsing. stdlib ElementTree does not resolve external
    entities, and with DTD/entities barred there is no expansion vector.
    """
    lowered = head[:4096].lower()
    if "<!doctype" in lowered or "<!entity" in lowered:
        raise ValueError(
            f"MTConnect agent at {url} returned XML with a DTD/entity declaration; "
            f"refused (XXE/entity-expansion defense). MTConnect XML carries neither."
        )


def _http_get(url: str, timeout: int = _HTTP_TIMEOUT_S) -> str:
    """Fetch ``url`` streamed and size-capped; return the body as text.

    Monkeypatched in tests. The body is read in chunks and refused once it
    exceeds ``MAX_RESPONSE_BYTES`` — never buffered whole first — and the
    DTD/entity guard runs on the FIRST chunk, before the rest is consumed.
    """
    try:
        import requests
    except ImportError as exc:  # pragma: no cover — exercised only without requests
        from iaiops.core.runtime.connection import OTConnectionError

        raise OTConnectionError(
            "The 'requests' package is not installed. Install the MTConnect "
            "connector: 'pip install iaiops[mtconnect]'."
        ) from exc

    resp = requests.get(url, timeout=timeout, stream=True)
    try:
        resp.raise_for_status()
        body = b""
        for chunk in resp.iter_content(_CHUNK_BYTES):
            if not body:
                _guard_dtd(chunk.decode("utf-8", errors="replace"), url)
            body += chunk
            if len(body) > MAX_RESPONSE_BYTES:
                raise ValueError(
                    f"MTConnect agent at {url} returned more than "
                    f"{MAX_RESPONSE_BYTES} bytes; refused (response size cap). "
                    f"Point the endpoint at a real MTConnect agent, or bound the "
                    f"request (e.g. a smaller /sample count)."
                )
        return body.decode("utf-8", errors="replace")
    finally:
        resp.close()


def _agent_base(target: Any) -> str:
    """Resolve the MTConnect agent base URL from the endpoint config."""
    base = (getattr(target, "agent_url", "") or "").rstrip("/")
    if not base and getattr(target, "host", ""):
        port = target.port or 5000
        base = f"http://{target.host}:{port}"
    if not base:
        raise ValueError(
            f"MTConnect endpoint '{target.name}' has no agent_url. Add "
            f"'agent_url: http://host:5000' (or host/port) to its config entry."
        )
    return base


def _strip(tag: str) -> str:
    """Drop the XML namespace from a tag, leaving the local name."""
    return tag.rsplit("}", 1)[-1]


def _int_or_none(value: str | None) -> int | None:
    """Parse an MTConnect sequence attribute to int, or None if absent/malformed."""
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _stream_header(root: ET.Element) -> dict:
    """Extract sequence bookkeeping from a Streams/Current document ``<Header>``.

    An MTConnect Streams header carries ``nextSequence`` (the sequence to pass as
    the next ``from=``), ``firstSequence`` / ``lastSequence`` (the agent's buffer
    window) and ``instanceId`` (changes when the agent restarts and its sequence
    numbering resets — which invalidates any held ``from`` cursor).
    """
    for el in root.iter():
        if _strip(el.tag) == "Header":
            return {
                "next_sequence": _int_or_none(el.get("nextSequence")),
                "first_sequence": _int_or_none(el.get("firstSequence")),
                "last_sequence": _int_or_none(el.get("lastSequence")),
                "instance_id": s(el.get("instanceId", ""), 32),
            }
    return {
        "next_sequence": None,
        "first_sequence": None,
        "last_sequence": None,
        "instance_id": "",
    }


def _clamp_int(value: int, lo: int, hi: int) -> int:
    """Clamp an int into ``[lo, hi]`` (coerces via ``int`` first)."""
    return max(lo, min(int(value), hi))


def _clamp_float(value: float, lo: float, hi: float) -> float:
    """Clamp a float into ``[lo, hi]`` (coerces via ``float`` first)."""
    return max(lo, min(float(value), hi))


def _fetch_xml(target: Any, path: str, query: str = "") -> ET.Element:
    """GET ``{agent}/{path}`` and parse the XML root (namespaces left intact)."""
    base = _agent_base(target)
    url = f"{base}/{path}"
    if query:
        url = f"{url}?{query}"
    body = _http_get(url)
    # Defense-in-depth: _http_get already guards the first streamed chunk, but
    # tests (and any alternative fetcher) monkeypatch _http_get, so the full
    # body is re-checked here before parsing.
    _guard_dtd(body, url)
    try:
        return ET.fromstring(body)  # nosec B314 — DTD/entities barred above; ET resolves no externals
    except ET.ParseError as exc:
        raise ValueError(f"MTConnect agent at {url} returned unparseable XML: {exc}") from exc


def mtconnect_probe(target: Any) -> dict:
    """[READ] The device model: devices → components → data items (the 'schema')."""
    root = _fetch_xml(target, "probe")
    devices: list[dict] = []
    for dev in root.iter():
        if _strip(dev.tag) != "Device":
            continue
        components: list[dict] = []
        for comp in dev.iter():
            if comp is dev:
                continue
            # A component is any element with a direct <DataItems> container; only
            # its DIRECT DataItem children belong to it (avoids nested double-count).
            container = next((c for c in comp if _strip(c.tag) == "DataItems"), None)
            if container is None:
                continue
            items = [_dataitem(di) for di in container if _strip(di.tag) == "DataItem"]
            if items:
                components.append(
                    {
                        "component": s(_strip(comp.tag), 48),
                        "id": s(comp.get("id", ""), 64),
                        "name": s(comp.get("name", ""), 64),
                        "data_items": items[:MAX_OBSERVATIONS],
                    }
                )
        devices.append(
            {
                "name": s(dev.get("name", ""), 64),
                "uuid": s(dev.get("uuid", ""), 96),
                "component_count": len(components),
                "components": components,
            }
        )
    return {"endpoint": s(target.name, 64), "device_count": len(devices), "devices": devices}


def _dataitem(di: ET.Element) -> dict:
    """Compact, sanitized descriptor for one MTConnect DataItem definition."""
    return {
        "id": s(di.get("id", ""), 64),
        "type": s(di.get("type", ""), 48),
        "category": s(di.get("category", ""), 24),
        "name": s(di.get("name", ""), 64),
        "units": s(di.get("units", ""), 24),
    }


def _observations(root: ET.Element) -> list[dict]:
    """Walk a Streams document; collect every element carrying a dataItemId."""
    out: list[dict] = []
    for el in root.iter():
        if "dataItemId" not in el.attrib:
            continue
        out.append(
            {
                "data_item_id": s(el.get("dataItemId", ""), 64),
                "type": s(_strip(el.tag), 48),
                "name": s(el.get("name", ""), 64),
                "timestamp": s(el.get("timestamp", ""), 40),
                "sequence": s(el.get("sequence", ""), 24),
                "value": s((el.text or "").strip(), 256),
            }
        )
        if len(out) >= MAX_OBSERVATIONS:
            break
    return out


def mtconnect_current(target: Any) -> dict:
    """[READ] Latest value of every data item (a snapshot of the machine now).

    Also returns the header's ``next_sequence`` so a caller can start an
    incremental ``mtconnect_stream`` exactly at 'now'.
    """
    root = _fetch_xml(target, "current")
    obs = _observations(root)
    hdr = _stream_header(root)
    return {
        "endpoint": s(target.name, 64),
        "observation_count": len(obs),
        "next_sequence": hdr["next_sequence"],
        "observations": obs,
    }


def _sample_page(
    target: Any, count: int, from_sequence: int | None = None
) -> tuple[list[dict], dict]:
    """Fetch ONE ``/sample`` page → ``(observations, header)``.

    ``header`` carries next/first/last sequence + instanceId (see ``_stream_header``).
    When ``from_sequence`` is given it is passed as ``from=`` so the agent returns
    observations at or after that sequence (the incremental-pull primitive).
    """
    query = f"count={count}"
    if from_sequence is not None:
        query = f"from={int(from_sequence)}&{query}"
    root = _fetch_xml(target, "sample", query=query)
    return _observations(root), _stream_header(root)


def mtconnect_sample(
    target: Any, count: int = DEFAULT_SAMPLE_COUNT, from_sequence: int | None = None
) -> dict:
    """[READ] ONE bounded ``/sample`` page (count capped server-side).

    With ``from_sequence`` this is a single *incremental* page (observations at or
    after that sequence); without it, the most recent ``count`` observations. The
    returned ``next_sequence`` is the cursor to resume from (feed it back here, or
    into ``mtconnect_stream``).
    """
    count = _clamp_int(count, 1, MAX_SAMPLE_COUNT)
    obs, hdr = _sample_page(target, count, from_sequence)
    return {
        "endpoint": s(target.name, 64),
        "mode": "snapshot",
        "requested_count": count,
        "from_sequence": from_sequence,
        "next_sequence": hdr["next_sequence"],
        "first_sequence": hdr["first_sequence"],
        "last_sequence": hdr["last_sequence"],
        "observation_count": len(obs),
        "observations": obs,
    }


def mtconnect_stream(
    target: Any,
    from_sequence: int | None = None,
    interval_ms: int = DEFAULT_STREAM_INTERVAL_MS,
    count: int = DEFAULT_SAMPLE_COUNT,
    max_samples: int = MAX_STREAM_SAMPLES,
    duration_s: float = DEFAULT_STREAM_DURATION_S,
) -> dict:
    """[READ] BOUNDED incremental long-poll: poll ``/sample`` advancing by sequence.

    Repeatedly fetch ``/sample?from=<seq>&count=<count>`` and advance ``seq`` by the
    header's ``nextSequence`` each round, accumulating new observations until a hard
    bound is hit. This NEVER loops unboundedly — it stops on the FIRST of:

    * ``max_samples`` observations collected (``stopped_reason='max_samples'``),
    * ``duration_s`` wall-clock elapsed (``'duration'``),
    * ``MAX_STREAM_POLLS`` rounds (``'max_polls'``),
    * the agent returns no new observations — caught up (``'caught_up'``),
    * ``nextSequence`` does not advance / is absent (``'no_progress'``),
    * the agent's ``instanceId`` changes mid-stream — a restart reset the buffer,
      so the held cursor is no longer valid (``'instance_changed'``).

    ``interval_ms`` is client-side spacing between rounds (NOT the agent's
    server-push interval). ``from_sequence=None`` starts from the most recent
    ``count`` observations. Returns the observation sequence plus ``next_sequence``
    to resume from.
    """
    count = _clamp_int(count, 1, MAX_SAMPLE_COUNT)
    interval_ms = _clamp_int(interval_ms, MIN_STREAM_INTERVAL_MS, MAX_STREAM_INTERVAL_MS)
    max_samples = _clamp_int(max_samples, 1, MAX_STREAM_SAMPLES)
    duration_s = _clamp_float(duration_s, 0.0, MAX_STREAM_DURATION_S) or DEFAULT_STREAM_DURATION_S
    deadline = time.monotonic() + duration_s

    seq = from_sequence
    collected: list[dict] = []
    polls = 0
    instance_id: str | None = None
    next_sequence: int | None = from_sequence
    stopped = "duration"

    while True:
        if polls >= MAX_STREAM_POLLS:
            stopped = "max_polls"
            break
        if time.monotonic() >= deadline:
            stopped = "duration"
            break

        obs, hdr = _sample_page(target, count, seq)
        polls += 1

        # A restarted agent renumbers sequences; the held cursor is stale → stop
        # rather than silently mixing observations from a reset buffer.
        header_instance = hdr["instance_id"] or ""
        if instance_id is None:
            instance_id = header_instance
        elif header_instance and header_instance != instance_id:
            stopped = "instance_changed"
            break

        if obs:
            collected.extend(obs[: max_samples - len(collected)])
        hdr_next = hdr["next_sequence"]
        if hdr_next is not None:
            next_sequence = hdr_next

        if len(collected) >= max_samples:
            stopped = "max_samples"
            break
        if not obs:
            stopped = "caught_up"
            break
        if hdr_next is None or hdr_next == seq:
            stopped = "no_progress"
            break

        seq = hdr_next
        if interval_ms > 0 and time.monotonic() < deadline:
            _sleep(interval_ms / 1000.0)

    return {
        "endpoint": s(target.name, 64),
        "mode": "stream",
        "from_sequence": from_sequence,
        "next_sequence": next_sequence,
        "observation_count": len(collected),
        "poll_count": polls,
        "stopped_reason": stopped,
        "interval_ms": interval_ms,
        "max_samples": max_samples,
        "observations": collected,
    }


def mtconnect_assets(target: Any) -> dict:
    """[READ] Assets the agent knows (cutting tools, fixtures, programs)."""
    root = _fetch_xml(target, "assets")
    assets: list[dict] = []
    for el in root.iter():
        if _strip(el.tag) != "Assets":
            continue
        for asset in list(el):
            assets.append(
                {
                    "asset_type": s(_strip(asset.tag), 48),
                    "asset_id": s(asset.get("assetId", ""), 64),
                    "timestamp": s(asset.get("timestamp", ""), 40),
                }
            )
        break
    return {
        "endpoint": s(target.name, 64),
        "asset_count": len(assets),
        "assets": assets[:MAX_OBSERVATIONS],
    }


def mtconnect_oee_snapshot(target: Any) -> dict:
    """[READ] Availability / Execution / mode / program from /current (OEE inputs).

    Pulls the key data items an availability/performance calculation needs. Does
    NOT compute a single OEE percentage (that needs planned-time + ideal-cycle
    context this preview cannot know) — it surfaces the live inputs for an agent.
    """
    root = _fetch_xml(target, "current")
    obs = _observations(root)
    picks: dict[str, dict] = {}
    for o in obs:
        key = (o["type"] or "").upper()
        if key in (_OEE_AVAILABILITY, _OEE_EXECUTION, _OEE_MODE, _OEE_PROGRAM):
            picks[key] = o
    availability = (picks.get(_OEE_AVAILABILITY, {}).get("value", "") or "").upper()
    execution = (picks.get(_OEE_EXECUTION, {}).get("value", "") or "").upper()
    available = availability == "AVAILABLE"
    active = execution == "ACTIVE"
    verdict = "running" if (available and active) else "available_idle" if available else "down"
    return {
        "endpoint": s(target.name, 64),
        "availability": s(availability, 32),
        "execution": s(execution, 32),
        "controller_mode": s(picks.get(_OEE_MODE, {}).get("value", ""), 32),
        "program": s(picks.get(_OEE_PROGRAM, {}).get("value", ""), 96),
        "available": available,
        "running": active,
        "verdict": verdict,
        "note": "OEE availability/performance inputs from /current. Full OEE % needs "
        "planned production time + ideal cycle time (not exposed by MTConnect).",
    }


# num() is re-exported for callers that want numeric coercion on observation values.
__all__ = [
    "mtconnect_probe",
    "mtconnect_current",
    "mtconnect_sample",
    "mtconnect_stream",
    "mtconnect_assets",
    "mtconnect_oee_snapshot",
    "num",
]
