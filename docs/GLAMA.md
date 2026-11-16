# Glama listing and build settings

## Listing

Suggested name: **Industrial-AIOps** (previous listing label: OT-AIops).

Suggested profile description:

> Vendor-neutral industrial data collection and diagnostics for AI agents and CLI
> workflows. Read OPC UA, Modbus, S7, MQTT/Sparkplug B, BACnet and other supported
> protocols; inspect asset inventory, alarms, data quality, OEE and downtime using
> collected evidence. MCP and CLI share audited governance. Analysis runs without
> a model; optional LLM narration is separate. Choose an industry or protocol
> profile. Connector coverage and real-device verification vary; this is not a
> safety system, and it does not deploy PLC logic.

Suggested categories: **Monitoring**, **Developer Tools**, **IoT** (use the closest
available labels in Glama). Industry profiles and bundled agent skills belong to
this server; they are not separate MCP directory entries.

## Claiming the organization listing

The repository root `glama.json` must contain the official schema URL and include
GitHub username `zw008` in `maintainers`. Preserve any other maintainers. Merge it
into the default branch, allow Glama to synchronize, and connect `zw008` in Glama.
A local untracked file does not grant access. Every new public MCP service repo
must include this file from its first commit.

Do not put profile descriptions or guessed build keys into `glama.json`; maintain
listing text in Glama's profile editor and keep repository metadata consistent.

## Build and startup

Glama's Dockerfile admin page holds its own build spec: build steps, command,
environment-variable schema and placeholders. It tests both image construction
and server startup. Updating this repository alone does not prove that the saved
Glama build spec has changed or that a Glama release has succeeded.

Use Python 3.12 and install the published package with an explicit dependency
extra, for example:

```sh
pip install 'iaiops[factory]==0.34.1'
```

Configure the executable as `iaiops-mcp`, with no arguments, and set:

```text
IAIOPS_MCP=factory
IAIOPS_MCP_TRANSPORT=stdio
PYTHONUNBUFFERED=1
```

Keep stdin open for the MCP handshake. Do not select streamable HTTP for a stdio
build test. `IAIOPS_MCP` is required: omitting it prints the profile selection menu
and exits with status 2. Other supported profiles include `building` and `water`;
install the corresponding package extra when changing the profile.

Run as a non-root user with a writable home directory. Preserve the audit/config
state directory (`IAIOPS_HOME`, default `~/.iaiops`) on a private writable volume.
Do not bake endpoint credentials, master passwords or production configuration
into the image. A build/handshake check needs no production OT access.

The repository already supplies a multi-stage container recipe with the profile,
non-root user and state directory configured:

```sh
docker build -f deploy/margo/Dockerfile \
  --build-arg IAIOPS_VERSION=0.34.1 --build-arg PROFILE=factory \
  -t iaiops-glama:0.34.1 .
docker run --rm -i -v iaiops-glama-state:/home/iaiops/.iaiops \
  iaiops-glama:0.34.1
```

Glama may use a generated build spec rather than that file. Compare its saved
spec with these settings before diagnosing a failure. Record the failing stage,
command and first relevant error from the build test; do not infer the actual
failure from a directory score or a repository Dockerfile alone.

After a successful Glama Deploy test, create a Glama release separately. A GitHub
or PyPI release does not create one automatically. Confirm the public profile,
version and claim state after synchronization.

References: [official claim guidance](https://glama.ai/blog/2025-07-08-what-is-glamajson),
[official release workflow](https://glama.ai/blog/2026-03-15-how-to-make-a-release),
[maintainer schema](https://glama.ai/mcp/schemas/server.json).
