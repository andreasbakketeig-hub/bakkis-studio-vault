"""
Plugin insights — read-only cleanup and update guidance from local scan data.

No files are moved, deleted, or modified by this module.
"""

from __future__ import annotations

import datetime
import os
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from app.core.cleanup import (
    CONF_REVIEW,
    PROFILE_ABLETON,
    CleanupRecommendation,
    DawProfile,
    analyze_cleanup,
    get_profile,
    make_custom_profile,
)
from app.core.health import (
    CAT_BROKEN,
    CAT_DUPLICATE,
    CAT_WARNING,
    HealthIssue,
    analyze_health,
)
from app.core.scanner import Plugin, analyze_formats
from app.core.vendor_registry import (
    VENDOR_REGISTRY,
    ResolvedManager,
    VendorRegistryEntry,
    match_vendor,
    resolve_manager_app,
)

if TYPE_CHECKING:
    from app.core.settings import AppSettings

# ── Issue kinds ───────────────────────────────────────────────────────────────

KIND_VERSION_CONFLICT = "version_conflict"
KIND_STALE_MODIFIED = "stale_modified"
KIND_LEGACY_VST2 = "legacy_vst2"
KIND_REDUNDANT_FORMAT = "redundant_format"
KIND_DUPLICATE_PATH = "duplicate_path"
KIND_MISSING_OR_BROKEN = "missing_or_broken"
KIND_UPDATE_MANAGER_AVAILABLE = "update_manager_available"
KIND_MANUAL_UPDATE_CHECK = "manual_update_check"
KIND_VENDOR_WEBSITE = "vendor_website"
KIND_UNKNOWN_UPDATE_PATH = "unknown_update_path"

# Legacy alias — do not use in new UI labels
KIND_UPDATE_MANAGER_MISSING = KIND_MANUAL_UPDATE_CHECK

# ── Risk / status / actions ───────────────────────────────────────────────────

RISK_LOW = "low"
RISK_MEDIUM = "medium"
RISK_HIGH = "high"

UPDATE_UNKNOWN = "unknown"
UPDATE_VERSION_MISMATCH = "version_mismatch"
UPDATE_CHECK_MANUALLY = "check_manually"
UPDATE_MANAGER_AVAILABLE = "manager_available"

ACTION_REVIEW = "review"
ACTION_REVEAL = "reveal"
ACTION_OPEN_UPDATE_MANAGER = "open_update_manager"
ACTION_CHECK_VENDOR_WEBSITE = "check_vendor_website"

# Issue kinds where quarantine may be offered (Plugin Health only)
QUARANTINE_ELIGIBLE_KINDS: frozenset[str] = frozenset({
    KIND_REDUNDANT_FORMAT,
    KIND_DUPLICATE_PATH,
    KIND_LEGACY_VST2,
})


def is_quarantine_eligible(insight: "PluginInsight") -> bool:
    """True when Plugin Health may offer Move to Quarantine for this row."""
    if not (insight.path or "").strip():
        return False
    if insight.issue_kind in (
        KIND_UPDATE_MANAGER_AVAILABLE,
        KIND_MANUAL_UPDATE_CHECK,
        KIND_VENDOR_WEBSITE,
        KIND_UNKNOWN_UPDATE_PATH,
    ):
        return False
    return insight.issue_kind in QUARANTINE_ELIGIBLE_KINDS

STALE_MEDIUM_YEARS = 3
STALE_HIGH_YEARS = 5

# UI filter keys (Plugin Health)
FILTER_ALL = "all"
FILTER_VERSION_CONFLICT = "version_conflict"
FILTER_STALE_MODIFIED = "stale_modified"
FILTER_UPDATE_GUIDANCE = "update_guidance"

FILTER_DISPLAY_LABELS: dict[str, str] = {
    FILTER_ALL: "All Issues",
    FILTER_VERSION_CONFLICT: "Version Conflicts",
    FILTER_STALE_MODIFIED: "Stale Plugins",
    FILTER_UPDATE_GUIDANCE: "Update Guidance",
    CAT_WARNING: "Warnings",
    CAT_DUPLICATE: "Duplicates",
    CAT_BROKEN: "Broken",
}

_ISSUE_LABELS: dict[str, str] = {
    KIND_VERSION_CONFLICT: "Version Conflict",
    KIND_STALE_MODIFIED: "Stale Plugin",
    KIND_LEGACY_VST2: "Legacy VST2",
    KIND_REDUNDANT_FORMAT: "Redundant Format",
    KIND_DUPLICATE_PATH: "Duplicate Path",
    KIND_MISSING_OR_BROKEN: "Missing or Broken",
    KIND_UPDATE_MANAGER_AVAILABLE: "Update Manager Available",
    KIND_MANUAL_UPDATE_CHECK: "Manual Update Check",
    KIND_VENDOR_WEBSITE: "Check Vendor Website",
    KIND_UNKNOWN_UPDATE_PATH: "Unknown Update Path",
}


@dataclass(frozen=True)
class PluginInsight:
    """Structured read-only insight row for UI and reporting."""

    plugin_name: str
    developer: str
    fmt: str
    installed_version: str
    path: str
    issue_kind: str
    risk_level: str
    update_status: str
    recommended_action: str
    recommendation: str
    related_paths: tuple[str, ...] = ()
    manager_app_path: str = ""
    manager_app_name: str = ""
    manager_display: str = ""
    website_url: str = ""
    product_key: str = ""

    @property
    def issue_type(self) -> str:
        return _ISSUE_LABELS.get(self.issue_kind, self.issue_kind)

    @property
    def category(self) -> str:
        """Coarse bucket for Plugin Health filters and row coloring."""
        if self.issue_kind == KIND_VERSION_CONFLICT:
            return FILTER_VERSION_CONFLICT
        if self.issue_kind == KIND_STALE_MODIFIED:
            return FILTER_STALE_MODIFIED
        if self.issue_kind in (
            KIND_UPDATE_MANAGER_AVAILABLE,
            KIND_MANUAL_UPDATE_CHECK,
            KIND_VENDOR_WEBSITE,
            KIND_UNKNOWN_UPDATE_PATH,
        ):
            return FILTER_UPDATE_GUIDANCE
        if self.issue_kind == KIND_DUPLICATE_PATH:
            return CAT_DUPLICATE
        if self.issue_kind == KIND_MISSING_OR_BROKEN:
            return CAT_BROKEN
        if self.issue_kind == KIND_LEGACY_VST2 and self.risk_level == RISK_HIGH:
            return CAT_BROKEN
        return CAT_WARNING


@dataclass
class PluginInsightsReport:
    insights: list[PluginInsight] = field(default_factory=list)
    total_plugins: int = 0

    @property
    def version_conflicts(self) -> list[PluginInsight]:
        return [i for i in self.insights if i.issue_kind == KIND_VERSION_CONFLICT]

    @property
    def stale_plugins(self) -> list[PluginInsight]:
        return [i for i in self.insights if i.issue_kind == KIND_STALE_MODIFIED]

    @property
    def update_guidance(self) -> list[PluginInsight]:
        return [
            i for i in self.insights
            if i.issue_kind in (
                KIND_UPDATE_MANAGER_AVAILABLE,
                KIND_MANUAL_UPDATE_CHECK,
                KIND_VENDOR_WEBSITE,
                KIND_UNKNOWN_UPDATE_PATH,
            )
        ]

    @property
    def version_conflict_products(self) -> int:
        """Unique products with cross-format version mismatch."""
        keys = {
            i.product_key for i in self.insights
            if i.issue_kind == KIND_VERSION_CONFLICT and i.product_key
        }
        if keys:
            return len(keys)
        names = {i.plugin_name for i in self.version_conflicts}
        return len(names)

    @property
    def broken(self) -> list[PluginInsight]:
        return [i for i in self.insights if i.category == CAT_BROKEN]

    @property
    def warnings(self) -> list[PluginInsight]:
        return [i for i in self.insights if i.category == CAT_WARNING]

    @property
    def duplicates(self) -> list[PluginInsight]:
        return [i for i in self.insights if i.category == CAT_DUPLICATE]

    def by_filter(self, key: str) -> list[PluginInsight]:
        if key == FILTER_ALL:
            return list(self.insights)
        if key == FILTER_VERSION_CONFLICT:
            return self.version_conflicts
        if key == FILTER_STALE_MODIFIED:
            return self.stale_plugins
        if key == FILTER_UPDATE_GUIDANCE:
            return self.update_guidance
        if key == CAT_WARNING:
            return self.warnings
        if key == CAT_DUPLICATE:
            return self.duplicates
        if key == CAT_BROKEN:
            return self.broken
        return list(self.insights)

    @property
    def healthy_count(self) -> int:
        """Plug-in paths with no insight (includes related_paths from grouped issues)."""
        affected: set[str] = set()
        for i in self.insights:
            if i.path:
                affected.add(i.path)
            affected.update(p for p in i.related_paths if p)
        return max(0, self.total_plugins - len(affected))

    @property
    def affected_path_count(self) -> int:
        affected: set[str] = set()
        for i in self.insights:
            if i.path:
                affected.add(i.path)
            affected.update(p for p in i.related_paths if p)
        return len(affected)


def analyze_insights(
    plugins: list[Plugin],
    music_apps: list | None = None,
    *,
    vst2_sensitivity: str = "Medium",
    cleanup_profile: DawProfile | None = None,
    preferred_daw: str = "",
    preferred_formats: list[str] | None = None,
    ignored_vendors: list[str] | None = None,
    safe_mode_cleanup: bool = False,
    never_remove_only_format: bool = True,
) -> PluginInsightsReport:
    """
    Build a read-only :class:`PluginInsightsReport` from *plugins* and optional
    *music_apps* (for update-manager detection).
    """
    report = PluginInsightsReport(total_plugins=len(plugins))
    if not plugins:
        return report

    ignored = {v.strip().lower() for v in (ignored_vendors or []) if v.strip()}
    apps = music_apps or []

    profile = cleanup_profile or _resolve_cleanup_profile(
        preferred_daw, preferred_formats,
    )
    health = analyze_health(plugins, vst2_sensitivity=vst2_sensitivity)
    cleanup_recs = analyze_cleanup(plugins, profile)

    seen_keys: set[tuple[str, str]] = set()
    seen_update_vendors: set[str] = set()

    def _add(insight: PluginInsight) -> None:
        key = (insight.path, insight.issue_kind)
        if insight.path and key in seen_keys:
            return
        if ignored and insight.developer.strip().lower() in ignored:
            return
        if insight.path:
            seen_keys.add(key)
        report.insights.append(insight)

    path_to_plugin = {p.path: p for p in plugins}
    _add_health_insights(health.issues, path_to_plugin, _add)
    _add_cleanup_insights(
        cleanup_recs, safe_mode_cleanup, never_remove_only_format, _add,
    )
    _add_version_conflicts(plugins, _add)
    _add_stale_insights(plugins, _add)
    _add_update_guidance(plugins, apps, seen_update_vendors, _add)

    return report


def insight_options_from_settings(settings: "AppSettings | None") -> dict:
    """Keyword arguments for :func:`analyze_insights` from :class:`AppSettings`."""
    if settings is None:
        return {}
    return {
        "vst2_sensitivity": settings.legacy_vst2_sensitivity,
        "preferred_daw": settings.preferred_daw,
        "preferred_formats": settings.preferred_formats,
        "ignored_vendors": settings.ignored_vendors,
        "safe_mode_cleanup": settings.safe_mode_cleanup,
        "never_remove_only_format": settings.never_remove_only_format,
    }


def filter_display_label(filter_key: str) -> str:
    """Human-readable label for a Plugin Health filter key."""
    return FILTER_DISPLAY_LABELS.get(filter_key, filter_key.replace("_", " ").title())


def _resolve_cleanup_profile(
    preferred_daw: str,
    preferred_formats: list[str] | None,
) -> DawProfile:
    from app.core.cleanup import PREFERRED_DAW_PROFILE

    if preferred_formats:
        return make_custom_profile(preferred_formats)
    key = PREFERRED_DAW_PROFILE.get(preferred_daw, PROFILE_ABLETON)
    return get_profile(key)


def _add_health_insights(
    issues: list[HealthIssue],
    path_to_plugin: dict[str, Plugin],
    add: callable,
) -> None:
    for issue in issues:
        kind = KIND_MISSING_OR_BROKEN
        risk = RISK_HIGH
        update_status = UPDATE_UNKNOWN
        action = ACTION_REVIEW

        if issue.issue_type.startswith("Legacy Format"):
            kind = KIND_LEGACY_VST2
            risk = RISK_HIGH if "High Sensitivity" in issue.issue_type else RISK_MEDIUM
        elif issue.issue_type == "Duplicate in Multiple Locations":
            kind = KIND_DUPLICATE_PATH
            risk = RISK_MEDIUM
        elif issue.issue_type == "Duplicate Name":
            continue
        elif issue.category == CAT_WARNING:
            risk = RISK_MEDIUM
        elif issue.category == CAT_BROKEN:
            kind = KIND_MISSING_OR_BROKEN
            risk = RISK_HIGH

        plugin = path_to_plugin.get(issue.path)
        developer = plugin.developer if plugin else ""
        version = plugin.version if plugin else ""

        add(PluginInsight(
            plugin_name=issue.plugin_name,
            developer=developer,
            fmt=issue.fmt,
            installed_version=version,
            path=issue.path,
            issue_kind=kind,
            risk_level=risk,
            update_status=update_status,
            recommended_action=action,
            recommendation=issue.suggested_action,
        ))


def _add_cleanup_insights(
    recs: list[CleanupRecommendation],
    safe_mode: bool,
    never_remove_only_format: bool,
    add: callable,
) -> None:
    for rec in recs:
        if not rec.has_redundant:
            continue
        if never_remove_only_format and len(rec.installed_formats) <= 1:
            continue
        confidence = rec.confidence
        if safe_mode and confidence == "Safe":
            confidence = CONF_REVIEW
        risk = RISK_LOW if confidence == "Safe" else RISK_MEDIUM
        redundant_paths = [
            rec.installed_formats[f].path
            for f in rec.redundant_formats
            if f in rec.installed_formats
        ]
        for fmt in rec.redundant_formats:
            plugin = rec.installed_formats.get(fmt)
            if not plugin:
                continue
            others = [p for p in redundant_paths if p != plugin.path]
            add(PluginInsight(
                plugin_name=rec.product_name,
                developer=rec.developer,
                fmt=fmt,
                installed_version=plugin.version,
                path=plugin.path,
                issue_kind=KIND_REDUNDANT_FORMAT,
                risk_level=risk,
                update_status=UPDATE_UNKNOWN,
                recommended_action=ACTION_REVIEW,
                recommendation=(
                    f"Redundant {fmt} copy for your workflow — keep "
                    f"{', '.join(rec.keep_formats)}. Review whether this copy is "
                    f"still needed before any cleanup."
                ),
                related_paths=tuple(others),
            ))


def _version_tuple(version: str) -> tuple[int, ...]:
    """Normalize a version string to comparable numeric components."""
    parts = re.findall(r"\d+", version.strip())
    if not parts:
        return ()
    return tuple(int(p) for p in parts)


def _versions_equivalent(a: str, b: str) -> bool:
    """Return True when two version strings are plausibly the same release."""
    ta, tb = _version_tuple(a), _version_tuple(b)
    if ta and tb:
        width = max(len(ta), len(tb), 3)
        pad = lambda t: t + (0,) * (width - len(t)) if len(t) < width else t[:width]
        if pad(ta) == pad(tb):
            return True
    return a.strip().lower() == b.strip().lower()


def _add_version_conflicts(plugins: list[Plugin], add: callable) -> None:
    groups = analyze_formats(plugins)
    for group in groups:
        version_by_plugin: list[tuple[str, Plugin]] = []
        for plugin in group.formats.values():
            ver = (plugin.version or "").strip()
            if ver:
                version_by_plugin.append((ver, plugin))

        if len(version_by_plugin) < 2:
            continue

        distinct: list[str] = []
        for ver, _ in version_by_plugin:
            if any(_versions_equivalent(ver, other) for other in distinct):
                continue
            distinct.append(ver)

        if len(distinct) < 2:
            continue

        all_paths = tuple(p.path for p in group.formats.values())
        ver_summary = ", ".join(
            f"{fmt} v{pl.version}"
            for fmt, pl in sorted(group.formats.items())
            if (pl.version or "").strip()
        )
        recommendation = (
            "Version strings differ across formats. This may be normal, but you "
            "may want to check the vendor manager."
        )
        if ver_summary:
            recommendation = f"{recommendation} ({ver_summary})"

        rep = version_by_plugin[0][1]
        product_key = group.product_name.lower().strip()
        add(PluginInsight(
            plugin_name=group.product_name,
            developer=group.developer,
            fmt=rep.fmt,
            installed_version=rep.version,
            path=rep.path,
            issue_kind=KIND_VERSION_CONFLICT,
            risk_level=RISK_MEDIUM,
            update_status=UPDATE_VERSION_MISMATCH,
            recommended_action=ACTION_REVIEW,
            recommendation=recommendation,
            related_paths=tuple(p for p in all_paths if p != rep.path),
            product_key=product_key,
        ))


def _add_stale_insights(plugins: list[Plugin], add: callable) -> None:
    today = datetime.date.today()
    for plugin in plugins:
        if not plugin.modified:
            continue
        try:
            modified = datetime.datetime.strptime(plugin.modified, "%Y-%m-%d").date()
        except ValueError:
            continue
        age_days = (today - modified).days
        age_years = age_days / 365.25
        if age_years < STALE_MEDIUM_YEARS:
            continue
        risk = RISK_HIGH if age_years >= STALE_HIGH_YEARS else RISK_MEDIUM
        years_int = int(age_years)
        add(PluginInsight(
            plugin_name=plugin.name,
            developer=plugin.developer,
            fmt=plugin.fmt,
            installed_version=plugin.version,
            path=plugin.path,
            issue_kind=KIND_STALE_MODIFIED,
            risk_level=risk,
            update_status=UPDATE_CHECK_MANUALLY,
            recommended_action=ACTION_REVIEW,
            recommendation=(
                f"File has not been modified since {plugin.modified}. This is not "
                f"the same as release date ({years_int}+ years on disk)."
            ),
        ))


def _add_update_guidance(
    plugins: list[Plugin],
    music_apps: list,
    seen_vendors: set[str],
    add: callable,
) -> None:
    """One update-guidance insight per matched vendor (first representative plugin)."""
    vendor_plugins: dict[str, list[Plugin]] = {}
    unknown_emitted = False

    for plugin in plugins:
        entry = match_vendor(plugin.developer)
        if entry is None:
            if not unknown_emitted and not (plugin.developer or "").strip():
                unknown_emitted = True
                add(_unknown_update_insight(plugin))
            continue
        vendor_plugins.setdefault(entry.vendor_key, []).append(plugin)

    for vendor_key, group_plugins in vendor_plugins.items():
        if vendor_key in seen_vendors:
            continue
        seen_vendors.add(vendor_key)
        entry = next(e for e in VENDOR_REGISTRY if e.vendor_key == vendor_key)
        rep = group_plugins[0]
        add(_vendor_update_insight(entry, rep, music_apps))


def _vendor_update_insight(
    entry: VendorRegistryEntry,
    plugin: Plugin,
    music_apps: list,
) -> PluginInsight:
    resolved = resolve_manager_app(entry, music_apps)

    if entry.website_only or not entry.manager_app_names:
        return PluginInsight(
            plugin_name=plugin.name,
            developer=plugin.developer or entry.display_name,
            fmt=plugin.fmt,
            installed_version=plugin.version,
            path=plugin.path,
            issue_kind=KIND_VENDOR_WEBSITE,
            risk_level=RISK_LOW,
            update_status=UPDATE_CHECK_MANUALLY,
            recommended_action=ACTION_CHECK_VENDOR_WEBSITE,
            recommendation=(
                f"Check {entry.display_name} website for updates: {entry.website_url}"
            ),
            website_url=entry.website_url,
            manager_display=entry.manager_display,
        )

    if resolved:
        open_label = resolved.app_name
        return PluginInsight(
            plugin_name=plugin.name,
            developer=plugin.developer or entry.display_name,
            fmt=plugin.fmt,
            installed_version=plugin.version,
            path=plugin.path,
            issue_kind=KIND_UPDATE_MANAGER_AVAILABLE,
            risk_level=RISK_LOW,
            update_status=UPDATE_MANAGER_AVAILABLE,
            recommended_action=ACTION_OPEN_UPDATE_MANAGER,
            recommendation=f"Open {open_label} to check for updates.",
            manager_app_path=resolved.app_path,
            manager_app_name=resolved.app_name,
            manager_display=open_label,
            website_url=entry.website_url,
        )

    return PluginInsight(
        plugin_name=plugin.name,
        developer=plugin.developer or entry.display_name,
        fmt=plugin.fmt,
        installed_version=plugin.version,
        path=plugin.path,
        issue_kind=KIND_MANUAL_UPDATE_CHECK,
        risk_level=RISK_LOW,
        update_status=UPDATE_CHECK_MANUALLY,
        recommended_action=ACTION_CHECK_VENDOR_WEBSITE,
        recommendation=(
            f"Check {entry.display_name} website or install "
            f"{entry.manager_display}: {entry.website_url}"
        ),
        website_url=entry.website_url,
        manager_display=entry.manager_display,
    )


def _unknown_update_insight(plugin: Plugin) -> PluginInsight:
    return PluginInsight(
        plugin_name=plugin.name,
        developer=plugin.developer,
        fmt=plugin.fmt,
        installed_version=plugin.version,
        path=plugin.path,
        issue_kind=KIND_UNKNOWN_UPDATE_PATH,
        risk_level=RISK_LOW,
        update_status=UPDATE_UNKNOWN,
        recommended_action=ACTION_CHECK_VENDOR_WEBSITE,
        recommendation="Developer unknown — check the vendor website for updates.",
    )


def open_update_manager(insight: PluginInsight) -> bool:
    """
    Launch the update manager app for *insight* if path is known and exists.
    Returns True when ``open`` was attempted.
    """
    path = insight.manager_app_path
    if not path or not os.path.exists(path):
        return False
    import subprocess
    subprocess.run(["open", path], check=False)
    return True


def open_vendor_website(insight: PluginInsight) -> bool:
    """Open the vendor website in the default browser when URL is set."""
    url = (insight.website_url or "").strip()
    if not url:
        return False
    import subprocess
    subprocess.run(["open", url], check=False)
    return True
