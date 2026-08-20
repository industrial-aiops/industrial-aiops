# `deploy/siemens-ie/` — iaiops as a Siemens Industrial Edge app

> **One distribution target, not a fork.** The artifact is the same published, cosign-signed OCI
> image used by [`../margo/`](../margo/) and [`../airgap/`](../airgap/). This folder is the
> Industrial-Edge-specific packaging around it.
>
> **Status: buildable today, not listed.** The compose definition here is what IEAP imports; the
> marketplace listing needs a Siemens relationship (see §3). Everything marked `待核实` needs a real
> IED/IEVD to confirm — the same discipline as the rest of the repo.

## Why this target is worth the effort

Unlike most app stores, Siemens charges **no membership fee and no listing fee** — only a
transaction cut on revenue, and the percentage is disclosed under the Ecosystem Agreement
(`待核实`: it is not published anywhere public). Siemens is also **Merchant of Record**, so billing,
invoicing, VAT and refunds are handled for you — non-trivial for a small vendor selling into
industrial enterprises across many jurisdictions.

Most importantly: **the marketplace is explicitly non-exclusive.** A `.app` file can be handed
directly to a customer who imports it into their own IEM, with no Siemens approval in the loop. So
the packaging work below has value whether or not the listing ever happens.

## 1. What Industrial Edge requires that other targets do not

| Rule | Where it bites |
|---|---|
| `mem_limit` is **mandatory** | IEAP rejects a service without one |
| IEAP **enforces** a CPU limit on every container | We set `cpus` explicitly so the number is ours |
| Bind mounts only from `./` | State must be a **named volume** — it already is |
| `proxy-redirect` is the default app network | Joined, so the app is reachable through the IED |
| Apps are **x86-64 or arm64**, never both in one package | Build per architecture; the published image is multi-arch, so the tag is the same |
| Privileges are **shown to the operator** at install | Every capability not requested is one less review question |

Our posture (`read_only`, `cap_drop: ALL`, `no-new-privileges`, non-root uid 10001, no inbound OT
port) is unchanged from the Margo package — it was already at the level Industrial Edge's security
guidance asks for.

## 2. Build the `.app`

No Siemens hardware is needed. Two supporting pieces do the work:

- **Industrial Edge Virtual Device (IEVD)** — a software-only IED running as a VM, for testing.
- **Edge App SDK** — emulates the device services locally, so an app can be developed and debugged
  with no IED at all.

```bash
# 1. Verify the artifact you are about to package (do this first, every time)
cosign verify --key ../margo/cosign.pub ghcr.io/industrial-aiops/iaiops:0.22.0-factory

# 2. Pull it so IEAP can import from the local Docker engine
docker pull ghcr.io/industrial-aiops/iaiops:0.22.0-factory

# 3. In IE App Publisher: create app -> add version -> import this docker-compose.yaml
#    -> configure pages (network / ports / volumes) -> validate -> export .app
#    待核实: IEAP needs the Docker CLI reachable over a TCP socket of the local daemon.
```

Then import the `.app` into an IEM and deploy it to an IEVD.

## 2b. What the marketplace actually looks like (verified 2026-08-20)

Two findings from reading the live catalogue that are not in any Siemens document:

**The catalogue is region-gated, and this is undocumented.** In the default anonymous
`zh_CN` view it returns **70 offerings, every one of them Siemens** — no third parties at all.
Forcing `?cclcl=en_US` returns **71 offerings across 8 vendors**, including the third-party apps.
So a listing can be invisible in a given market without anything saying so. **Verify locale
visibility before signing** — a slot nobody in your target region can see is worth far less than
it appears.

**Third parties are scarce, which cuts the other way.** The full en_US third-party set is roughly
**11 apps against ~60 Siemens first-party ones**: HighByte, HiveMQ Edge, AWS IoT SiteWise Edge,
OPC Router (2 SKUs, via Software Toolbox), FFT (2), Novakon (3), Dynics. Being one of eleven is a
genuinely scarce position — the opposite of the IGEL App Portal, where 143 apps compete and 59% of
them are under 1K downloads.

**Prices are shown for Siemens apps and hidden for most third parties.** Siemens' own connectors
publish annual figures (OPC UA HP Connector $192/yr, Modbus TCP $216/yr — each entitling **one
instance on one device and twenty data sources**). Among third parties only OPC Router shows a
price ($2,292/yr); HighByte and HiveMQ both say "contact us". Worth knowing before deciding whether
to publish a number.

## 3. Getting listed — the honest sequence

The Ecosystem process is **not self-serve**. Phase one ends at "contact the Industrial Edge
Ecosystem team to qualify for assessment" — a human at Siemens decides whether the use case is worth
their review effort.

| Step | What it needs | Status |
|---|---|---|
| ① Working `.app` + a named customer use case | This folder + an IEVD | **in progress** |
| ② Qualify — email `industrialedgeecosystem.industry@siemens.com` | A use-case document; arriving with a running app converts "why bother" into "let's process this" | not started |
| ③ Seller onboarding | **Company entity**; Siemens runs a background check incl. export control | `待核实` |
| ④ Legal onboarding | Ecosystem Agreement + Acceptable Use Policy + Antitrust Code of Conduct + App Developer Supplemental Terms | `待核实` |
| ⑤ Ecosystem Review | Use-case doc, release candidate, documentation, sample data; then a four-category test phase | `待核实` |
| ⑥ DEX registration | App Seller Role from the regional Ecosystem Manager; product ID issued | `待核实` |

Precedent that the door is open to non-giants: **inray** (OPC Router, three SKUs) and **axtesys**, a
small Austrian shop with four database-connector apps. Both are meaningfully smaller than Siemens.

`待核实` throughout: the transaction-fee percentage, the review duration (Siemens publishes no SLA),
whether a formal SBOM is a hard gate, and whether a third-party app may take the PROFINET interface
directly — the documented intent is that apps consume PLC data via the Connectivity Suite / S7
Connector and the **IE Databus**, not by speaking PROFINET themselves.

## 4. Where iaiops fits on an IED

The IE Databus is an on-device **MQTT broker** with per-app credentials — which is exactly the
surface [`uns_publish`](../../mcp_server/tools/egress_tools.py) already speaks. So the natural
integration is bidirectional and needs no new code:

```
Siemens connectors ──publish──> IE Databus ──subscribe──> iaiops (read)
iaiops brain ────────────────> IE Databus <──subscribe──── IIH / other apps
   (uns_publish)
```

That is worth stating plainly in a submission: the app is a **good citizen of the platform's own
data fabric** rather than a parallel stack.

`待核实`: whether IE Databus supports Sparkplug B natively. It is documented as a plain MQTT broker
with configurable topic/payload formats — Sparkplug is a payload convention layered on top, so it
can be implemented, but do not assume host-application/edge-node semantics from Siemens.
