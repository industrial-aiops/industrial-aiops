<!-- Feasibility study (2026-07-15) — closing the CC-Link gap (the biggest Japan-market hole in
     the protocol matrix) without breaking the read-first, no-special-hardware tap model. Design
     note only; no connector is shipped by this document. Same 待核实 discipline as the rest of
     the repo. -->

# CC-Link family — feasibility study (调研结论)

> **TL;DR（中文）** — CC-Link 家族是协议矩阵里日本市场的最大缺口。结论：**可行，且不需要任何
> 专用硬件** — 不是去参与 CC-Link 网络本身（那条路要主站卡/ASIC/认证，且与 read-first 定位冲突），
> 而是**经主站 PLC 的以太网口用 SLMP 读链路映像 + 网络诊断寄存器**。SLMP 的报文格式与
> MC 协议 QnA-3E 帧相同 — 也就是说现有 `mc` connector（pymcprotocol，纯 Python）已经在说这门
> 语言。推荐路线 = 扩展 `mc` connector（CC-Link 链路设备模板 + SB/SW 网络诊断工具），而非新建
> connector。实机验证 `待核实`。

## 1. The family, and what each member is made of

| Variant | Physical layer | Cyclic transport | Third-party software tap? |
|---|---|---|---|
| **CC-Link** (classic, 2000) | RS-485 fieldbus | proprietary serial frames | ❌ needs a master/local interface card — same hardware gate as EtherCAT/PROFINET-RT |
| **CC-Link IE Control / Field** (2007+) | 1 Gbps Ethernet (dedicated) | L2 frames via **dedicated ASIC/FPGA** | ❌ ASIC required to join; L2-only |
| **CC-Link IE Field Basic** | standard 100M Ethernet | **software-only cyclic over standard UDP** ([CLPA](https://www.cc-link.org/en/cclink/cclinkie/cclinkie_f_b.html)) | ⚠️ joining = master/slave role (write-side, out of our lane); passive mirror-port observation `待核实` |
| **CC-Link IE TSN** (2018+) | standard Ethernet + TSN (802.1AS/Qbv), L2 TSN + standard L3–7 ([CLPA](https://www.cc-link.org/en/networktechnology/features/cclinkietsn/index.html)) | cyclic in TSN timeslots; **transient = SLMP over standard IP** | ⚠️ Class A device stations can be pure software on general-purpose Ethernet chips (CLPA ships an SDK + sample code) — but joining the network is a *device* role, not a tap |
| **SLMP** (the family's application protocol) | any Ethernet | client/server messaging, TCP or UDP | ✅ **plain client reads — this is our lane** |

The load-bearing fact ([CLPA SLMP page](https://www.cc-link.org/en/cclink/slmp/index.html)):
**SLMP's message format is the same as the MC-protocol QnA-compatible 3E frame** (and 4E → SLMP
"MT"; 1E → A-compatible). SLMP is what CC-Link IE TSN uses for transient/acyclic communication,
and it is served by the master PLC's ordinary Ethernet port. iaiops's existing `mc` connector
(`pymcprotocol`, pure Python, 3E binary) already speaks exactly this format — the connector's own
error text has said "the MC 3E binary 'SLMP/MC' server" since it shipped.

## 2. The route that fits iaiops (and the ones that don't)

**✅ Recommended: read *through* the master, not *on* the wire.** In the dominant deployments the
CC-Link / CC-Link IE / TSN master is a Mitsubishi PLC (iQ-R / iQ-F / L / Q). Everything the network
carries is already mirrored into the master's address space:

- **link devices** — remote inputs/outputs RX/RY and link registers RWr/RWw are refreshed into the
  PLC's B/W (or X/Y/D…) devices by the project's *refresh parameters*;
- **network health** — link special relays/registers **SB/SW** expose per-station data-link
  status, error codes, and own/other-station diagnostics.

A read-first SLMP/MC client polling those devices gives cross-station process data **and** network
RCA evidence with zero new hardware, zero network membership, zero conformance obligations — the
exact pattern of every other iaiops connector. Because the refresh assignment is per-project
configuration, the concrete register map ships as a **documented default template, `待核实` per
site** — same discipline as the PROFINET/HART templates already in `docs/ROADMAP.md`.

**❌ Rejected: implementing a CC-Link network role.** Master/slave cyclic stacks (classic serial,
IE Field Basic software master, TSN Class A device) all mean *participating* in the control
network — write-side risk posture, conformance-test surface, and for classic/IE non-Basic variants
dedicated silicon. Wrong lane for a governed read tap.

**⚠️ Parked (`待核实`): passive observation.** IE Field Basic cyclic is plain UDP and TSN L3–7 is
standard Ethernet, so a mirror-port decoder is *conceivable* — but it needs switch cooperation,
frame-format documentation beyond the public SLMP spec, and it breaks the "poll, don't sniff"
operational model. Revisit only on concrete demand.

## 3. Library landscape

| Library | Status | Fit |
|---|---|---|
| **pymcprotocol** (already pinned by `mc`) | pure Python, 3E binary; in-tree, tested | ✅ sufficient for the recommended route (SLMP ST = 3E) |
| [PySLMPClient](https://github.com/masahase0117/PySLMPClient) | pure Python, BSD-3, **stale** (1 release, 2020) | reference only |
| slmpclient (PyPI) | wraps a C SLMP packet library | ❌ non-pure dependency, no need |
| CLPA CC-Link IE TSN SDK / sample code | C, for building *device stations* | ❌ device role, not our lane |

No new dependency is required. Full SLMP command-code coverage beyond what `pymcprotocol` exposes
(e.g. NodeSearch discovery, self-test) is `待核实` against the CLPA SLMP spec (BAP-C0401 — the
previously public PDF URL now 404s; the spec is downloadable from
[CLPA downloads](https://www.cc-link.org/en/downloads/), open to non-members).

## 4. Licensing / IP position (honest)

- The SLMP specification is **downloadable from CLPA including by non-members**, and development /
  sales rights and conformance testing are open to non-members ([CLPA conformance](https://www.cc-link.org/en/development/conformance/index.html)).
- A read-only SLMP *client* is the same legal posture as our MC/S7/FINS connectors: we implement a
  published wire protocol as a diagnostic client. We do **not** claim "CC-Link compatible product",
  do not use CLPA certification marks, and never say *certified* — material says
  **"reads CC-Link link data and network diagnostics via the master PLC (SLMP)"**.
- CC-Link / CC-Link IE / SLMP / CLPA are open-standard names (same tier as PROFINET/BACnet already
  in-repo) — safe under the brand-isolation 铁律, and they stay inside this doc + the eventual
  connector, per the rule.

## 5. Proposed shape (when we build it)

Phase 1 — **extend `mc`, no new connector** — ✅ **SHIPPED 2026-07-15**
(`iaiops/connectors/mc/cclink.py` + three governed `[READ]` tools in the factory edition):
1. **`mc_cclink_templates` / `mc_cclink_link_read`** — named refresh-layout templates
   (`cclink_classic_default`: RX→X1000/RY→Y1000/RWr→W0/RWw→W100; `cclink_ie_field_default`:
   RX→B0/RY→B1000/RWr→W0/RWw→W1000; both `待核实` per project) with per-project head-device
   overrides (`{"rx": "X1200", "rwr": "W200:8"}`), following the Modbus template pattern.
2. **`mc_cclink_network_health`** — reads the master's link special registers and decodes one
   row per station: classic `SW0080–0083` (verified addresses, QJ61BT11N manual); IE Field
   `SB0049` own-station error + `SW00B0–B7` per-station + `SW00A0–A7` baton pass (verified,
   Mitsubishi IE Field manuals). Bit semantics 0=normal / 1=error. Mock-tested against a
   faked pymcprotocol client (`tests/test_mc_cclink.py`); **live pass on a real master
   `待核实`**.
3. Support rows: library pin `pymcprotocol` (unchanged), spec = SLMP/MC 3E, vendor coverage =
   Mitsubishi masters (iQ-R/iQ-F/L/Q), transport = TCP/UDP Ethernet, self-test = mock CI (live
   `待核实`).

Phase 2 — only on market pull: a named `cclink` menu profile / edition wiring, TSN NodeSearch
discovery, IE-TSN-specific diagnostics — each row `待核实` until live-verified.

**Verification plan:** GX Works3 simulator SLMP behaviour `待核实`; a real FX5/iQ-R master with a
CC-Link IE (TSN) segment is the honest target — candidate for the field-testing call
(issue #28). No live pass exists today; nothing in this doc claims one.

## 6. Sources

- CLPA — [SLMP overview](https://www.cc-link.org/en/cclink/slmp/index.html) (SLMP ↔ MC 3E/4E frame equivalence)
- CLPA — [CC-Link IE Field Basic](https://www.cc-link.org/en/cclink/cclinkie/cclinkie_f_b.html) (software-only cyclic over standard UDP)
- CLPA — [CC-Link IE TSN](https://www.cc-link.org/en/networktechnology/features/cclinkietsn/index.html) (TSN L2 + standard L3–7; SLMP transient)
- CLPA — [TSN Class A sample code](https://www.cc-link.org/en/cclink/cclinkie/code_cclinkie_tsn.html) + [development flow](https://www.cc-link.org/en/support/cclinkie_tsn_flow/index.html) (software device stations on general-purpose Ethernet)
- CLPA — [conformance test](https://www.cc-link.org/en/development/conformance/index.html) (open to non-members)
- Mitsubishi — [CC-Link IE Field Basic concept](https://www.mitsubishielectric.com/fa/products/cnt/plcnet/pmerit/cclink_ie/basic/concept/index.html)
- [PySLMPClient](https://github.com/masahase0117/PySLMPClient) · [pymcprotocol](https://pypi.org/project/pymcprotocol/)
