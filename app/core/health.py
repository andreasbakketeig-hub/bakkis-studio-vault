"""
Plugin Health analyzer — inspects scanned audio plug-ins for potential issues.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from app.core.scanner import Plugin

# ── Thresholds ────────────────────────────────────────────────────────────────

SMALL_FILE_THRESHOLD = 4096  # bytes — bundles under 4 KB are suspicious

# ── Issue categories ──────────────────────────────────────────────────────────

CAT_BROKEN    = "broken"
CAT_WARNING   = "warning"
CAT_DUPLICATE = "duplicate"

# ── Known formats ─────────────────────────────────────────────────────────────

_KNOWN_FORMATS: frozenset[str] = frozenset({"VST", "VST3", "AU", "AAX"})

_EXT_TO_FMT: dict[str, str] = {
    ".vst":       "VST",
    ".vst3":      "VST3",
    ".component": "AU",
    ".aaxplugin": "AAX",
}


# ── Data model ────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class HealthIssue:
    plugin_name: str
    issue_type: str           # human-readable label, e.g. "Missing File"
    category: str             # CAT_BROKEN | CAT_WARNING | CAT_DUPLICATE
    fmt: str
    path: str
    suggested_action: str


@dataclass
class HealthReport:
    issues: list[HealthIssue] = field(default_factory=list)
    total_plugins: int = 0

    @property
    def broken(self) -> list[HealthIssue]:
        return [i for i in self.issues if i.category == CAT_BROKEN]

    @property
    def warnings(self) -> list[HealthIssue]:
        return [i for i in self.issues if i.category == CAT_WARNING]

    @property
    def duplicates(self) -> list[HealthIssue]:
        return [i for i in self.issues if i.category == CAT_DUPLICATE]

    @property
    def healthy_count(self) -> int:
        """Plugins with no detected issues."""
        affected_paths = {i.path for i in self.issues}
        return max(0, self.total_plugins - len(affected_paths))


# ── Analyzer ──────────────────────────────────────────────────────────────────

def analyze_health(
    plugins: list[Plugin],
    vst2_sensitivity: str = "Medium",
) -> HealthReport:
    """
    Inspect *plugins* for potential issues and return a :class:`HealthReport`.

    Checks performed (in order):
      1. Broken symlinks
      2. Missing files (path no longer exists)
      3. Zero-byte bundles
      4. Suspiciously small bundles (< SMALL_FILE_THRESHOLD bytes)
      5. Legacy VST2 format (deprecated on macOS) / unknown formats
      6. Duplicate plugin names across formats
      7. Identical name + format found in multiple file-system locations

    vst2_sensitivity controls VST2 flagging:
      - "Low"    : only flag VST2 when a VST3 or AU equivalent exists
      - "Medium" : always flag VST2 as a warning  (default)
      - "High"   : flag all VST2 plugins as broken (most aggressive)
    """
    report = HealthReport(total_plugins=len(plugins))
    if not plugins:
        return report

    # Build name → [Plugin] map for duplicate detection
    name_groups: dict[str, list[Plugin]] = {}
    for p in plugins:
        name_groups.setdefault(p.name.lower().strip(), []).append(p)

    # Track paths already flagged as duplicates to avoid double-reporting
    duplicate_paths: set[str] = set()

    for p in plugins:
        # ── 1. Broken symlink ─────────────────────────────────────────────────
        if os.path.islink(p.path) and not os.path.exists(p.path):
            report.issues.append(HealthIssue(
                plugin_name=p.name,
                issue_type="Broken Symlink",
                category=CAT_BROKEN,
                fmt=p.fmt,
                path=p.path,
                suggested_action="Review broken symlink — reinstall plugin if needed",
            ))
            continue  # no further checks are meaningful for this path

        # ── 2. Missing file ───────────────────────────────────────────────────
        if not os.path.exists(p.path):
            report.issues.append(HealthIssue(
                plugin_name=p.name,
                issue_type="Missing File",
                category=CAT_BROKEN,
                fmt=p.fmt,
                path=p.path,
                suggested_action="Verify installation — file no longer exists at this path",
            ))
            continue

        # ── 3. Zero-byte bundle ───────────────────────────────────────────────
        if p.file_size == 0:
            report.issues.append(HealthIssue(
                plugin_name=p.name,
                issue_type="Zero-Byte File",
                category=CAT_BROKEN,
                fmt=p.fmt,
                path=p.path,
                suggested_action="Reinstall plugin — bundle appears to be empty",
            ))

        # ── 4. Suspiciously small bundle ──────────────────────────────────────
        elif 0 < p.file_size < SMALL_FILE_THRESHOLD:
            report.issues.append(HealthIssue(
                plugin_name=p.name,
                issue_type="Suspiciously Small",
                category=CAT_WARNING,
                fmt=p.fmt,
                path=p.path,
                suggested_action="File may be corrupt or only partially installed — verify",
            ))

        # ── 5. Format checks ──────────────────────────────────────────────────
        ext = Path(p.path).suffix.lower()
        if p.fmt not in _KNOWN_FORMATS:
            report.issues.append(HealthIssue(
                plugin_name=p.name,
                issue_type="Unsupported Format",
                category=CAT_WARNING,
                fmt=p.fmt,
                path=p.path,
                suggested_action="Unknown format — may not load in any DAW on this system",
            ))
        elif ext in _EXT_TO_FMT and _EXT_TO_FMT[ext] != p.fmt:
            # Extension and reported format disagree (e.g. .vst3 file labelled as VST)
            report.issues.append(HealthIssue(
                plugin_name=p.name,
                issue_type="Format Mismatch",
                category=CAT_WARNING,
                fmt=p.fmt,
                path=p.path,
                suggested_action="File extension does not match reported format — check installation",
            ))
        elif p.fmt == "VST":
            # VST2 flagging — behaviour controlled by vst2_sensitivity
            group = name_groups.get(p.name.lower().strip(), [])
            has_modern = any(
                q.fmt in ("VST3", "AU") for q in group if q.path != p.path
            )

            if vst2_sensitivity == "Low":
                # Only flag when a modern equivalent is also installed
                if has_modern:
                    report.issues.append(HealthIssue(
                        plugin_name=p.name,
                        issue_type="Legacy Format (VST2)",
                        category=CAT_WARNING,
                        fmt=p.fmt,
                        path=p.path,
                        suggested_action=(
                            "VST3/AU equivalent found — review whether the VST2 "
                            "copy is still needed"
                        ),
                    ))
            elif vst2_sensitivity == "High":
                # Flag all VST2 as broken regardless of alternatives
                report.issues.append(HealthIssue(
                    plugin_name=p.name,
                    issue_type="Legacy Format (VST2) — High Sensitivity",
                    category=CAT_BROKEN,
                    fmt=p.fmt,
                    path=p.path,
                    suggested_action="VST2 is deprecated — upgrade to VST3 or AU immediately",
                ))
            else:
                # Medium (default): always flag as warning
                report.issues.append(HealthIssue(
                    plugin_name=p.name,
                    issue_type="Legacy Format (VST2)",
                    category=CAT_WARNING,
                    fmt=p.fmt,
                    path=p.path,
                    suggested_action="VST2 is deprecated on macOS — check for a VST3 or AU version",
                ))

    # ── 6 & 7. Duplicate detection ────────────────────────────────────────────
    for _, group in name_groups.items():
        if len(group) <= 1:
            continue

        # Group by format to find the same format installed in multiple locations
        fmt_map: dict[str, list[Plugin]] = {}
        for p in group:
            fmt_map.setdefault(p.fmt, []).append(p)

        for fmt, fmt_plugins in fmt_map.items():
            if len(fmt_plugins) > 1:
                for p in fmt_plugins:
                    if p.path not in duplicate_paths:
                        duplicate_paths.add(p.path)
                        report.issues.append(HealthIssue(
                            plugin_name=p.name,
                            issue_type="Duplicate in Multiple Locations",
                            category=CAT_DUPLICATE,
                            fmt=p.fmt,
                            path=p.path,
                            suggested_action=(
                                "Multiple copies found — review which path to keep "
                                "to avoid DAW loading conflicts"
                            ),
                        ))

        # Same name but different formats (informational duplicate)
        if len(fmt_map) > 1:
            for p in group:
                if p.path not in duplicate_paths:
                    duplicate_paths.add(p.path)
                    report.issues.append(HealthIssue(
                        plugin_name=p.name,
                        issue_type="Duplicate Name",
                        category=CAT_DUPLICATE,
                        fmt=p.fmt,
                        path=p.path,
                        suggested_action=(
                            "Same plugin name across multiple formats — review "
                            "which format you want to keep"
                        ),
                    ))

    return report
