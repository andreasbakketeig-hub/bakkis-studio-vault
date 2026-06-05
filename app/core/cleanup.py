"""
Cleanup Recommendations — analyze plugin format redundancy and produce
safe, read-only suggestions for which formats could be removed.

No files are deleted or quarantined by this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.core.scanner import FormatGroup, Plugin, _fmt_size, analyze_formats

# ── Confidence levels ─────────────────────────────────────────────────────────

CONF_SAFE    = "Safe"
CONF_REVIEW  = "Review"
CONF_UNKNOWN = "Unknown"

# Minimum recoverable bytes to flag as "high disk usage"
HIGH_DISK_THRESHOLD = 50 * 1024 * 1024  # 50 MB

# ── DAW profile keys ──────────────────────────────────────────────────────────

PROFILE_LOGIC     = "logic"
PROFILE_ABLETON   = "ableton"
PROFILE_CUBASE    = "cubase"
PROFILE_PRO_TOOLS = "pro_tools"
PROFILE_CUSTOM    = "custom"


@dataclass(frozen=True)
class DawProfile:
    """
    Describes which plugin formats a DAW prefers and which must never
    be flagged for removal.

    preferred    — formats the DAW uses, in priority order.  Only preferred
                   formats are placed in the "keep" column; everything else
                   becomes a candidate for the "suggested removal" column.
    never_remove — hard safety guard: these formats are NEVER placed in the
                   redundant list regardless of what other logic says.
    """
    key: str
    name: str
    preferred: list[str]
    never_remove: list[str]
    description: str = ""


DAW_PROFILES: list[DawProfile] = [
    DawProfile(
        key=PROFILE_LOGIC,
        name="Logic Pro",
        preferred=["AU"],
        never_remove=["AU"],
        description="AU preferred  ·  VST / VST3 / AAX suggested when AU is present",
    ),
    DawProfile(
        key=PROFILE_ABLETON,
        name="Ableton Live",
        preferred=["VST3", "AU"],
        never_remove=[],
        description="VST3 + AU preferred  ·  VST suggested when VST3 or AU is present",
    ),
    DawProfile(
        key=PROFILE_CUBASE,
        name="Cubase / Nuendo",
        preferred=["VST3"],
        never_remove=[],
        description="VST3 preferred  ·  VST suggested when VST3 is present",
    ),
    DawProfile(
        key=PROFILE_PRO_TOOLS,
        name="Pro Tools",
        preferred=["AAX"],
        never_remove=["AAX"],
        description="AAX preferred  ·  other formats suggested when AAX is present",
    ),
    DawProfile(
        key=PROFILE_CUSTOM,
        name="Custom",
        preferred=["VST3", "AU"],   # overridden at analysis time from UI checkboxes
        never_remove=[],
        description="Choose your preferred formats manually",
    ),
]

_PROFILE_BY_KEY: dict[str, DawProfile] = {p.key: p for p in DAW_PROFILES}

PREFERRED_DAW_PROFILE: dict[str, str] = {
    "Logic Pro":     PROFILE_LOGIC,
    "GarageBand":    PROFILE_LOGIC,
    "Pro Tools":     PROFILE_PRO_TOOLS,
    "Cubase":        PROFILE_CUBASE,
    "Studio One":    PROFILE_CUBASE,
    "Ableton Live":  PROFILE_ABLETON,
    "FL Studio":     PROFILE_ABLETON,
    "Bitwig Studio": PROFILE_ABLETON,
    "Reaper":        PROFILE_ABLETON,
    "Reason":        PROFILE_ABLETON,
}


def get_profile(key: str) -> DawProfile:
    """Return the :class:`DawProfile` for *key*, defaulting to Ableton Live."""
    return _PROFILE_BY_KEY.get(key, DAW_PROFILES[1])


def make_custom_profile(preferred: list[str]) -> DawProfile:
    """Build a Custom :class:`DawProfile` with the given *preferred* list."""
    return DawProfile(
        key=PROFILE_CUSTOM,
        name="Custom",
        preferred=preferred,
        never_remove=[],
        description="Custom preferred formats: " + "  ·  ".join(preferred) if preferred else "No formats selected",
    )


# ── Data model ────────────────────────────────────────────────────────────────

@dataclass
class CleanupRecommendation:
    """Format-cleanup recommendation for one logical plugin product."""

    product_name: str
    developer: str
    installed_formats: dict[str, Plugin]  # fmt -> Plugin
    keep_formats: list[str]               # formats to retain
    redundant_formats: list[str]          # formats suggested for removal
    confidence: str                       # CONF_SAFE | CONF_REVIEW | CONF_UNKNOWN

    @property
    def recoverable_size(self) -> int:
        """Total bytes that could be freed by removing the redundant formats."""
        return sum(
            self.installed_formats[fmt].file_size
            for fmt in self.redundant_formats
            if fmt in self.installed_formats
        )

    @property
    def recoverable_size_human(self) -> str:
        return _fmt_size(self.recoverable_size)

    @property
    def total_size(self) -> int:
        return sum(p.file_size for p in self.installed_formats.values())

    @property
    def is_multi_format(self) -> bool:
        return len(self.installed_formats) > 1

    @property
    def has_redundant(self) -> bool:
        return bool(self.redundant_formats)

    @property
    def is_high_disk_usage(self) -> bool:
        return self.recoverable_size >= HIGH_DISK_THRESHOLD


@dataclass(frozen=True)
class RedundantFormatPath:
    """One redundant format copy with a resolved on-disk plug-in path."""

    fmt: str
    path: str
    plugin: Plugin


def redundant_format_paths(rec: CleanupRecommendation) -> list[RedundantFormatPath]:
    """
    Return redundant formats that map to existing plug-in bundle paths.

    Order follows ``redundant_formats`` on the recommendation.
    """
    out: list[RedundantFormatPath] = []
    for fmt in rec.redundant_formats:
        plugin = rec.installed_formats.get(fmt)
        if plugin is None:
            continue
        path = (plugin.path or "").strip()
        if not path:
            continue
        try:
            if not Path(path).expanduser().exists():
                continue
        except OSError:
            continue
        out.append(RedundantFormatPath(fmt=fmt, path=path, plugin=plugin))
    return out


def cleanup_quarantine_reason(rec: CleanupRecommendation, fmt: str) -> str:
    """Human-readable reason shown in the quarantine confirmation dialog."""
    keep = " · ".join(rec.keep_formats) if rec.keep_formats else "—"
    return (
        f"Redundant {fmt} format for {rec.product_name} "
        f"(confidence: {rec.confidence}; keep: {keep})"
    )


def requires_format_picker(rec: CleanupRecommendation) -> bool:
    """True when the user must pick exactly one redundant path before quarantine."""
    paths = redundant_format_paths(rec)
    if len(paths) > 1:
        return True
    return len(paths) == 1 and rec.confidence == CONF_UNKNOWN


def can_offer_cleanup_quarantine(
    rec: CleanupRecommendation,
    *,
    scan_paths: list[str] | None = None,
    path_quarantined_check=None,
    preflight_check=None,
) -> bool:
    """
    True when Cleanup Recommendations may enable Quarantine for *rec*.

    At least one redundant path must pass the preflight check. ``selected_path``
    is not required to enable the button — the picker supplies it when needed.
    """
    if not rec.has_redundant:
        return False

    paths = redundant_format_paths(rec)
    if not paths:
        return False

    check = path_quarantined_check
    if check is None:
        from app.core.quarantine import is_path_quarantined as check

    available = [p for p in paths if not check(p.path)]
    if not available:
        return False

    if preflight_check is None:
        from app.core.quarantine import preflight_quarantine_target

        def preflight_check(path: str) -> bool:
            return preflight_quarantine_target(
                path, scan_paths=scan_paths,
            ).can_offer_in_ui

    return any(preflight_check(p.path) for p in available)


def cleanup_quarantine_block_reason(
    rec: CleanupRecommendation,
    *,
    scan_paths: list[str] | None = None,
    path_quarantined_check=None,
) -> str:
    """Return a user-facing reason when Quarantine cannot be offered."""
    if not rec.has_redundant:
        return "No redundant formats for this product."
    paths = redundant_format_paths(rec)
    if not paths:
        return "No on-disk plug-in paths found for redundant formats."
    from app.core.quarantine import (
        is_path_quarantined,
        preflight_quarantine_target,
    )
    check = path_quarantined_check or is_path_quarantined
    available = [p for p in paths if not check(p.path)]
    if not available:
        return "All redundant copies are already in quarantine."
    for p in available:
        pf = preflight_quarantine_target(p.path, scan_paths=scan_paths)
        if pf.can_offer_in_ui:
            return ""
        if pf.not_writable:
            return pf.message
        if pf.message:
            return pf.message
    return "Quarantine is not available for this selection."


# ── Confidence engine ─────────────────────────────────────────────────────────

def _fmt_confidence(fmt: str, keep: list[str], profile: DawProfile) -> str:
    """
    Assess confidence for removing a single *fmt* given *keep* and *profile*.

    Rules (checked in order):
    1. AAX outside Pro Tools → always Review  (may be needed for Pro Tools)
    2. VST when VST3 or AU is kept → Safe  (clearly superseded by modern format)
    3. Format not in this profile's preferred list, but the profile's preferred
       IS present in keep → Safe  (the DAW's required format is satisfied; this
       format is genuinely redundant for that workflow)
    4. Anything else → Review
    """
    keep_set = set(keep)

    # Rule 1 — AAX outside Pro Tools is never Safe
    if fmt == "AAX" and profile.key != PROFILE_PRO_TOOLS:
        return CONF_REVIEW

    # Rule 2 — VST clearly superseded when VST3 or AU kept
    if fmt == "VST" and (keep_set & {"VST3", "AU"}):
        return CONF_SAFE

    # Rule 3 — format not needed by this profile, but profile's format is present
    if fmt not in profile.preferred and (keep_set & set(profile.preferred)):
        return CONF_SAFE

    return CONF_REVIEW


def _assess_confidence(keep: list[str], redundant: list[str], profile: DawProfile) -> str:
    """
    Return the most conservative confidence across all *redundant* formats.
    A single Review entry makes the whole recommendation Review.
    """
    if not redundant:
        return CONF_UNKNOWN

    for fmt in redundant:
        if _fmt_confidence(fmt, keep, profile) == CONF_REVIEW:
            return CONF_REVIEW
    return CONF_SAFE


# ── Recommendation engine ─────────────────────────────────────────────────────

def _recommend(group: FormatGroup, profile: DawProfile) -> CleanupRecommendation:
    """Build a :class:`CleanupRecommendation` for one :class:`FormatGroup`."""
    installed = set(group.formats.keys())

    # ── Single format: nothing to suggest ────────────────────────────────────
    if len(installed) <= 1:
        return CleanupRecommendation(
            product_name=group.product_name,
            developer=group.developer,
            installed_formats=dict(group.formats),
            keep_formats=list(installed),
            redundant_formats=[],
            confidence=CONF_UNKNOWN,
        )

    # ── Determine keep set ────────────────────────────────────────────────────
    # Keep formats that the profile prefers AND are actually installed.
    # This is the core fix: preferred is a SHORT DAW-specific list, so other
    # formats installed naturally fall into the redundant column.
    preferred_present = [f for f in profile.preferred if f in installed]

    if not preferred_present:
        # The profile's preferred formats aren't installed — cannot make a
        # safe recommendation; keep everything and flag as Unknown.
        return CleanupRecommendation(
            product_name=group.product_name,
            developer=group.developer,
            installed_formats=dict(group.formats),
            keep_formats=sorted(installed),
            redundant_formats=[],
            confidence=CONF_UNKNOWN,
        )

    keep = preferred_present[:]

    # never_remove formats that aren't already in keep still go into keep
    # (they must appear in the "keep" column even if not in preferred)
    for f in profile.never_remove:
        if f in installed and f not in keep:
            keep.append(f)

    # Redundant = installed formats not in keep
    redundant = [f for f in installed if f not in keep]

    if not redundant:
        return CleanupRecommendation(
            product_name=group.product_name,
            developer=group.developer,
            installed_formats=dict(group.formats),
            keep_formats=keep,
            redundant_formats=[],
            confidence=CONF_UNKNOWN,
        )

    confidence = _assess_confidence(keep, redundant, profile)

    return CleanupRecommendation(
        product_name=group.product_name,
        developer=group.developer,
        installed_formats=dict(group.formats),
        keep_formats=keep,
        redundant_formats=redundant,
        confidence=confidence,
    )


def analyze_cleanup(
    plugins: list[Plugin],
    profile: DawProfile | None = None,
) -> list[CleanupRecommendation]:
    """
    Analyze *plugins* and return one :class:`CleanupRecommendation` per
    logical product under the given *profile*.

    Results are sorted: items with redundant formats first (by recoverable
    space descending), then single-format products alphabetically.

    Defaults to the Ableton Live profile when *profile* is None, since its
    [VST3, AU] preferred list generates useful recommendations immediately
    for the most common multi-format installs.
    """
    if profile is None:
        profile = get_profile(PROFILE_ABLETON)

    groups = analyze_formats(plugins)
    recs = [_recommend(g, profile) for g in groups]

    with_redundant = sorted(
        [r for r in recs if r.has_redundant],
        key=lambda r: r.recoverable_size,
        reverse=True,
    )
    without_redundant = sorted(
        [r for r in recs if not r.has_redundant],
        key=lambda r: r.product_name.lower(),
    )
    return with_redundant + without_redundant
