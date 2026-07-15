<!-- Design note + operator guide — running the full iaiops diagnostic path with ZERO cloud
     egress: offline install, on-box LLM narration, and how to verify nothing leaves the plant.
     Same honesty discipline as the rest of the repo: live-hardware rows stay 待核实 until a
     real pass is recorded. -->

# Air-gapped operation — the on-box LLM brain option

> **TL;DR（中文）** — iaiops 的诊断路径可以**完全不出厂**：RCA 核心是确定性纯 Python（根本不需要
> LLM）；可选的自然语言叙述用**厂内本地模型**（Ollama）完成；安装用离线 wheelhouse；镜像/应用包
> 均有签名可离线校验。本文是完整的气隙部署指南：分层架构、离线装机、离线模型供应、旁路 compose、
> 以及如何**验证零外联**。

## 1. What runs where — three tiers, only one of them needs a model

| Tier | What | Needs an LLM? | Status |
|---|---|---|---|
| **1. Diagnosis** | Protocol tap → normalize → govern → deterministic RCA (noisy-OR + temporal weighting + citations; `docs/RCA.md`) | **No.** Pure Python, works with zero egress by construction | ✅ shipped |
| **2. Narration** | `rca_narrate` MCP tool → on-box Ollama rephrases the **already-cited** verdict in plain language | Yes — **local** (`iaiops[ollama]` extra) | ✅ shipped (mock-tested; live Ollama pass `待核实`) |
| **3. Copilot** | An MCP-capable agent *driving* the governed tools end-to-end with a local model | Yes — local MCP client + local model | ⏳ pattern documented below; no client is pinned or endorsed (`待核实`) |

The load-bearing property is the **boundary** (see `docs/RCA.md`): the model — local or not — only
*narrates* a verdict the deterministic core already produced and cited. It never derives causes,
invents citations, or scores confidence. A small on-box model is therefore *sufficient*: narration
is a short-context, single-turn rephrasing task, not reasoning.

## 2. Offline install (wheelhouse)

Same flow as `docs/CHINA.md` §2 — build a wheelhouse on a connected host that matches the target
OS + CPU arch + Python, move it by approved transfer, install with `--no-index`:

```bash
# Connected staging host — add the ollama extra for Tier 2:
pip download "iaiops[factory,ollama]" -d ./wheelhouse

# Air-gapped host:
pip install --no-index --find-links ./wheelhouse "iaiops[factory,ollama]"
```

Container route instead: pull + `cosign verify` the signed per-edition image on the staging host
(`deploy/margo/README.md`), `docker save` → transfer → `docker load` on the air-gapped host.

## 3. Offline model provisioning (Ollama)

The Ollama container/daemon on the air-gapped host **never needs internet**. Provision models the
same way as wheels:

```bash
# Connected staging host (same CPU arch as the target):
ollama pull qwen3:8b                       # or any local model your hardware fits
# Models live under ~/.ollama (or $OLLAMA_MODELS). Copy that directory by approved transfer.

# Air-gapped host: place it where the runtime expects it —
#   bare-metal:  ~/.ollama            (or point $OLLAMA_MODELS at it)
#   compose:     the `ollama-models` volume in deploy/airgap/compose.yaml
ollama list                                # must show the model without any network access
```

Alternative for GGUF files obtained through your artifact pipeline: `ollama create <name> -f
Modelfile` (a `Modelfile` with `FROM ./model.gguf`) — also fully offline.

**Model sizing (guidance, not benchmarks — real numbers per box are `待核实`):** narration is a
single short completion over a small JSON verdict, so quantized 3–8B-class models are the sensible
starting point on CPU-only edge hardware; larger models buy fluency, not correctness — correctness
comes from the cited verdict underneath. Set a longer `timeout_s` on slow CPUs.

## 4. Side-by-side deployment (compose)

`deploy/airgap/compose.yaml` runs the signed iaiops image next to a pinned Ollama on the same box:

- the LLM sits on an **internal-only network** — no gateway, no published ports; only iaiops can
  reach it (`http://ollama:11434`);
- iaiops keeps the hardened posture (non-root, read-only rootfs, `cap_drop: ALL`) and exposes one
  loopback-bound MCP port;
- the OT side stays strictly **outbound** to the endpoints in `config.yaml`.

```bash
docker compose -f deploy/airgap/compose.yaml up
# Then, from your MCP client, narrate a verdict via the on-box model:
#   rca_narrate(verdict=<downtime_root_cause output>, base_url="http://ollama:11434", model="qwen3:8b")
```

`rca_narrate` defaults to `http://localhost:11434` (bare-metal layout); pass `base_url` explicitly
in the compose layout above.

## 5. Tier 3 — a fully local copilot

iaiops is a standard MCP server (stdio or socket transport, `deploy/margo/README.md`), so the agent
that *drives* the tools can itself be local: any MCP-capable client wired to an on-box model gives a
plant-floor copilot with zero egress. iaiops deliberately does **not** pin or endorse a client — the
tool surface is client-agnostic, and client maturity for local models varies. Record your own pass:
which client, which model, which edition profile — a `待核实 → verified` row like every hardware
pass in `docs/ROADMAP.md`.

## 6. Verifying zero egress — don't trust, check

1. **Audit chain** — every governed tool call is recorded (`iaiops audit …`); the record includes
   the target endpoint. Anything talking to a non-OT address shows up here first.
2. **Network posture** — on the container route, the LLM network is `internal: true` (kernel-level:
   no gateway); iaiops publishes exactly one loopback MCP port. Host firewall: default-deny egress,
   allow only the configured OT endpoint CIDRs.
3. **Observe it** — during an `rca_narrate` call, watch conntrack/pcap on the uplink: the only
   flows are MCP-client→loopback and iaiops→OT endpoints. A live recorded pass on real gear is
   `待核实` — record it like every other hardware row.
4. **Secrets** — values never travel in descriptors or deployment specs (reference model,
   `deploy/margo/margo.yaml`); the encrypted store lives on-box under `IAIOPS_HOME`.

## 7. Honest status

- Tier 1 (deterministic diagnosis, zero egress): property of the architecture, covered by the
  normal test suite. ✅
- Tier 2 (`rca_narrate` → local Ollama): shipped + mock-tested; **a live pass against a real
  Ollama server on real edge hardware is `待核实`** (`iaiops/core/llm/ollama.py` says the same).
- Tier 3 (fully local copilot): documented pattern only — **no verified client/model pairing yet**
  (`待核实`).
- No latency/throughput numbers are claimed anywhere in this document on purpose.
