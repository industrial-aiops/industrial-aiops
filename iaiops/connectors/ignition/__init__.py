"""MES/SCADA read-layer connector — vendor Gateway HTTP/web API (READ-ONLY).

Speaks the vendor SCADA/MES platform's HTTP *Gateway* web API — the MES-ish
production surface (gateway/module health, tag tree browse, current tag values,
active alarms, tag-history samples). This is deliberately NOT a second OPC-UA
connector: the platform also exposes an OPC-UA server, but that is already
covered by the base ``opcua`` connector. This layer targets the platform's
HTTP/JSON web API for the reads OPC-UA does not surface (module inventory,
alarm-journal shape, historian aggregation), behind one authenticated endpoint.

Every tool is READ-ONLY (risk=low); there are NO writes. A small per-deployment
:mod:`dialects` map (resource paths + field aliases + pure normalizers) folds the
platform's JSON shapes into a neutral schema; the client reuses the repo's shared
``requests`` stack (no new HTTP dep) with a size cap, and resolves the token/API
key from the encrypted secret store by key name. The vendor/product name stays
INSIDE this connector package + its edition tool/skill/changelog (brand-isolation
iron rule).
"""
