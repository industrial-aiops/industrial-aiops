# The adapter belt — lightweight core, open to every interface

Industrial-AIOps is deliberately a **small neutral core wrapped by a thin, pluggable adapter belt**.
It binds no store, no bus, no host, no model — it *fits* whatever a site already runs. The whole
system is three legs:

```
  INGRESS                         CORE                                  EGRESS
  protocol tap  ─────────▶  normalize → govern → RCA  ─────────▶  sinks · stream · export · narrate
  (OPC-UA, Modbus,          (ISA-95/18.2 model,                   (TSDB, message bus, files,
   S7, EtherNet/IP,          audit/budget/risk-tier/undo,          on-box LLM)
   BACnet, MQTT, …)          deterministic RCA — see RCA.md)
```

Everything on the edges is an **optional, lazily-imported adapter behind a tiny SPI** — the base
package installs and imports with none of them, and a site installs only the 1–2 it uses. This is the
same discipline as the per-protocol connector extras.

## The three SPIs

| Leg | SPI | Interface | Adapters (extras) |
|-----|-----|-----------|-------------------|
| **Ingress** | connectors | per-protocol read ops | `opcua`, `modbus`, `s7`, … (14) |
| **Egress · historian** | `iaiops.core.sink` — `get_sink(kind)` → `write(points) -> int` | write normalized points to a TSDB | `sqlite` (built-in) · `tdengine` · `iotdb` · **`influxdb`** |
| **Egress · stream** | `iaiops.core.egress` — `get_publisher(kind)` → `publish_points()` / `publish_event()` | publish points + RCA/alarm events to a bus | **`nats`** |
| **Egress · narrate** | `iaiops.core.llm` — `get_provider(kind)` → `complete()` | on-box LLM narration of a cited RCA verdict | **`ollama`** |

`normalize_points()` (in `sink/base.py`) produces the uniform `{metric, value, numeric, timestamp,
tags}` shape that **all** egress adapters consume — so the core computes once and every target reuses it.

## Adding an adapter (the pattern)

Every adapter follows the same 5 rules, so a new target is a small, self-contained file:

1. **Lazy-import** the client library *inside* the method that needs it — never at module load.
2. Raise the belt's teaching error (`SinkError` / `EgressError` / `LLMError`) with the exact
   `pip install iaiops[<extra>]` when the lib is missing.
3. Keep the network call in **one isolated method** (`write` / `_deliver` / `complete`) so the shaping
   logic is mock-testable without a server.
4. Add the extra to `pyproject.toml` (prefer reusing the `requests` pin over a heavy SDK).
5. Register it in the leg's factory (`get_sink` / `get_publisher` / `get_provider`) + its
   `SUPPORTED_*` tuple, and add a mock-based test.

## Read-first stays intact

Egress carries only data iaiops **already read** or **already computed** (normalized tags, alarm
episodes, RCA verdicts). It is **not** a control-system write — the few real writes remain the rare,
MOC-gated exception in the connectors. Publishing to your bus or historian never touches the plant.

## Why this matters (the pitch)

A neutral host (IGEL / any Margo device) wants a workload that drops in without dragging a store, a
broker, or a cloud dependency behind it. The adapter belt is exactly that: **install the core + the
one or two adapters your site runs, and it fits.**
