# 0.34.0 Compose host trial — 2026-11-09

This is a manual deployment on a lab VM, **not** a Margo WFM/device-agent lifecycle run or a Margo compliance claim. No OT hardware or production endpoint was connected.

## Environment and subject

| Role | VM | OS / resources | State |
|---|---|---|---|
| Planned WFM | `test-llm` (`192.168.1.25`) | Ubuntu 24.04.4; 8 vCPU, 16 GB RAM, 70 GB disk (54 GB guest free after boot) | Powered on after a powered-off, no-memory baseline snapshot `pre-margo-sandbox-20261109`. No WFM service installed. |
| Compose host | `Open-test` (`192.168.1.21`) | Ubuntu 24.04.4; 2 vCPU, 32 GB RAM, 100 GB disk (13 GB guest free) | Docker 29.1.3, user-level Docker Compose 2.40.3 and ORAS 1.3.0. |

The two VMs can reach each other. `test-llm` ran the published factory image as UID 10001 with a read-only root, dropped capabilities and no-new-privileges; `iaiops` reported version `0.34.0` and its health exporter returned `None` with metrics disabled by default.

## Registry pull and Compose execution

On `Open-test`, ORAS anonymously pulled the **published** references:

| Reference | Manifest digest | Result |
|---|---|---|
| `ghcr.io/industrial-aiops/iaiops-margo:0.34.0` | `sha256:9cf7abbe6f8ff6277d7c5d0babf885c7c2be4dc8b08786790d2f99d9e72de3c3` | `margo.yaml` pulled. |
| `ghcr.io/industrial-aiops/iaiops-compose:0.34.0` | `sha256:cdf8852066bb79dc71cf6f8ff0609556c284c1948077e074e1e29aa6aaa4bb34` | One `iaiops-compose-0.34.0.tar.gz` layer pulled. Its SHA-256 is `efc495230780955557cdac75f7eb091e580ce42c51b9c7174c72751db9ab376f`; it contains `iaiops/compose.yaml`. |

Docker Compose rendered that extracted file to image `ghcr.io/industrial-aiops/iaiops:0.34.0-factory`, UID `10001:10001`, read-only root, all capabilities dropped, and host bind `127.0.0.1:8000`. The default OTEL exporter rendered to `none` with protocol `http/protobuf`.

A local, mode-0600 `.env` contained random **test-only** MCP token and master password. `docker compose up -d --no-build` started the published image; it reached `healthy`. An unauthenticated `GET /mcp` returned HTTP 401. An authenticated MCP `initialize` returned HTTP 200 and `serverInfo.version=0.34.0`. No secret values were retained in this record.

A marker written inside the named `iaiops-state` volume survived `docker compose up -d --force-recreate --no-build`. This checks manual Compose state continuity; the replacement container was still in its `starting` health window when checked. An explicit `docker compose down --volumes` then removed the test container, network and named volume. The temporary `.env` and HTTP response files were deleted. The OCI archives and extracted Compose file remain under `/home/wei/workspace/margo-034-device/` for inspection.

## Container OTLP receipt

A second run enabled `OTEL_METRICS_EXPORTER=otlp` and set the endpoint to `http://172.19.0.1:4318/v1/metrics`, the host address on the temporary Compose bridge. A small HTTP receiver bound only to that private bridge address. The published container reached `healthy` and sent a 259-byte OTLP protobuf request. The [retained raw request](otlp-metrics-v0.34.0-2026-11-09.pb) has SHA-256 `4a8024e05cc2bab4bde4b9822e51c304e5cd95430bb78a929443f25b0a9815f4`.

Decoding the request with the published 0.34.0 image yielded exactly `iaiops.process.uptime`, `iaiops.audit.events`, `iaiops.audit.errors` and `iaiops.audit.available`. Its resource attribute keys contained only `service.name`. The random test MCP token and master password were absent from the raw bytes. The receiver, container, named volume, temporary `.env` and receiver files were removed after capture. This verifies container-to-local-receiver OTLP transport, **not** delivery to the sandbox Collector or a WFM deployment.

## Remaining WFM gate

The official sandbox setup scripts require sudo on both VMs, and the current `wei` guest account prompts for a password. `test-llm` could not complete `git ls-remote https://github.com/margo/sandbox.git` within 10 seconds; the same command succeeded on `Open-test`. The full sandbox source at commit `64d7a7433e304f1694b2f72d9bf3af288de5e368` was therefore relayed to `/home/wei/workspace/sandbox` on `test-llm` and checked clean there. `ghcr.io` was reachable from `test-llm`. Symphony, MIS, Harbor, the sandbox Compose agent and Collector were **not** installed. WFM onboarding, deploy, update, delete and Collector receipt are still `待核实`. The upstream Compose update path also needs the named-volume fix tracked in [margo/sandbox#490](https://github.com/margo/sandbox/issues/490).
