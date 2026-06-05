"""
Cleanup Recommendations — analyze plugin format redundancy and produce
safe, read-only suggestions for which formats could be removed.

No files are deleted or quarantined by this module.
"""

from __future__ import annotations

from dataclasses import dataclass, field
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
    *,
    _profile_override: DawProfile | None = None,
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


# ── Actionability model ───────────────────────────────────────────────────────

ACT_ACTIONABLE    = "actionable_quarantine"
ACT_SYSTEM_LOCKED = "system_locked"
ACT_NEEDS_PICKER  = "needs_picker"
ACT_MISSING_PATH  = "missing_path"
ACT_ALREADY_QUAR  = "already_quarantined"
ACT_UNSUPPORTED   = "unsupported"

_ACT_LABELS: dict[str, str] = {
    ACT_ACTIONABLE:    "Can Quarantine",
    ACT_SYSTEM_LOCKED: "System Locked",
    ACT_NEEDS_PICKER:  "Choose Format",
    ACT_MISSING_PATH:  "No Path",
    ACT_ALREADY_QUAR:  "Already Quarantined",
    ACT_UNSUPPORTED:   "Manual Cleanup",
}

SYSTEM_LOCKED_REASON = (
    "This plug-in is installed in a protected system location. "
    "Studio Vault does not use administrator permissions. "
    "Use Reveal in Finder or the vendor's installer/uninstaller."
)


@dataclass(frozen=True)
class RowActionability:
    """Actionability classification for one redundant format copy."""

    fmt: str
    plugin: Plugin | None
    path: str
    status: str
    reason: str
    recoverable_size: int

    @property
    def label(self) -> str:
        return _ACT_LABELS.get(self.status, self.status)

    @property
    def recoverable_size_human(self) -> str:
        return _fmt_size(self.recoverable_size) if self.recoverable_size else "—"

    @property
    def is_actionable(self) -> bool:
        return self.status in (ACT_ACTIONABLE, ACT_NEEDS_PICKER)

    @property
    def is_system_locked(self) -> bool:
        return self.status == ACT_SYSTEM_LOCKED


def _is_system_path(path: str) -> bool:
    """True when *path* lives in a system-owned location."""
    p = str(Path(path).expanduser())
    return p.startswith(("/Library/", "/System/", "/Applications/"))


def classify_row_actionability(
    rec: CleanupRecommendation,
    fmt: str,
    *,
    scan_paths: list[str] | None = None,
) -> RowActionability:
    """
    Classify one redundant format copy for actionability.
    No files are read or moved; only path metadata is checked.
    """
    plugin = rec.installed_formats.get(fmt)
    path = (plugin.path or "").strip() if plugin else ""
    size = plugin.file_size if plugin else 0

    def _make(status: str, reason: str) -> RowActionability:
        return RowActionability(
            fmt=fmt, plugin=plugin, path=path,
            status=status, reason=reason, recoverable_size=size,
        )

    if not path:
        return _make(ACT_MISSING_PATH, "No file path recorded for this format.")

    try:
        exists = Path(path).expanduser().exists()
    except OSError:
        exists = False
    if not exists:
        return _make(ACT_MISSING_PATH, "File path no longer exists on disk.")

    from app.core.quarantine import is_path_quarantined  # noqa: PLC0415
    if is_path_quarantined(path):
        return _make(ACT_ALREADY_QUAR, "This copy is already in quarantine.")

    from app.core.quarantine import preflight_quarantine_target  # noqa: PLC0415
    pf = preflight_quarantine_target(path, scan_paths=scan_paths)

    if pf.can_offer_in_ui or pf.requires_system_ack:
        return _make(ACT_ACTIONABLE, "Studio Vault can move this file to quarantine.")

    if pf.not_writable or _is_system_path(path):
        return _make(ACT_SYSTEM_LOCKED, SYSTEM_LOCKED_REASON)

    return _make(ACT_UNSUPPORTED, pf.message or "Not eligible for quarantine.")


def classify_rec_actionability(
    rec: CleanupRecommendation,
    *,
    scan_paths: list[str] | None = None,
) -> tuple[str, str]:
    """
    Return ``(status, reason)`` for a whole recommendation.

    Priority: actionable/needs_picker > system_locked > already_quarantined
              > missing_path > unsupported.
    """
    if not rec.has_redundant:
        return ACT_UNSUPPORTED, "No redundant formats for this product."

    row_acts = [
        classify_row_actionability(rec, fmt, scan_paths=scan_paths)
        for fmt in rec.redundant_formats
    ]

    actionable = [a for a in row_acts if a.status == ACT_ACTIONABLE]
    if actionable:
        if len(actionable) > 1 or requires_format_picker(rec):
            return ACT_NEEDS_PICKER, "Multiple redundant formats — choose one to quarantine."
        return ACT_ACTIONABLE, actionable[0].reason

    if any(a.status == ACT_SYSTEM_LOCKED for a in row_acts):
        locked = next(a for a in row_acts if a.status == ACT_SYSTEM_LOCKED)
        return ACT_SYSTEM_LOCKED, locked.reason

    if all(a.status == ACT_ALREADY_QUAR for a in row_acts):
        return ACT_ALREADY_QUAR, "All redundant copies are already in quarantine."

    if any(a.status == ACT_MISSING_PATH for a in row_acts):
        missing = next(a for a in row_acts if a.status == ACT_MISSING_PATH)
        return ACT_MISSING_PATH, missing.reason

    return ACT_UNSUPPORTED, "Not eligible for quarantine."


@dataclass
class ActionabilitySummary:
    """Aggregated actionability counts and recoverable sizes."""

    recs_actionable: int = 0
    recs_system_locked: int = 0
    recs_needs_picker: int = 0
    recs_already_quar: int = 0
    recs_missing: int = 0
    recs_unsupported: int = 0

    actionable_bytes: int = 0
    system_locked_bytes: int = 0
    total_bytes: int = 0

    @property
    def total_recs_with_status(self) -> int:
        return (
            self.recs_actionable + self.recs_needs_picker
            + self.recs_system_locked + self.recs_already_quar
            + self.recs_missing + self.recs_unsupported
        )

    @property
    def actionable_size_human(self) -> str:
        return _fmt_size(self.actionable_bytes) if self.actionable_bytes else "0 B"

    @property
    def system_locked_size_human(self) -> str:
        return _fmt_size(self.system_locked_bytes) if self.system_locked_bytes else "0 B"

    @property
    def total_size_human(self) -> str:
        return _fmt_size(self.total_bytes) if self.total_bytes else "0 B"


def cleanup_actionability_summary(
    recs: list[CleanupRecommendation],
    *,
    scan_paths: list[str] | None = None,
) -> ActionabilitySummary:
    """Aggregate actionability counts and sizes across all recommendations."""
    s = ActionabilitySummary()
    for rec in recs:
        if not rec.has_redundant:
            continue

        # Classify each format once, reuse for both rec-level and byte totals.
        row_acts = {
            fmt: classify_row_actionability(rec, fmt, scan_paths=scan_paths)
            for fmt in rec.redundant_formats
        }

        for act in row_acts.values():
            s.total_bytes += act.recoverable_size
            if act.status == ACT_ACTIONABLE:
                s.actionable_bytes += act.recoverable_size
            elif act.status == ACT_SYSTEM_LOCKED:
                s.system_locked_bytes += act.recoverable_size

        actionable_rows = [a for a in row_acts.values() if a.status == ACT_ACTIONABLE]
        if actionable_rows:
            if len(actionable_rows) > 1 or requires_format_picker(rec):
                s.recs_needs_picker += 1
            else:
                s.recs_actionable += 1
        elif any(a.status == ACT_SYSTEM_LOCKED for a in row_acts.values()):
            s.recs_system_locked += 1
        elif all(a.status == ACT_ALREADY_QUAR for a in row_acts.values()):
            s.recs_already_quar += 1
        elif any(a.status == ACT_MISSING_PATH for a in row_acts.values()):
            s.recs_missing += 1
        else:
            s.recs_unsupported += 1

    return s


def generate_cleanup_report_rows(
    recs: list[CleanupRecommendation],
    *,
    scan_paths: list[str] | None = None,
) -> list[dict]:
    """Build export rows (one per redundant format copy) for CSV / Markdown."""
    rows: list[dict] = []
    for rec in recs:
        if not rec.has_redundant:
            continue
        installed_str = ", ".join(sorted(rec.installed_formats.keys()))
        keep_str = ", ".join(rec.keep_formats) if rec.keep_formats else ""
        for fmt in rec.redundant_formats:
            act = classify_row_actionability(rec, fmt, scan_paths=scan_paths)
            if act.status in (ACT_ACTIONABLE, ACT_NEEDS_PICKER):
                suggested = "Quarantine via Studio Vault"
            elif act.status == ACT_SYSTEM_LOCKED:
                suggested = "Use vendor uninstaller or Reveal in Finder"
            elif act.status == ACT_ALREADY_QUAR:
                suggested = "Already quarantined — no action needed"
            elif act.status == ACT_MISSING_PATH:
                suggested = "Locate file manually"
            else:
                suggested = "Manual review required"

            rows.append({
                "Product":                  rec.product_name,
                "Developer":                rec.developer or "",
                "Installed Formats":        installed_str,
                "Keep Formats":             keep_str,
                "Redundant Format":         fmt,
                "File Path":                act.path,
                "Actionability":            act.label,
                "Reason":                   act.reason,
                "Est. Recoverable (bytes)": act.recoverable_size,
                "Est. Recoverable":         act.recoverable_size_human,
                "Confidence":               rec.confidence,
                "Suggested Action":         suggested,
            })
    return rows
