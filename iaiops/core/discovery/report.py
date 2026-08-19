"""The scan report — one self-contained HTML file, and what it puts first.

The section order is the argument. Most scanners open with findings; this one
opens with **what it did**, because the reader of a first survey is usually the
person who has to defend having let it run. "We made 1,524 TCP connections and
12 Modbus device-ID requests, and here is everything we did not do" is checkable
against a packet capture. "The scan was safe" is not.

So: header → **what we touched** → devices → diagnosis → appendix. The trust
page is section one and cannot be moved by configuration.

Two constraints are load-bearing and both are tested:

* **Zero network requests.** No CDN, no web font, no remote image, no fetch. The
  file opens on an air-gapped laptop in a plant office and renders identically.
  A report that phoned home to render would contradict the product.
* **Everything is escaped.** A vendor string is whatever the *device* said, and
  a device on an unknown network is not a trusted source. An OPC-UA
  ApplicationName is free text; so is a Modbus vendor field. Rendering either
  unescaped would turn a survey of a hostile network into script execution on
  the surveyor's laptop.
"""

from __future__ import annotations

import html
import json
from typing import Any

from iaiops.core.discovery import wirelog
from iaiops.core.discovery.types import ScanResult

_VERDICT_TEXT = {
    "ok": ("ok", "Industrial devices were identified."),
    "partial": (
        "partial",
        "Hosts are present, but no industrial protocol was confirmed on any of them.",
    ),
    "no_devices_found": ("none", "Nothing answered. See the diagnosis below before re-running."),
    "aborted_unhealthy_segment": (
        "aborted",
        "The run stopped early because the segment was failing. Results are incomplete.",
    ),
}

_CSS = """
:root {
  --bg:#f7f7f5; --fg:#16181d; --muted:#5c6270; --line:#dcdcd6; --card:#fff;
  --ok:#1a7f4b; --warn:#8a5a00; --bad:#a3262c; --accent:#1f4e79; --code:#f0f0ec;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg:#14161a; --fg:#e8e8e4; --muted:#9aa0ac; --line:#2c3038; --card:#1b1e24;
    --ok:#4cc38a; --warn:#d6a34a; --bad:#e5757c; --accent:#7fb3e0; --code:#22262e;
  }
}
* { box-sizing:border-box; }
body {
  margin:0; padding:2rem 1.25rem 4rem; background:var(--bg); color:var(--fg);
  font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,
       "Helvetica Neue",Arial,sans-serif;
}
.wrap { max-width:1100px; margin:0 auto; }
h1 { font-size:1.5rem; margin:0 0 .25rem; }
h2 { font-size:1.1rem; margin:2.5rem 0 .75rem; padding-bottom:.4rem;
     border-bottom:1px solid var(--line); }
h3 { font-size:.95rem; margin:1.5rem 0 .5rem; color:var(--muted); font-weight:600; }
.sub { color:var(--muted); margin:0 0 1.5rem; }
.card { background:var(--card); border:1px solid var(--line); border-radius:8px;
        padding:1rem 1.15rem; }
.grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(190px,1fr)); gap:.9rem; }
.kv { font-size:.85rem; }
.kv dt { color:var(--muted); font-size:.75rem; text-transform:uppercase; letter-spacing:.04em; }
.kv dd { margin:.15rem 0 0; font-weight:600; word-break:break-word; }
.badge { display:inline-block; padding:.15rem .55rem; border-radius:999px; font-size:.75rem;
         font-weight:700; border:1px solid currentColor; }
.badge.ok{color:var(--ok)} .badge.partial{color:var(--warn)}
.badge.none{color:var(--muted)} .badge.aborted{color:var(--bad)}
table { width:100%; border-collapse:collapse; font-size:.85rem; }
.scroll { overflow-x:auto; border:1px solid var(--line); border-radius:8px;
          background:var(--card); }
th,td { padding:.5rem .7rem; text-align:left; border-bottom:1px solid var(--line);
        white-space:nowrap; }
th { background:var(--code); font-size:.72rem; text-transform:uppercase; letter-spacing:.04em;
     color:var(--muted); cursor:pointer; user-select:none; position:sticky; top:0; }
th[data-sort]:after { content:" \\2195"; opacity:.35; }
tbody tr:last-child td { border-bottom:none; }
tbody tr:hover { background:var(--code); }
td.blank { color:var(--muted); }
ul.never { list-style:none; padding:0; margin:.5rem 0 0; }
ul.never li { padding:.3rem 0 .3rem 1.5rem; position:relative; font-size:.87rem; }
ul.never li:before { content:"\\2717"; position:absolute; left:.25rem;
                     color:var(--ok); font-weight:700; }
ul.notes { margin:.5rem 0 0; padding-left:1.2rem; font-size:.88rem; }
ul.notes li { margin:.35rem 0; }
input[type=search] { width:100%; max-width:340px; padding:.45rem .6rem; margin-bottom:.75rem;
  border:1px solid var(--line); border-radius:6px; background:var(--card);
  color:var(--fg); font-size:.85rem; }
pre { background:var(--code); border:1px solid var(--line); border-radius:8px; padding:.9rem;
      overflow-x:auto; font-size:.78rem; line-height:1.45; }
code { font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace; }
.mono { font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace; }
.foot { margin-top:3rem; padding-top:1rem; border-top:1px solid var(--line);
        color:var(--muted); font-size:.78rem; }
.empty { color:var(--muted); font-style:italic; padding:1rem 0; }
"""

_JS = """
(function () {
  var box = document.getElementById('filter');
  var table = document.getElementById('devices');
  if (!table) return;
  var body = table.tBodies[0];
  var rows = Array.prototype.slice.call(body.rows);

  if (box) {
    box.addEventListener('input', function () {
      var q = box.value.toLowerCase();
      var shown = 0;
      rows.forEach(function (row) {
        var hit = !q || row.textContent.toLowerCase().indexOf(q) !== -1;
        row.hidden = !hit;
        if (hit) shown++;
      });
      var count = document.getElementById('shown');
      if (count) count.textContent = shown + ' of ' + rows.length + ' shown';
    });
  }

  var dir = {};
  Array.prototype.forEach.call(table.tHead.rows[0].cells, function (th, index) {
    if (!th.hasAttribute('data-sort')) return;
    th.addEventListener('click', function () {
      dir[index] = !dir[index];
      var numeric = th.getAttribute('data-sort') === 'num';
      var sorted = rows.slice().sort(function (a, b) {
        var x = a.cells[index].getAttribute('data-key') || a.cells[index].textContent;
        var y = b.cells[index].getAttribute('data-key') || b.cells[index].textContent;
        var out = numeric ? (parseFloat(x) || 0) - (parseFloat(y) || 0)
                          : x.localeCompare(y, undefined, { numeric: true });
        return dir[index] ? out : -out;
      });
      sorted.forEach(function (row) { body.appendChild(row); });
    });
  });
})();
"""


def _e(value: Any) -> str:
    """Escape for HTML text. Every device-supplied string goes through this."""
    return html.escape("" if value is None else str(value), quote=True)


def _cell(value: Any, key: str | None = None) -> str:
    text = "" if value is None else str(value)
    attrs = f' data-key="{_e(key)}"' if key is not None else ""
    if not text.strip():
        return f'<td class="blank"{attrs}>—</td>'
    return f"<td{attrs}>{_e(text)}</td>"


def _kv(label: str, value: Any) -> str:
    return f"<div class='kv'><dt>{_e(label)}</dt><dd>{_e(value) or '—'}</dd></div>"


def _header(record: dict[str, Any]) -> str:
    key, explanation = _VERDICT_TEXT.get(
        record.get("verdict", ""), ("none", "Outcome not recorded.")
    )
    scope = record.get("scope") or {}
    targets = ", ".join(list(scope.get("cidrs") or []) + list(scope.get("hosts") or [])) or "—"
    approver = record.get("approved_by") or ""
    ticket = record.get("ticket") or ""
    authorization = (
        f"{approver} ({ticket})" if approver and ticket else (approver or "not recorded")
    )
    return f"""
<h1>Site survey — {_e(record.get("site") or "unnamed site")}</h1>
<p class="sub">{_e(explanation)}</p>
<div class="card">
  <dl class="grid" style="margin:0">
    <div class="kv"><dt>Verdict</dt><dd><span class="badge {key}">{_e(key)}</span></dd></div>
    {_kv("Profile", record.get("profile"))}
    {_kv("Started", record.get("started_at"))}
    {_kv("Finished", record.get("finished_at"))}
    {_kv("Scope", targets)}
    {_kv("Authorized by", authorization)}
    {_kv("Hosts seen", record.get("host_count"))}
    {_kv("Devices identified", record.get("device_count"))}
    {_kv("Stages run", ", ".join(record.get("stages") or []))}
  </dl>
</div>
"""


def _trust(record: dict[str, Any]) -> str:
    """Section one. What went on the wire, and the list of what never does."""
    summary = record.get("wire_summary") or {}
    total = sum(summary.values())
    if summary:
        rows = "\n".join(
            f"<tr>{_cell(kind)}<td>{count:,}</td>"
            f"{_cell(wirelog.KNOWN_KINDS.get(kind, 'undeclared packet class'))}</tr>"
            for kind, count in sorted(summary.items())
        )
        counts = f"""
<div class="scroll">
<table><thead><tr><th>Packet class</th><th>Count</th><th>What it is</th></tr></thead>
<tbody>{rows}</tbody></table></div>"""
    else:
        counts = (
            '<p class="empty">Nothing was emitted. This survey read only local state '
            "(the kernel ARP cache and any inventory you imported).</p>"
        )
    never = "\n".join(f"<li>{_e(item)}</li>" for item in wirelog.NEVER_DONE)
    return f"""
<h2>1 &middot; What this scan touched</h2>
<p class="sub" style="margin-bottom:.9rem">
  {total:,} request{"" if total == 1 else "s"} in total. These counts include requests that
  failed — the packet went out either way — and every class below is declared in the tool
  before it can be sent, so this table is checkable against a packet capture.
</p>
{counts}
<h3>And what it never does</h3>
<div class="card"><ul class="never">{never}</ul></div>
"""


_COLUMNS = (
    ("Address", "text", "ip"),
    ("MAC", "text", "mac"),
    ("Protocol", "text", "confirmed"),
    ("Vendor", "text", "vendor"),
    ("Model", "text", "model"),
    ("Serial", "text", "serial"),
    ("Firmware", "text", "firmware"),
    ("Name", "text", "name"),
    ("Open ports", "text", "open_ports"),
    ("Seen via", "text", "sources"),
    ("Identity from", "text", "identity_from"),
)


def _devices(record: dict[str, Any]) -> str:
    hosts = record.get("hosts") or []
    if not hosts:
        return (
            '<h2>2 &middot; Devices</h2><p class="empty">No host produced any response. '
            "The diagnosis below explains what that means.</p>"
        )
    head = "".join(f'<th data-sort="{kind}">{_e(label)}</th>' for label, kind, _ in _COLUMNS)
    rows = []
    for host in hosts:
        cells = []
        for _, _, field in _COLUMNS:
            value = host.get(field)
            if isinstance(value, list):
                value = ", ".join(str(v) for v in value)
            cells.append(_cell(value, key=_sort_key(field, host)))
        rows.append(f"<tr>{''.join(cells)}</tr>")
    return f"""
<h2>2 &middot; Devices</h2>
<input type="search" id="filter" placeholder="Filter — address, vendor, protocol&hellip;"
       aria-label="Filter devices">
<p class="sub" id="shown" style="margin:0 0 .6rem;font-size:.8rem">{len(hosts)} host(s)</p>
<div class="scroll">
<table id="devices"><thead><tr>{head}</tr></thead><tbody>
{chr(10).join(rows)}
</tbody></table></div>
<p class="sub" style="margin-top:.6rem;font-size:.8rem">
  A blank cell means the device did not report that field. It is never filled by inference.
  &ldquo;Identity from&rdquo; names the one protocol that supplied this row&rsquo;s identity —
  where a host speaks two, the rest is in the appendix rather than merged into a device that
  does not exist.
</p>
"""


def _sort_key(field: str, host: dict[str, Any]) -> str | None:
    """Numeric-friendly sort key for addresses; plain text elsewhere."""
    if field != "ip":
        return None
    parts = str(host.get("ip", "")).split(".")
    if len(parts) == 4 and all(p.isdigit() for p in parts):
        return ".".join(p.zfill(3) for p in parts)
    return str(host.get("ip", ""))


def _diagnosis(record: dict[str, Any]) -> str:
    notes = record.get("notes") or []
    errors = [
        (host.get("ip", ""), error)
        for host in (record.get("hosts") or [])
        for error in (host.get("errors") or [])
    ]
    if not notes and not errors:
        return ""
    parts = ["<h2>3 &middot; Diagnosis</h2>"]
    if notes:
        items = "\n".join(f"<li>{_e(note)}</li>" for note in notes)
        parts.append(f'<div class="card"><ul class="notes">{items}</ul></div>')
    if errors:
        rows = "\n".join(f"<tr>{_cell(ip)}{_cell(error)}</tr>" for ip, error in errors[:200])
        parts.append(
            "<h3>Per-host detail</h3>"
            '<div class="scroll"><table><thead><tr><th>Address</th><th>What happened</th>'
            f"</tr></thead><tbody>{rows}</tbody></table></div>"
        )
    return "\n".join(parts)


def _appendix(record: dict[str, Any]) -> str:
    payload = {
        "scan_id": record.get("scan_id"),
        "scope": record.get("scope"),
        "stages": record.get("stages"),
        "wire_summary": record.get("wire_summary"),
        "hosts": [
            {
                "ip": host.get("ip"),
                "ports": host.get("ports"),
                "protocols": host.get("protocols"),
                "identity": host.get("identity"),
            }
            for host in (record.get("hosts") or [])
        ],
    }
    blob = json.dumps(payload, indent=2, sort_keys=True, default=str)
    return f"""
<h2>4 &middot; Appendix — the full record</h2>
<p class="sub" style="margin-bottom:.7rem">
  Everything observed, including the per-protocol identity that the table above deliberately
  does not merge. This is the same data the on-box store holds.
</p>
<pre><code>{_e(blob)}</code></pre>
"""


def render_html(record: dict[str, Any]) -> str:
    """Render a stored scan (as returned by ``load_scan``) to one HTML file."""
    site = _e(record.get("site") or "site survey")
    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Site survey — {site}</title>
<style>{_CSS}</style>
</head><body><div class="wrap">
{_header(record)}
{_trust(record)}
{_devices(record)}
{_diagnosis(record)}
{_appendix(record)}
<p class="foot">
  Generated by iaiops. This file is self-contained: it loads no fonts, scripts, styles or
  images from anywhere, and makes no network request when opened. Scan id
  <span class="mono">{_e(record.get("scan_id") or "unstored")}</span>.
</p>
</div><script>{_JS}</script></body></html>
"""


def render_result(result: ScanResult) -> str:
    """Render a scan that has not been stored, without touching a database."""
    from iaiops.core.sink.scan_store import host_to_dict, scan_id_for

    return render_html(
        {
            "scan_id": scan_id_for(result),
            "site": result.plan.site,
            "started_at": result.started_at,
            "finished_at": result.finished_at,
            "profile": result.plan.profile,
            "verdict": result.verdict,
            "stages": list(result.plan.stages),
            "scope": {
                "cidrs": list(result.plan.cidrs),
                "hosts": list(result.plan.hosts),
                "excluded": list(result.plan.excluded),
            },
            "approved_by": result.plan.authorization.approved_by,
            "ticket": result.plan.authorization.ticket,
            "wire_summary": dict(result.wire_summary),
            "notes": list(result.notes),
            "host_count": len(result.hosts),
            "device_count": len(result.devices),
            "hosts": [host_to_dict(h) for h in result.hosts],
        }
    )


__all__ = ["render_html", "render_result"]
