# iaiops as a Margo-style edge application — reproducible, headless, non-root, read-only-rootfs friendly.
# See docs/MARGO-ALIGNMENT.md (§4 work items). NOT a Margo-compliant image yet — this is the
# `⏳` container skeleton; the app-package descriptor + conformance run are still 待核实.
#
# Build:  docker build -t iaiops:factory --build-arg PROFILE=factory -f deploy/margo/Dockerfile .
# Run:    see deploy/margo/compose.yaml
ARG PYTHON_VERSION=3.12

# ── build stage: install the published wheel + the chosen edition extra into a venv ──
FROM python:${PYTHON_VERSION}-slim AS build
# Which edition profile to bake in. Matches an IAIOPS_MCP profile AND the same-named pip extra
# (fab / factory / process / building / water). Pin the version for a reproducible image.
ARG PROFILE=factory
ARG IAIOPS_VERSION=0.10.1
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
    PYTHONUNBUFFERED=1
USER iaiops
WORKDIR /home/iaiops
# Config/secrets/audit are a mounted volume (see compose.yaml). Least-privilege: this workload is
# read-first and needs only OUTBOUND access to the OT endpoints you configure — no inbound ports.
VOLUME ["/home/iaiops/.iaiops"]
# Liveness: the capability map is a pure, no-network self-check.
HEALTHCHECK --interval=1m --timeout=10s --start-period=15s --retries=3 \
    CMD ["iaiops", "protocols"]
# Headless MCP server for the baked-in profile. NOTE (待核实): iaiops-mcp speaks MCP over stdio by
# default — the transport a Margo orchestrator expects (stdio vs socket vs HTTP/SSE) is exactly the
# open question in the app-package-definition-wg post (docs/MARGO-ALIGNMENT.md appendix B).
ENTRYPOINT ["iaiops-mcp"]
