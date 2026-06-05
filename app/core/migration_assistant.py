"""
Migration Assistant — snapshot, compare, and export a studio setup.

No files are modified; all operations are read-only scans or writes to
user-chosen export destinations.
"""

from __future__ import annotations

import csv
import datetime
import json
import os
import platform
import socket
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.core.scanner import Plugin
    from app.core.music_software_scanner import MusicApp

# ── Status constants ──────────────────────────────────────────────────────────

STATUS_INSTALLED    = "Installed"
STATUS_MISSING      = "Missing"
STATUS_NEEDS_REVIEW = "Needs Review"


# ── Snapshot model ────────────────────────────────────────────────────────────

@dataclass
class MigrationSnapshot:
    """Serialisable record of a studio system's installed software."""

    created_at: str          # ISO-8601 timestamp
    hostname: str
    plugins: list[dict]      # serialised Plugin dicts
    apps: list[dict]         # serialised MusicApp dicts

    # ── Derived counts ───────────────────────────────────────────────────────

    @property
    def total_plugins(self) -> int:
        return len(self.plugins)

    @property
    def total_apps(self) -> int:
        return len(self.apps)

    @property
    def plugin_products(self) -> int:
        """Unique logical products, normalised across formats."""
        seen: set[str] = set()
        for p in self.plugins:
            name = p.get("name", "")
            import re
            key = re.sub(r"[\s_\-]*(vst3?|au|aax)\s*$", "", name, flags=re.IGNORECASE).strip().lower()
            seen.add(key or name.lower())
        return len(seen)

    @property
    def plugin_formats(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for p in self.plugins:
            fmt = p.get("fmt") or "Unknown"
            counts[fmt] = counts.get(fmt, 0) + 1
        return counts

    @property
    def duplicate_format_products(self) -> int:
        """Products that appear in more than one format."""
        import re
        names: dict[str, set[str]] = {}
        for p in self.plugins:
            raw = p.get("name", "")
            key = re.sub(r"[\s_\-]*(vst3?|au|aax)\s*$", "", raw, flags=re.IGNORECASE).strip().lower()
            key = key or raw.lower()
            names.setdefault(key, set()).add(p.get("fmt", ""))
        return sum(1 for fmts in names.values() if len(fmts) > 1)

    @property
    def estimated_savings_bytes(self) -> int:
        """Rough saving from removing all but the largest copy of each product."""
        import re
        groups: dict[str, list[int]] = {}
        for p in self.plugins:
            raw = p.get("name", "")
            key = re.sub(r"[\s_\-]*(vst3?|au|aax)\s*$", "", raw, flags=re.IGNORECASE).strip().lower()
            key = key or raw.lower()
            groups.setdefault(key, []).append(p.get("file_size", 0))
        total = 0
        for sizes in groups.values():
            if len(sizes) > 1:
                ordered = sorted(sizes)
                total += sum(ordered[:-1])
        return total

    def _apps_by_category(self, category: str) -> list[dict]:
        return [a for a in self.apps if a.get("category") == category]

    @property
    def daws(self) -> list[dict]:
        return self._apps_by_category("DAW")

    @property
    def license_managers(self) -> list[dict]:
        return self._apps_by_category("License Manager")

    @property
    def hardware_utilities(self) -> list[dict]:
        return self._apps_by_category("Hardware Utility")

    @property
    def plugin_managers(self) -> list[dict]:
        return self._apps_by_category("Plugin Manager")

    # ── Serialisation ─────────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        return {
            "created_at": self.created_at,
            "hostname":   self.hostname,
            "plugins":    self.plugins,
            "apps":       self.apps,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "MigrationSnapshot":
        return cls(
            created_at=data.get("created_at", ""),
            hostname=data.get("hostname", ""),
            plugins=data.get("plugins", []),
            apps=data.get("apps", []),
        )


# ── Comparison model ──────────────────────────────────────────────────────────

@dataclass
class ComparisonItem:
    name: str
    category: str
    status: str
    details: str = ""


@dataclass
class ComparisonResult:
    present_plugins: list[ComparisonItem] = field(default_factory=list)
    missing_plugins: list[ComparisonItem] = field(default_factory=list)
    present_apps:    list[ComparisonItem] = field(default_factory=list)
    missing_apps:    list[ComparisonItem] = field(default_factory=list)

    @property
    def all_items(self) -> list[ComparisonItem]:
        return (
            self.present_apps  + self.missing_apps +
            self.present_plugins + self.missing_plugins
        )

    @property
    def installed_count(self) -> int:
        return sum(1 for i in self.all_items if i.status == STATUS_INSTALLED)

    @property
    def missing_count(self) -> int:
        return sum(1 for i in self.all_items if i.status == STATUS_MISSING)

    @property
    def review_count(self) -> int:
        return sum(1 for i in self.all_items if i.status == STATUS_NEEDS_REVIEW)


# ── Snapshot creation ─────────────────────────────────────────────────────────

def create_snapshot(
    plugins: "list[Plugin]",
    apps: "list[MusicApp]",
    machine_name: str = "",
    machine_role: str = "",
) -> MigrationSnapshot:
    """Build a MigrationSnapshot from live scan data.

    machine_name overrides the hostname shown in snapshots and exports.
    machine_role is stored in the snapshot metadata for comparison context.
    """
    hostname = machine_name.strip() or _get_hostname()
    if machine_role.strip():
        hostname = f"{hostname}  [{machine_role.strip()}]"
    return MigrationSnapshot(
        created_at=datetime.datetime.now().isoformat(timespec="seconds"),
        hostname=hostname,
        plugins=[_plugin_to_dict(p) for p in plugins],
        apps=[_app_to_dict(a) for a in apps],
    )


def _get_hostname() -> str:
    try:
        return socket.gethostname()
    except Exception:
        return platform.node() or "unknown"


def _plugin_to_dict(p: "Plugin") -> dict:
    return {
        "name":      p.name,
        "fmt":       p.fmt,
        "developer": p.developer,
        "version":   p.version,
        "file_size": p.file_size,
        "modified":  p.modified,
        "path":      p.path,
    }


def _app_to_dict(a: "MusicApp") -> dict:
    return {
        "name":      a.name,
        "category":  a.category,
        "developer": a.developer,
        "version":   a.version,
        "path":      a.path,
        "modified":  a.modified,
    }


# ── Persistence ───────────────────────────────────────────────────────────────

def save_snapshot_json(
    snapshot: MigrationSnapshot,
    dest: "Path | str | None" = None,
) -> Path:
    if dest is None:
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        dest = Path.home() / "Desktop" / f"studio_snapshot_{ts}.json"
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("w", encoding="utf-8") as fh:
        json.dump(snapshot.to_dict(), fh, indent=2, ensure_ascii=False)
    return dest


def load_snapshot_json(path: "Path | str") -> MigrationSnapshot:
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    return MigrationSnapshot.from_dict(data)


# ── Comparison ────────────────────────────────────────────────────────────────

def compare_snapshots(
    reference: MigrationSnapshot,
    current_plugins: "list[Plugin]",
    current_apps: "list[MusicApp]",
    comparison_behavior: str = "Match by name",
) -> ComparisonResult:
    """
    Compare *reference* (old system) against the currently installed set.
    Returns a ComparisonResult with per-item statuses.

    comparison_behavior controls plugin matching:
      - "Match by name"           : case-insensitive name match (default)
      - "Match by name + version" : name + version must both match
      - "Strict path match"       : name + developer must both match
    """
    result = ComparisonResult()

    # Build current-plugin lookup based on behavior
    if comparison_behavior == "Match by name + version":
        current_plugin_keys = {
            f"{p.name.lower()}|{p.version or ''}" for p in current_plugins
        }
    elif comparison_behavior == "Strict path match":
        current_plugin_keys = {
            f"{p.name.lower()}|{p.developer.lower()}" for p in current_plugins
        }
    else:
        current_plugin_keys = {p.name.lower() for p in current_plugins}

    for p in reference.plugins:
        name      = p.get("name", "")
        fmt       = p.get("fmt", "")
        version   = p.get("version", "") or ""
        developer = p.get("developer", "") or ""

        if comparison_behavior == "Match by name + version":
            key = f"{name.lower()}|{version}"
        elif comparison_behavior == "Strict path match":
            key = f"{name.lower()}|{developer.lower()}"
        else:
            key = name.lower()

        if key in current_plugin_keys:
            result.present_plugins.append(ComparisonItem(
                name=name,
                category=fmt,
                status=STATUS_INSTALLED,
                details=f"v{version}" if version else "",
            ))
        else:
            result.missing_plugins.append(ComparisonItem(
                name=name,
                category=fmt,
                status=STATUS_MISSING,
                details=developer,
            ))

    current_app_names = {a.name.lower() for a in current_apps}
    current_app_categories = {a.category for a in current_apps}
    for a in reference.apps:
        name     = a.get("name", "")
        category = a.get("category", "")
        if name.lower() in current_app_names:
            result.present_apps.append(ComparisonItem(
                name=name,
                category=category,
                status=STATUS_INSTALLED,
                details=f"v{a['version']}" if a.get("version") else "",
            ))
        else:
            # Same category present but different app → Needs Review
            if category in current_app_categories:
                result.missing_apps.append(ComparisonItem(
                    name=name,
                    category=category,
                    status=STATUS_NEEDS_REVIEW,
                    details="Similar app in category found",
                ))
            else:
                result.missing_apps.append(ComparisonItem(
                    name=name,
                    category=category,
                    status=STATUS_MISSING,
                    details=a.get("developer", ""),
                ))

    return result


# ── CSV export ────────────────────────────────────────────────────────────────

def export_migration_csv(
    snapshot: MigrationSnapshot,
    dest: "Path | str | None" = None,
) -> Path:
    if dest is None:
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        dest = Path.home() / "Desktop" / f"migration_report_{ts}.csv"
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)

    with dest.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)

        w.writerow(["BAKKIS STUDIO MANAGER — Migration Report"])
        w.writerow([f"Generated: {snapshot.created_at}"])
        w.writerow([f"System: {snapshot.hostname}"])
        w.writerow([])

        w.writerow(["SUMMARY"])
        w.writerow(["Total Plugins",          snapshot.total_plugins])
        w.writerow(["Plugin Products",         snapshot.plugin_products])
        w.writerow(["Duplicate Format Products", snapshot.duplicate_format_products])
        w.writerow(["Estimated Storage Savings", _fmt_size(snapshot.estimated_savings_bytes)])
        w.writerow(["Music Applications",      snapshot.total_apps])
        w.writerow(["DAWs",                    len(snapshot.daws)])
        w.writerow(["License Managers",        len(snapshot.license_managers)])
        w.writerow(["Hardware Utilities",      len(snapshot.hardware_utilities)])
        w.writerow([])

        w.writerow(["PLUGIN FORMATS"])
        w.writerow(["Format", "Count"])
        for fmt, count in sorted(snapshot.plugin_formats.items()):
            w.writerow([fmt, count])
        w.writerow([])

        w.writerow(["PLUGINS"])
        w.writerow(["Name", "Format", "Developer", "Version", "Size", "Modified"])
        for p in sorted(snapshot.plugins, key=lambda x: x.get("name", "").lower()):
            w.writerow([
                p.get("name", ""),
                p.get("fmt", ""),
                p.get("developer", ""),
                p.get("version", ""),
                _fmt_size(p.get("file_size", 0)),
                p.get("modified", ""),
            ])
        w.writerow([])

        w.writerow(["MUSIC APPLICATIONS"])
        w.writerow(["Name", "Category", "Developer", "Version"])
        for a in sorted(snapshot.apps, key=lambda x: (x.get("category",""), x.get("name","").lower())):
            w.writerow([
                a.get("name", ""),
                a.get("category", ""),
                a.get("developer", ""),
                a.get("version", ""),
            ])

    return dest


# ── HTML report ───────────────────────────────────────────────────────────────

def export_migration_html(
    snapshot: MigrationSnapshot,
    dest: "Path | str | None" = None,
) -> Path:
    """
    Export a printable HTML migration report.
    Open in any browser and use File › Print to save as PDF.
    """
    if dest is None:
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        dest = Path.home() / "Desktop" / f"migration_report_{ts}.html"
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)

    fmt_rows = "".join(
        f"<tr><td>{fmt}</td><td>{count}</td></tr>"
        for fmt, count in sorted(snapshot.plugin_formats.items())
    )
    plugin_rows = "".join(
        f"<tr><td>{p.get('name','')}</td><td>{p.get('fmt','')}</td>"
        f"<td>{p.get('developer','')}</td><td>{p.get('version','')}</td>"
        f"<td>{_fmt_size(p.get('file_size',0))}</td></tr>"
        for p in sorted(snapshot.plugins, key=lambda x: x.get("name", "").lower())
    )
    app_rows = "".join(
        f"<tr><td>{a.get('name','')}</td><td>{a.get('category','')}</td>"
        f"<td>{a.get('developer','')}</td><td>{a.get('version','')}</td></tr>"
        for a in sorted(snapshot.apps,
                        key=lambda x: (x.get("category", ""), x.get("name", "").lower()))
    )

    savings_str = _fmt_size(snapshot.estimated_savings_bytes)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Migration Report — {snapshot.hostname}</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
         background: #fff; color: #1a1a2e; padding: 40px; max-width: 960px;
         margin: 0 auto; font-size: 14px; line-height: 1.5; }}
  h1  {{ color: #6C8EF5; font-size: 26px; border-bottom: 2px solid #6C8EF5;
         padding-bottom: 10px; margin-bottom: 6px; }}
  h2  {{ color: #333; font-size: 16px; margin: 32px 0 10px; text-transform: uppercase;
         letter-spacing: 0.5px; border-left: 3px solid #6C8EF5; padding-left: 10px; }}
  .meta {{ color: #666; font-size: 12px; margin-bottom: 28px; }}
  .stats {{ display: flex; gap: 16px; flex-wrap: wrap; margin-bottom: 32px; }}
  .stat {{ background: #f4f6ff; border-radius: 10px; padding: 14px 20px; min-width: 110px; }}
  .stat .val {{ font-size: 26px; font-weight: 700; color: #6C8EF5; }}
  .stat .lbl {{ font-size: 10px; color: #666; text-transform: uppercase; letter-spacing: 0.5px; }}
  table {{ width: 100%; border-collapse: collapse; margin-top: 6px; font-size: 13px; }}
  th {{ background: #6C8EF5; color: #fff; padding: 8px 12px; text-align: left;
        font-weight: 600; font-size: 11px; text-transform: uppercase; letter-spacing: 0.4px; }}
  td {{ padding: 7px 12px; border-bottom: 1px solid #eee; }}
  tr:nth-child(even) td {{ background: #f9f9ff; }}
  .badge {{ display: inline-block; padding: 2px 8px; border-radius: 12px; font-size: 11px;
             font-weight: 600; }}
  .badge-dup  {{ background: #fff3e0; color: #e67e22; }}
  .badge-save {{ background: #e8f5e9; color: #2e7d32; }}
  @media print {{ @page {{ margin: 20mm; }} }}
</style>
</head>
<body>

<h1>Bakkis Studio Manager — Migration Report</h1>
<div class="meta">
  Generated: {snapshot.created_at} &nbsp;·&nbsp; Source system: <strong>{snapshot.hostname}</strong>
</div>

<div class="stats">
  <div class="stat"><div class="val">{snapshot.total_plugins}</div><div class="lbl">Total Plugins</div></div>
  <div class="stat"><div class="val">{snapshot.plugin_products}</div><div class="lbl">Products</div></div>
  <div class="stat"><div class="val">{snapshot.total_apps}</div><div class="lbl">Applications</div></div>
  <div class="stat"><div class="val">{len(snapshot.daws)}</div><div class="lbl">DAWs</div></div>
  <div class="stat"><div class="val">{len(snapshot.license_managers)}</div><div class="lbl">License Managers</div></div>
  <div class="stat"><div class="val">{snapshot.duplicate_format_products}</div><div class="lbl">Dup. Formats</div></div>
  <div class="stat"><div class="val">{savings_str}</div><div class="lbl">Est. Savings</div></div>
</div>

<h2>Plugin Formats</h2>
<table>
  <tr><th>Format</th><th>Count</th></tr>
  {fmt_rows}
</table>

<h2>Plugins ({snapshot.total_plugins})</h2>
<table>
  <tr><th>Name</th><th>Format</th><th>Developer</th><th>Version</th><th>Size</th></tr>
  {plugin_rows}
</table>

<h2>Music Applications ({snapshot.total_apps})</h2>
<table>
  <tr><th>Name</th><th>Category</th><th>Developer</th><th>Version</th></tr>
  {app_rows}
</table>

</body>
</html>"""

    with dest.open("w", encoding="utf-8") as fh:
        fh.write(html)

    return dest


# ── Size helper ───────────────────────────────────────────────────────────────

def _fmt_size(n: int) -> str:
    if n == 0:
        return "—"
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024  # type: ignore[assignment]
    return f"{n:.1f} GB"
