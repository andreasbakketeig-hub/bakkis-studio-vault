"""
Exports: printable HTML checklist, checklist CSV and snapshot inventory CSV.

Everything is written to a file the user picks. The HTML is self-contained
(inline CSS, no scripts, no remote resources) so it prints and opens offline.
CSV cells that a spreadsheet would treat as a formula are neutralised.
"""

from __future__ import annotations

import csv
import datetime
import html
from pathlib import Path

from studio_vault import APP_NAME, __version__
from studio_vault.checklist import (
    STATUS_INSTALLED,
    STATUS_PARTIAL,
    Checklist,
    ChecklistItem,
    VendorGroup,
)
from studio_vault.snapshot import Snapshot

_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def csv_cell(value: object) -> str:
    """Stringify and guard against spreadsheet formula injection."""
    text = "" if value is None else str(value)
    return "'" + text if text.startswith(_FORMULA_PREFIXES) else text


def _write_csv(dest: Path, header: list[str], rows: list[list[object]]) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("w", newline="", encoding="utf-8-sig") as fh:  # BOM so Excel reads UTF-8
        writer = csv.writer(fh)
        writer.writerow(header)
        writer.writerows([[csv_cell(c) for c in row] for row in rows])
    return dest


def _pretty_date(iso: str) -> str:
    try:
        return datetime.datetime.fromisoformat(iso).strftime("%d %b %Y, %H:%M")
    except ValueError:
        return iso


def item_status_text(item: ChecklistItem) -> str:
    if item.status == STATUS_INSTALLED:
        return "Installed"
    if item.manual_done:
        return "Done (ticked)"
    if item.status == STATUS_PARTIAL:
        return f"Partly installed — missing {', '.join(item.missing_formats)}"
    return "Missing"


# ── CSV ───────────────────────────────────────────────────────────────────────

def checklist_csv(checklist: Checklist, dest: Path) -> Path:
    rows: list[list[object]] = []
    for g in checklist.groups:
        for i in g.items:
            rows.append([g.name, i.kind, i.name, i.version, " ".join(i.formats), item_status_text(i),
                         g.manager_app, g.license_system, g.download_url])
    for i in checklist.hardware:
        rows.append([i.vendor, i.kind, i.name, "", "", item_status_text(i), "", "", i.download_url])
    for i in checklist.content:
        rows.append(["", i.kind, i.name, "", i.category, item_status_text(i), "", "", ""])
    return _write_csv(dest, ["Vendor", "Type", "Name", "Old version", "Formats", "Status",
                             "Installer app", "License", "Download"], rows)


def inventory_csv(snapshot: Snapshot, dest: Path) -> Path:
    rows: list[list[object]] = []
    for p in snapshot.plugins:
        rows.append(["Plug-in", p.name, p.developer, p.version, p.fmt, p.size, p.path])
    for a in snapshot.apps:
        rows.append(["App", a.name, a.developer, a.version, a.category, "", a.path])
    for h in snapshot.hardware:
        rows.append(["Hardware", h.name, h.vendor, "", h.device_type, "", h.details or h.connection_type])
    return _write_csv(dest, ["Type", "Name", "Vendor", "Version", "Format / category",
                             "Size (bytes)", "Path / connection"], rows)


# ── HTML ──────────────────────────────────────────────────────────────────────

_CSS = """
:root { --ink:#16181d; --muted:#5b6170; --line:#dde0e6; --ok:#137a4b; --warn:#a15c00; --bad:#b42318; }
* { box-sizing:border-box; }
body { font:13px/1.45 -apple-system, BlinkMacSystemFont, "Helvetica Neue", sans-serif;
       color:var(--ink); background:#fff; margin:32px auto; max-width:900px; padding:0 16px; }
h1 { font-size:22px; margin:0 0 4px; }
h2 { font-size:15px; margin:0; }
.meta, .muted { color:var(--muted); }
.progress { margin:16px 0 24px; font-weight:600; }
section { border:1px solid var(--line); border-radius:8px; padding:12px 16px; margin:0 0 12px;
          break-inside:avoid; }
.head { display:flex; justify-content:space-between; gap:16px; align-items:baseline; }
.step { margin:6px 0 8px; }
.facts { color:var(--muted); font-size:12px; margin-bottom:6px; }
.facts a { color:inherit; }
ul { list-style:none; margin:0; padding:0; }
li { display:flex; gap:10px; padding:4px 0; border-top:1px solid var(--line); }
li:first-child { border-top:0; }
.box { width:14px; height:14px; border:1.5px solid var(--muted); border-radius:3px; flex:none; margin-top:2px;
       text-align:center; line-height:11px; font-size:11px; }
.done .box { border-color:var(--ok); color:var(--ok); }
.name { flex:1; }
.st { font-size:12px; white-space:nowrap; }
.st.ok { color:var(--ok); } .st.part { color:var(--warn); } .st.miss { color:var(--bad); }
footer { margin-top:24px; color:var(--muted); font-size:11px; }
@media print { body { margin:0 auto; } a { text-decoration:none; } }
"""


def _e(text: object) -> str:
    return html.escape("" if text is None else str(text), quote=True)


def _item_html(item: ChecklistItem) -> str:
    detail = []
    if item.version:
        detail.append(f"v{item.version}")
    if item.formats:
        detail.append(" · ".join(item.formats))
    if item.category:
        detail.append(item.category)
    css = "ok" if item.done else ("part" if item.status == STATUS_PARTIAL else "miss")
    return (
        f'<li class="{"done" if item.done else ""}">'
        f'<span class="box">{"✓" if item.done else ""}</span>'
        f'<span class="name">{_e(item.name)} <span class="muted">{_e(" — ".join(detail))}</span></span>'
        f'<span class="st {css}">{_e(item_status_text(item))}</span></li>'
    )


def _group_html(group: VendorGroup) -> str:
    facts = []
    if group.manager_app:
        facts.append(f"Installer: {_e(group.manager_app)}")
    if group.license_system:
        facts.append(f"License: {_e(group.license_system)}")
    if group.download_url:
        facts.append(f'<a href="{_e(group.download_url)}">{_e(group.download_url)}</a>')
    return (
        f'<section><div class="head"><h2>{_e(group.name)}</h2>'
        f'<span class="muted">{group.done_count} / {len(group.items)}</span></div>'
        f'<div class="step">{_e(group.next_step)}</div>'
        f'<div class="facts">{" · ".join(facts)}</div>'
        f'<ul>{"".join(_item_html(i) for i in group.items)}</ul></section>'
    )


def _hardware_html(items: list[ChecklistItem]) -> str:
    if not items:
        return ""
    rows = []
    for i in items:
        link = f' <a class="muted" href="{_e(i.download_url)}">drivers</a>' if i.download_url else ""
        rows.append(_item_html(i).replace('</span></span><span class="st',
                                          f'</span>{link}</span><span class="st', 1))
    return (
        '<section><div class="head"><h2>Hardware</h2>'
        f'<span class="muted">{sum(1 for i in items if i.done)} / {len(items)}</span></div>'
        '<div class="step">Connect each device and install its driver or control app.</div>'
        f'<ul>{"".join(rows)}</ul></section>'
    )


def _content_html(items: list[ChecklistItem]) -> str:
    if not items:
        return ""
    rows = "".join(
        f'<li class="{"done" if i.done else ""}"><span class="box">{"✓" if i.done else ""}</span>'
        f'<span class="name">{_e(i.name)} <span class="muted">— {_e(i.category)}</span></span>'
        f'<span class="st {"ok" if i.done else "miss"}">{"Back" if i.done else "Copy back"}</span></li>'
        for i in items)
    return (
        '<section><div class="head"><h2>Presets and your own content</h2>'
        f'<span class="muted">{sum(1 for i in items if i.done)} / {len(items)}</span></div>'
        '<div class="step">Copy these folders back from your backup (Migration Assistant or Time Machine can do it).</div>'
        f'<ul>{rows}</ul></section>'
    )


def checklist_html(checklist: Checklist) -> str:
    title = f"New Mac checklist — {checklist.source_name}"
    pct = round(100 * checklist.done_count / checklist.total) if checklist.total else 100
    return (
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        f"<title>{_e(title)}</title><style>{_CSS}</style></head><body>"
        f"<h1>{_e(title)}</h1>"
        f'<div class="meta">From the snapshot taken {_e(_pretty_date(checklist.source_created_at))}'
        f" · made {_e(datetime.datetime.now().strftime('%d %b %Y'))}</div>"
        f'<div class="progress">{checklist.done_count} of {checklist.total} done ({pct}%)</div>'
        + "".join(_group_html(g) for g in checklist.groups)
        + _hardware_html(checklist.hardware)
        + _content_html(checklist.content)
        + f"<footer>{_e(APP_NAME)} {_e(__version__)} · Read-only: nothing on your Mac was changed."
        " License keys are never included in this report.</footer></body></html>"
    )


def write_checklist_html(checklist: Checklist, dest: Path) -> Path:
    if dest.suffix.lower() not in (".html", ".htm"):
        dest = dest.with_name(dest.name + ".html")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(checklist_html(checklist), encoding="utf-8")
    return dest
