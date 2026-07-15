<!-- Design note — how Industrial-AIOps positions itself in the Margo edge-interoperability
     ecosystem. Honest by construction: iaiops is NOT Margo-compliant today; this records the
     role mapping, the concrete gap, and the contribution plan. Same 待核实 discipline as the
     rest of the repo. -->

# Industrial-AIOps × Margo — ecosystem alignment (design note)

> **TL;DR（中文）** — [Margo](https://margo.org/)（Linux Foundation 的工业边缘互操作标准，PR1 2026-01，GA 计划 2026 内）把边缘世界分成三个角色：**设备 / 应用 / 编排软件**。iaiops 天然是其中的**边缘应用（edge application）**——一个厂商中立、带治理的 OT 只读 tap + 跨协议 RCA，全部以受治理的 MCP 工具暴露。本文记录：角色映射、**诚实的差距（我们现在还不是 Margo-compliant）**、以及不花钱先当贡献者的落地路径。定位是 roadmap `⏳`，不是既成事实。

## 1. Why Margo, and why it's complementary (not either/or)

Margo standardises **the handshake, not the implementation**: any application packaged as a
Margo *application package* can be deployed by any compliant workload-orchestration software
onto any compliant device. That is exactly the neutrality iaiops already sells at the protocol
layer — so the two stack cleanly instead of competing:

```
┌──────────────────────────────────────────────────────────────────┐
│  Edge DEVICE / host        — hardened, immutable, centrally managed │  ← Margo device role
│    (an immutable edge OS such as IGEL OS, or any Margo device)      │     (host vendor's lane)
├──────────────────────────────────────────────────────────────────┤
│  Workload ORCHESTRATION    — declarative desired-state fleet mgmt   │  ← Margo WOS role
│    (any Margo-compliant orchestrator)                              │
├──────────────────────────────────────────────────────────────────┤
│  Edge APPLICATION          — iaiops: governed OT read tap +         │  ← where iaiops sits
│    14-protocol normalization + cross-protocol RCA, as MCP tools     │     (our lane)
│    → optional on-box LLM (air-gapped brain), data never leaves plant │
└──────────────────────────────────────────────────────────────────┘
```

Neither layer steps on the other's lane. The host vendor owns the immutable OS + fleet control;
iaiops is a portable, governed OT-domain app that *any* compliant orchestrator can place.

## 2. Role mapping — iaiops → Margo

| Margo concept | iaiops today | Gap to be Margo-shaped |
|---|---|---|
| **Application package** (container + standard *application description*, OCI/Helm) | Ships as one Python package + a menu-configurable MCP server; container image is straightforward | Author a Margo **application description** + publish an OCI image per edition profile |
| **Edge application** (containerised workload) | Pure-Python core, lazy per-protocol extras, runs headless as an MCP server | Package the `IAIOPS_MCP` profiles (`fab`/`factory`/`process`/`building`/`water`) as deployable app variants |
| **Device role** (compliant host) | N/A — we ride on the host | Validate on an immutable/centrally-managed edge OS (candidate: IGEL OS + its container runtime) |
| **Orchestration (WOS)** desired-state | N/A — we are the payload | Confirm iaiops deploys/updates cleanly under a compliant orchestrator's desired-state lifecycle |
| **Compliance test suite** (open, publicly traceable results) | Not run | Run the Margo conformance toolkit; publish the result — only then may we say *Margo-compliant* |

**Honest status:** iaiops is **NOT Margo-compliant today** (`待核实` until the conformance toolkit
passes on a real device). Everything in §4 is roadmap `⏳`. Do not claim compliance in any
material until the published test result exists — that would break the same honesty discipline
the rest of this repo runs on.

## 3. Why iaiops is a *good* Margo citizen already

- **Governed by construction** — audit / budget / risk-tier / undo + MOC gating already wrap every
  tool; a Margo host wanting a *safe* OT workload gets governance for free.
- **Neutral** — 14 field protocols in this package, no vendor lock, MIT. Margo's whole thesis is
  multi-vendor neutrality.
- **Air-gap friendly** — pure-Python core, offline wheelhouse install, encrypted local secrets,
  optional on-box LLM brain → data never leaves the plant. Fits an immutable edge host.
- **Already a published, governed MCP server** — when Margo's own MCP work lands, iaiops is a
  neutral tool layer that a neutral host can adopt without bespoke glue.

## 4. Work items (roadmap `⏳` — tracked in `docs/ROADMAP.md`)

1. **`✅` Container image (2026-07-15)** — reproducible OCI image per edition profile (base +
   selected extras), headless MCP entrypoint, non-root, read-only rootfs friendly
   (`deploy/margo/Dockerfile`). CI builds multi-arch per-profile images on every release tag,
   **cosign-signs them** (public key `deploy/margo/cosign.pub`), and pushes
   `ghcr.io/industrial-aiops/iaiops:<version>-<profile>`.
2. **`✅` Margo application description (2026-07-15)** — **done to the real `margo.org/v1-alpha1`
   schema** (`deploy/margo/margo.yaml`: compose `deploymentProfiles` / `components` /
   `requiredResources` / `parameters` / `configuration`). **WG feedback folded in (2026-07-13,
   ABB / P. Presson):** the descriptor targets the **socket (streamable-http) transport**
   (WG-recommended; `transport` / `mcpPort` / `allowlistIps` parameters + the compose port), and
   keeps the **single parameterised application** (`profile`) rather than N packages. **Hosted +
   signed + CI-linted:** CI attaches the cosign-signed `iaiops-margo-package-<version>.tar.gz`
   (descriptor + deploy-ready compose) to each GitHub release (= `packageLocation` /
   `keyLocation`), and `tests/test_margo_package.py` lints the descriptor against the pinned
   profile bundles. Remaining: only the secret-parameter flag (pending
   [`margo/specification#145`](https://github.com/margo/specification/issues/145)).
3. **`⏳` On-box LLM brain option** — document/point the RCA copilot at an on-box local LLM for a
   fully air-gapped diagnostic path (no cloud egress).
4. **`⏳` Conformance run** — execute the Margo compliance toolkit on a real device; publish the
   traceable result. **Only after this passes** does any material say *Margo-compliant*.
5. **`⏳` Immutable-host validation** — a live deploy on a candidate immutable edge OS (IGEL OS or
   equivalent), captured as a `待核实 → verified` row like every other hardware pass.

## 5. Participation — contributor first, membership later

Margo is a Linux Foundation open project: **contributing is free and open to anyone**; paid
sponsorship only buys governance/steering seats. For a small team the right order is:

1. **Now (free):** contribute on Margo's GitHub org + Discourse — raise the *governed MCP-based OT
   diagnostics app* as a use case, and offer iaiops as a reference edge application. See the
   ready-to-paste intro in the appendix.
2. **Track the spec:** PR1 (2026-01) → GA (2026); the descriptor format may still move, so align
   packaging while it's cheap and feed back friction as issues.
3. **Membership later:** only once there's customer/revenue pull — don't pre-pay for a seat.

## 6. Brand-isolation note

Margo, LF Edge, IIoT, "edge interoperability" are neutral open-standard / ecosystem terms (same
tier as IEC 62443 / 等保 already in this repo) — safe in-repo. **IGEL** is named only as *one
candidate* immutable-host target for prototyping — no partnership is stated or implied. Avoid
IT-line orchestration brand words entirely (per the repo's brand-isolation 铁律); say
"container / OCI" and "compliant orchestrator" generically.

## 7. Concrete join steps (verified 2026-07-09)

Contributing is free; no sponsorship needed (*"join Margo as a contributing member without
sponsoring… deliverables free of charge"*). Do these once, with the **wei `<zhouwei008@gmail.com>`**
identity (per repo brand rule):

1. **Register** (adds you to the Technical WG + grants GitHub repo access):
   the onboarding form → `https://docs.google.com/forms/d/e/1FAIpQLScB4q9c86zeUIngV-z0HfShSNVsU5whWwcgbyUprfeJWMkp4w/viewform`
   (linked from `operations.margo.org/member-onboarding`). Alt entry: `https://margo.org/about/members/join/`.
2. **Linux Foundation ID (LFID/LFX)** — create at `https://docs.linuxfoundation.org/lfx/sso/create-an-account/`
   (needed for the mailing list + LF program access).
3. **GitHub** — `https://github.com/margo`. Key repos: `specification`, `technical-wg`
   (agendas/minutes in its **issues**), and the four focus groups:
   **`app-package-definition-wg`** ← *our lane*, `woa-interfaces-wg`, `device-requirements-wg`,
   `app-observability-wg`.
4. **Discourse** — `https://discourse.margo.org/` (spec discussion/feedback). Discord + mailing
   list (`https://lists.margo.org/g/main` → "Join this Group", needs LFID) also available.
5. **Contacts** — `operations@margo.org` (general), `membership@margo.org`, training
   `smcilroy@linuxfoundation.org`.

**Credibility move (beyond a hello):** engage the **`app-package-definition-wg`** focus group with
the app-package question below — that's the WG that owns the descriptor iaiops needs, and it directly
advances Work item §4.2. Watch the Events page for **Plug Fests** (interop test events) — a future
`待核实 → verified` opportunity.

---

## Appendix — ready-to-paste posts

### A. Intro (Discourse `discourse.margo.org` / general)

> **Subject:** Governed, MCP-based OT diagnostics as a Margo edge application — reference + feedback
>
> Hi Margo community — I maintain **Industrial-AIOps** (`iaiops`, MIT, on PyPI + the MCP Registry),
> a vendor-neutral OT **read-first** data tap across ~14 field protocols (OPC-UA, Modbus, S7comm,
> EtherNet/IP, PROFINET-DCP, BACnet/IP, MTConnect, MQTT-Sparkplug, HART-IP, …) plus a cross-protocol
> RCA "brain", all exposed as **governed MCP tools** (audit / budget / risk-tier / undo + change-mgmt
> gating on the few writes).
>
> It maps naturally onto Margo's **edge-application** role: pure-Python, headless, air-gap friendly,
> already container-shippable. I'd like to (a) package it with a proper Margo application description,
> (b) run the conformance toolkit, and (c) offer it as a neutral reference OT app. Two questions:
> is a governed MCP tool-server a shape the app-package spec already accommodates, and where's the
> best place to feed packaging friction from a small independent maintainer? Happy to contribute the
> descriptor + a container recipe back.

### B. Focus-group post (`app-package-definition-wg`, GitHub Discussion/issue)

> **Title:** Packaging a headless MCP tool-server (multi-profile) as a Margo application — descriptor questions
>
> Bringing a concrete candidate app to the app-package WG. **iaiops** is a headless, pure-Python OT
> diagnostics workload that runs as a **governed MCP server**; a site enables one *profile* (e.g.
> `fab` / `factory` / `process` / `building`) selecting which field-protocol connectors load. Trying
> to map it to a Margo application description, three questions:
>
> 1. **Runtime shape** — the app exposes an MCP stdio/socket tool surface rather than an HTTP UI. Does
>    the app-package descriptor care about the interface, or purely about the container + config +
>    lifecycle?
> 2. **Profiles / variants** — is the idiom one application with parameterised config, or N app
>    packages (one per profile)? We can go either way.
> 3. **Least-privilege declaration** — is there a place to declare that the workload is read-first and
>    needs only outbound access to specified OT endpoints (no inbound)? Governance is core to us.
>
> Happy to open-source a reference container recipe + descriptor as a worked example for a
> "governed, read-only OT tool app" once I know the intended shape.

#### B.1 — Answers received (2026-07-13, ABB / Philip Presson · Discourse [t/43](https://discourse.margo.org/t/governed-mcp-based-ot-diagnostics-as-a-margo-edge-application-reference-feedback/43))

1. **Runtime shape** — *"specifying how applications communicate with each other is not in Margo's
   scope."* No position on stdio vs socket; **socket recommended** as simpler to deploy (just open a
   container port). → **Done:** `deploy/margo/` now defaults the deployment to the **streamable-http
   socket** transport (`IAIOPS_MCP_TRANSPORT` / `_HOST` / `_PORT`, one IP-allowlisted port), stdio
   kept as the local-pipe fallback.
2. **Profiles / variants** — *"Margo doesn't have an opinion on how applications are implemented."*
   A `profile` parameter is valid; multiple packages are also valid. → **Done:** we keep **one
   parameterised application** (`profile` param), the simpler supply/upgrade story for App Portal.
3. **Secrets + least-privilege** — secret-typed parameters are **not yet in the spec**; tracked at
   [`margo/specification#145`](https://github.com/margo/specification/issues/145) (assoc. #129).
   → **Open, and our contribution lane.** #145 currently weighs two models — an app-encrypted opaque
   blob passed through the WFM (nilanjan-samajdar), and a WFM-managed per-device key derived from the
   device cert via HKDF-SHA256 + AES-256-GCM (vireshnavalli). **iaiops offers a distinct third
   model worth putting on #145: a reference, not a value** — the descriptor/deployment spec carries
   only the secret's logical *name*; the real value is provisioned out-of-band into the device's own
   encrypted secret store and resolved on-device by name, so the secret never enters the Margo
   control plane at all. Pair it with a least-privilege declaration (this secret is used only for
   outbound connections to endpoints X/Y — overlaps #145's `Runtime Constraints/Interoperability`
   label). Next action: post the iaiops reference-model use case on #145 and offer iaiops as a
   real-world validation target.
