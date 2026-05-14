"""
Cleanup Recommendations — analyze plugin format redundancy and produce
safe, read-only suggestions for which formats could be removed.

No files are deleted or quarantined by this module.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.scanner import FormatGroup, Plugin, _fmt_size, analyze_formats

# ── Preferred format order (user-configurable, this is the default) ───────────

PREFERRED_FORMATS: list[str] = ["VST3", "AU", "VST", "AAX"]

# ── Confidence levels ─────────────────────────────────────────────────────────

CONF_SAFE    = "Safe"
CONF_REVIEW  = "Review"
CONF_UNKNOWN = "Unknown"

# Minimum recoverable bytes to be considered "high disk usage"
HIGH_DISK_THRESHOLD = 50 * 1024 * 1024  # 50 MB


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
        """Total bytes that could be freed by removing redundant formats."""
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


# ── Recommendation engine ─────────────────────────────────────────────────────

def _assess_confidence(keep: list[str], redundant: list[str]) -> str:
    """
    Determine confidence for a recommendation given which formats to keep
    and which are flagged as redundant.

    Rules (in order):
    - Safe   — VST is redundant and VST3 is being kept (clear supersession)
    - Safe   — AU is redundant and VST3 is kept, no AAX involved
    - Review — AAX is in the redundant list (may be needed for Pro Tools)
    - Safe   — only legacy formats (VST) redundant while modern (VST3/AU) kept
    - Review — anything else that has redundancy
    """
    if not redundant:
        return CONF_UNKNOWN

    redundant_set = set(redundant)
    keep_set = set(keep)

    # AAX is always Review — cannot safely remove without knowing Pro Tools usage
    if "AAX" in redundant_set:
        return CONF_REVIEW

    # VST superseded by VST3 → Safe
    if redundant_set == {"VST"} and "VST3" in keep_set:
        return CONF_SAFE

    # AU + VST redundant while VST3 kept → Safe (no AAX involved)
    if "VST3" in keep_set and not (redundant_set & {"AAX"}):
        return CONF_SAFE

    return CONF_REVIEW


def _recommend(
    group: FormatGroup,
    preferred: list[str],
) -> CleanupRecommendation:
    """Build a :class:`CleanupRecommendation` for one :class:`FormatGroup`."""
    installed = set(group.formats.keys())

    if len(installed) <= 1:
        # Single format — nothing to flag
        return CleanupRecommendation(
            product_name=group.product_name,
            developer=group.developer,
            installed_formats=dict(group.formats),
            keep_formats=list(installed),
            redundant_formats=[],
            confidence=CONF_UNKNOWN,
        )

    # Formats to keep: preferred order filtered to what's actually installed
    keep = [f for f in preferred if f in installed]

    if not keep:
        # None of the preferred formats installed — keep everything, flag unknown
        keep = sorted(installed)
        redundant: list[str] = []
        confidence = CONF_UNKNOWN
    else:
        redundant = [f for f in installed if f not in keep]
        confidence = _assess_confidence(keep, redundant)

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
    preferred: list[str] | None = None,
) -> list[CleanupRecommendation]:
    """
    Analyze *plugins* and return one :class:`CleanupRecommendation` per
    logical product.

    Results are sorted: items with redundant formats first (by recoverable
    space descending), then single-format products alphabetically.
    """
    if preferred is None:
        preferred = PREFERRED_FORMATS

    groups = analyze_formats(plugins)
    recs = [_recommend(g, preferred) for g in groups]

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
