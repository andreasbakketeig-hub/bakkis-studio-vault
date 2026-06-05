"""
Responsive ttk.Treeview column layout helpers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Sequence

from tkinter import ttk

from app.utils.helpers import truncate

# Approximate pixels per character at 12 pt UI font.
_CHAR_PX = 7
_VSB_GUTTER = 18


@dataclass(frozen=True)
class FixedColumn:
    col_id: str
    width: int
    anchor: str = "w"


@dataclass(frozen=True)
class FlexColumn:
    col_id: str
    weight: float
    min_width: int
    anchor: str = "w"


@dataclass(frozen=True)
class TreeColumnLayout:
    fixed: tuple[FixedColumn, ...]
    flex: tuple[FlexColumn, ...]


def _measure_host_width(hosts: Sequence) -> int:
    """Return width from the innermost mapped host; fall back to parents."""
    for host in hosts:
        try:
            width = host.winfo_width()
        except Exception:
            continue
        if width > 1:
            return width
    return 0


def apply_tree_column_layout(
    tree: ttk.Treeview,
    layout: TreeColumnLayout,
    available_width: int,
) -> dict[str, int]:
    """Set column widths to fit *available_width*; return assigned widths."""
    if available_width <= 1:
        return {}

    usable = max(available_width - _VSB_GUTTER, 1)
    fixed_total = sum(col.width for col in layout.fixed)
    flex_min_total = sum(col.min_width for col in layout.flex)
    remaining = usable - fixed_total

    widths: dict[str, int] = {}

    for col in layout.fixed:
        widths[col.col_id] = col.width
        tree.heading(col.col_id, anchor=col.anchor)
        tree.column(
            col.col_id,
            width=col.width,
            minwidth=col.width,
            stretch=False,
            anchor=col.anchor,
        )

    if not layout.flex:
        return widths

    if remaining < flex_min_total:
        for col in layout.flex:
            widths[col.col_id] = col.min_width
            tree.heading(col.col_id, anchor=col.anchor)
            tree.column(
                col.col_id,
                width=col.min_width,
                minwidth=col.min_width,
                stretch=True,
                anchor=col.anchor,
            )
        return widths

    extra = remaining - flex_min_total
    weight_total = sum(col.weight for col in layout.flex) or 1.0
    allocated = 0
    flex_cols = list(layout.flex)

    for i, col in enumerate(flex_cols):
        if i == len(flex_cols) - 1:
            width = max(col.min_width, remaining - allocated)
        else:
            width = col.min_width + int(extra * (col.weight / weight_total))
            width = max(col.min_width, width)
            allocated += width
        widths[col.col_id] = width
        tree.heading(col.col_id, anchor=col.anchor)
        tree.column(
            col.col_id,
            width=width,
            minwidth=col.min_width,
            stretch=True,
            anchor=col.anchor,
        )

    return widths


def bind_responsive_tree_columns(
    tree: ttk.Treeview,
    host,
    layout: TreeColumnLayout,
    on_layout: Callable[[dict[str, int]], None] | None = None,
    *,
    extra_hosts: Sequence | None = None,
) -> Callable[[], None]:
    """Re-layout columns when any *host* is resized.

    Returns a callable that forces an immediate re-layout (e.g. after navigation).
    """
    hosts: list = []
    for candidate in (host, *(extra_hosts or ())):
        if candidate is not None and candidate not in hosts:
            hosts.append(candidate)

    last_width = [-1]

    def _relayout(_event=None, *, force: bool = False) -> None:
        width = _measure_host_width(hosts)
        if width <= 1:
            return
        if not force and width == last_width[0]:
            return
        last_width[0] = width
        assigned = apply_tree_column_layout(tree, layout, width)
        if on_layout:
            on_layout(assigned)

    def force_relayout() -> None:
        last_width[0] = -1
        _relayout(force=True)

    for h in hosts:
        h.bind("<Configure>", _relayout, add="+")

    try:
        toplevel = tree.winfo_toplevel()
        toplevel.bind("<Configure>", _relayout, add="+")
    except Exception:
        pass

    tree.bind("<Map>", lambda _e: force_relayout(), add="+")

    tree.after_idle(force_relayout)
    for delay in (50, 150, 400):
        tree.after(delay, force_relayout)

    return force_relayout


def truncate_for_column(text: str, column_width: int, char_px: int = _CHAR_PX) -> str:
    """Ellipsize *text* to fit a tree column width (paths)."""
    max_len = max(12, column_width // char_px)
    if len(text) <= max_len:
        return text
    return truncate(text, max_len)
