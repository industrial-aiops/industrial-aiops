# iaiops as a Margo-style edge application — reproducible, headless, non-root, read-only-rootfs friendly.
# See docs/MARGO-ALIGNMENT.md (§4 work items). Built + cosign-signed per profile by CI
# (.github/workflows/publish-image.yml → ghcr.io/industrial-aiops/iaiops:<version>-<profile>).
# NOT Margo-compliant yet — the conformance run is still 待核实.
#
# Build:  docker build -t iaiops:factory --build-arg PROFILE=factory -f deploy/margo/Dockerfile .
# Run:    see deploy/margo/compose.yaml
ARG PYTHON_VERSION=3.12

# ── build stage: install the published wheel + the chosen edition extra into a venv ──
FROM python:${PYTHON_VERSION}-slim AS build
# Which edition profile to bake in. Matches an IAIOPS_MCP profile AND the same-named pip extra
# (fab / factory / process / building / water). Pin the version for a reproducible image.
ARG PROFILE=factory
ARG IAIOPS_VERSION=0.14.0
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
# Install from PyPI (published, reproducible). To build from local source instead, replace the
# next line with:  COPY . /src  &&  pip install "/src[${PROFILE}]"
RUN pip install "iaiops[${PROFILE}]==${IAIOPS_VERSION}"

# ── runtime stage: minimal, non-root ──
FROM python:${PYTHON_VERSION}-slim AS runtime
ARG PROFILE=factory
# Non-root user; app state lives under its home so the rootfs can be mounted read-only.
RUN useradd --create-home --uid 10001 iaiops
COPY --from=build /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH" \
    # The MCP server reads this to expose ONLY the selected edition's tools (no default flood).
    IAIOPS_MCP=${PROFILE} \
    # Config + encrypted secrets + audit/undo store live here — mount a volume at this path.
    IAIOPS_HOME=/home/iaiops/.iaiops \
    # MCP transport. stdio is the image default (works for a local `docker run … | client` pipe).
    # A Margo/edge deployment fronts it as a SOCKET instead — set these three (see compose.yaml):
    #   IAIOPS_MCP_TRANSPORT=streamable-http  IAIOPS_MCP_HOST=0.0.0.0  IAIOPS_MCP_PORT=8000
    # (socket is what the Margo app-package WG recommends — one container port, no protocol glue;
    #  app-package-definition-wg, 2026-07-13. See docs/MARGO-ALIGNMENT.md appendix B.) Guard a
    #  non-loopback bind with IAIOPS_ALLOWLIST_IPS or a front gateway.
    IAIOPS_MCP_TRANSPORT=stdio \
    IAIOPS_MCP_HOST=127.0.0.1 \
    IAIOPS_MCP_PORT=8000 \
    PYTHONUNBUFFERED=1
USER iaiops
WORKDIR /home/iaiops
# Config/secrets/audit are a mounted volume (see compose.yaml). Least-privilege: this workload is
# read-first and makes only OUTBOUND connections to the OT endpoints you configure — it opens NO
# inbound OT protocol listeners. The one optional inbound port below is the MCP tool interface (for
# the orchestrator/agent), not an OT port, and is off unless you select the socket transport.
VOLUME ["/home/iaiops/.iaiops"]
# The MCP socket transport (streamable-http/sse) listens here when selected; harmless under stdio.
EXPOSE 8000
# Liveness: the capability map is a pure, no-network self-check.
HEALTHCHECK --interval=1m --timeout=10s --start-period=15s --retries=3 \
    CMD ["iaiops", "protocols"]
# Headless MCP server for the baked-in profile — stdio by default, socket when the IAIOPS_MCP_*
# env above selects streamable-http/sse (the Margo-recommended shape).
ENTRYPOINT ["iaiops-mcp"]
