# Footprint — small by design

A neutral edge host wants a *small, controllable* workload. iaiops is built for that, and treats
footprint as a first-class property, not an afterthought.

## What keeps it small

- **Pure-Python core, no compiled base deps** — 6 runtime dependencies (`typer`, `rich`, `pyyaml`,
  `python-dotenv`, `cryptography`, `mcp[cli]`). The base wheel is ~0.5 MB.
- **Lazy imports** — every protocol client and every adapter (sink / stream / LLM) is imported only
  when first used, so unused ones cost nothing at import.
- **Per-profile installs** — a site installs only the 1–2 protocols + adapters it runs
  (`iaiops[opcua,modbus]`, an edition bundle, or `+[influxdb]` / `+[nats]` / `+[ollama]`), not the
  whole matrix.
- **No bundled store / broker / model** — the historian, bus, and LLM stay external (the adapter
  belt, see `ADAPTERS.md`), so iaiops never drags a heavy runtime behind it.
- **Hardened container** — non-root, read-only rootfs + a tmpfs (`deploy/margo/`); no inbound ports.

## Declared resource envelope (`deploy/margo/margo.yaml`)

| Resource | Declared |
|----------|----------|
| CPU | 0.5 core |
| Memory | 512 MiB |
| Storage | 1 GiB |
| Arch | amd64, arm64 |

## Measured / `待核实`

| Metric | Value |
|--------|-------|
| Base wheel size | ~0.5 MB (PyPI `iaiops` sdist/wheel) |
| Base runtime deps | 6 (all pure-Python) |
| Per-protocol extra | +1–2 libs each (e.g. `opcua` → `asyncua`) |
| Adapter extras (`influxdb`/`nats`/`ollama`) | `influxdb`/`ollama` reuse `requests`; `nats` adds `nats-py` (pure-Python) |
| **Container image size** | `待核实` — measure per edition profile after `docker build` |
| **Runtime RAM (idle / under sampling)** | `待核实` — measure on the target host/arch |

## How to measure (reproducible)

```bash
# image size per profile
docker build -t iaiops:factory --build-arg PROFILE=factory -f deploy/margo/Dockerfile . \
  && docker image inspect iaiops:factory --format '{{.Size}}' | numfmt --to=iec

# idle RSS of the running MCP server
docker run --rm -e IAIOPS_MCP=factory iaiops:factory &   # then: docker stats --no-stream
```

Record real numbers here as they're taken (replace the `待核实` rows) — a small, *documented*
footprint is a selling point for the "smaller, less expensive, more control" edge story.
