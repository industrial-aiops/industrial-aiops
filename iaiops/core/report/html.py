"""Shared primitives for the self-contained HTML reports.

Two constraints are load-bearing here, and both were argued for in the scan
report this module was extracted from (:mod:`iaiops.core.discovery.report`):

* **Zero network requests.** No CDN, no web font, no remote image, no fetch. The
  file opens on an air-gapped laptop in a plant office and renders identically.
  A report that phoned home to render would contradict the product.
* **Everything is escaped.** A vendor string is whatever the *device* said, and a
  tag label is whatever the site typed. Rendering either unescaped would turn a
  report about a hostile network into script execution on the reader's laptop.

Extracted rather than copied: the repo already had two report builders
(``discovery/report.py`` and ``brain/compliance_report.py``) sharing **no code**,
with two different escape helpers and two ``_cell`` functions whose contracts
disagreed. A third copy would have been the point of no return. The scan report
was the mature one — dark mode, escape-everywhere, tested self-containment — so
these came out of it, and it now imports them back.

``compliance_report.py`` is deliberately left alone: it renders Markdown first
and converts, which is a different design, and folding it in today would widen
the blast radius for no gain.
"""

from __future__ import annotations

import html
from typing import Any

CSS = """
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

JS = """
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


def escape(value: Any) -> str:
    """Escape for HTML text. Every externally-supplied string goes through this."""
    return html.escape("" if value is None else str(value), quote=True)


def cell(value: Any, key: str | None = None) -> str:
    """A table cell. Blank renders as a dash, not as the word ``None``.

    ``key`` becomes a ``data-key`` sort attribute and is escaped too — an
    unescaped attribute is a quote away from being an event handler.
    """
    text = "" if value is None else str(value)
    attrs = f' data-key="{escape(key)}"' if key is not None else ""
    if not text.strip():
        return f'<td class="blank"{attrs}>—</td>'
    return f"<td{attrs}>{escape(text)}</td>"


def kv(label: str, value: Any) -> str:
    """One metric tile in a ``<dl class="grid">``."""
    return f"<div class='kv'><dt>{escape(label)}</dt><dd>{escape(value) or '—'}</dd></div>"


def document(
    *,
    title: str,
    body: str,
    footer: str,
    lang: str = "en",
    script: str = "",
    extra_css: str = "",
) -> str:
    """One complete, standalone HTML file.

    ``script`` is opt-in: a page with no sortable table should ship no script at
    all rather than an inert one, so that "this file runs nothing" stays true by
    construction on the pages where it is true.

    **``title`` and ``lang`` are escaped here; ``body``, ``footer`` and ``script``
    are NOT.** The first three are values, the last three are already-built markup
    — a caller that escapes its own footer before passing it will double-escape,
    which is exactly what happened once and put ``&#x27;`` through a report's
    honesty section. Pass markup, not text.

    ``extra_css`` is appended rather than merged into :data:`CSS`, so a rule one
    report needs cannot change the bytes another report emits. That mattered
    immediately: the scan report's output had to stay provably identical across
    this module's extraction, and a shared stylesheet that grew for the OEE page
    would have quietly broken that proof.
    """
    tail = f"<script>{script}</script>" if script else ""
    style = CSS + extra_css
    return f"""<!doctype html>
<html lang="{escape(lang)}"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(title)}</title>
<style>{style}</style>
</head><body><div class="wrap">
{body}
<p class="foot">{footer}</p>
</div>{tail}</body></html>
"""
