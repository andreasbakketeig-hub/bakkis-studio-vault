"""
Confirmation dialog for moving a plug-in to quarantine.
"""

from __future__ import annotations

import tkinter as tk
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import customtkinter as ctk

from app.core.plugin_insights import PluginInsight
from app.core.quarantine import (
    PERMISSION_DENIED_MESSAGE,
    QuarantineError,
    ValidationResult,
    get_quarantine_display_root,
    get_quarantine_root,
    is_quarantine_path_movable,
    plan_quarantine_destination,
    preflight_quarantine_target,
    validate_quarantine_target,
)

BG = "#131720"
BG_INNER = "#181D2C"
TEXT = "#EEF0F8"
MUTED = "#94A3B8"
WARN = "#F59E0B"
DANGER = "#F87171"
ACCENT = "#6C8EF5"
BORDER = "#1C2038"
SYSTEM_FRAME = "#2A1E08"


@dataclass(frozen=True)
class QuarantineConfirmTarget:
    """Display + validation payload for the quarantine confirmation modal."""

    path: str
    plugin_name: str
    developer: str = ""
    fmt: str = ""
    issue_type: str = ""
    recommendation: str = ""
    extra_fields: tuple[tuple[str, str], ...] = ()

    @staticmethod
    def from_insight(insight: PluginInsight) -> QuarantineConfirmTarget:
        return QuarantineConfirmTarget(
            path=insight.path,
            plugin_name=insight.plugin_name,
            developer=insight.developer or "",
            fmt=insight.fmt or "",
            issue_type=insight.issue_type,
            recommendation=insight.recommendation,
        )


class QuarantineConfirmDialog(ctk.CTkToplevel):
    """Modal confirmation before quarantining a plug-in."""

    def __init__(
        self,
        parent: ctk.CTk,
        target: QuarantineConfirmTarget,
        on_confirm: Callable[[str, str, str, str, bool], None],
        scan_paths: list[str] | None = None,
        quarantine_root: str | Path | None = None,
        display_quarantine_root: str | None = None,
        **kwargs,
    ):
        super().__init__(parent, **kwargs)
        self._target = target
        self._on_confirm = on_confirm
        self._scan_paths = scan_paths
        self._quarantine_root = get_quarantine_root(quarantine_root)
        # Human-friendly label shown in the UI — not resolved through symlinks so
        # it matches the path string visible in the Settings view.
        self._display_quarantine_root = display_quarantine_root or get_quarantine_display_root()
        self._operation_id = ""
        self._dest_path: Path | None = None
        self._plan_error = ""
        self._validation = ValidationResult(False, "Loading…")
        self._needs_system_ack = False
        self._not_writable = False

        self.title("Move to Quarantine")
        self.configure(fg_color=BG)
        self.transient(parent)
        self.grab_set()

        self._validation = preflight_quarantine_target(
            target.path,
            root=self._quarantine_root,
            scan_paths=scan_paths,
        )
        self._needs_system_ack = self._validation.requires_system_ack
        self._not_writable = self._validation.not_writable

        self._build()
        self.geometry("580x640")
        self.resizable(False, False)
        self.after(50, self._center_on_parent, parent)
        self._update_helper_text()

    def _center_on_parent(self, parent: ctk.CTk) -> None:
        self.update_idletasks()
        px = parent.winfo_rootx() + (parent.winfo_width() // 2) - 290
        py = parent.winfo_rooty() + (parent.winfo_height() // 2) - 320
        self.geometry(f"+{max(px, 0)}+{max(py, 0)}")

    def _system_acknowledged(self) -> bool:
        if not self._needs_system_ack:
            return True
        return bool(self._system_ack_var.get())

    def _try_plan_destination(self) -> None:
        self._plan_error = ""
        if not self._ack_var.get():
            self._operation_id = ""
            self._dest_path = None
            self._update_helper_text()
            return
        if not self._system_acknowledged():
            self._operation_id = ""
            self._dest_path = None
            self._update_helper_text()
            return
        try:
            self._operation_id, self._dest_path = plan_quarantine_destination(
                self._target.path,
                root=self._quarantine_root,
                scan_paths=self._scan_paths,
                system_path_acknowledged=self._system_acknowledged(),
            )
            if hasattr(self, "_dest_label"):
                self._dest_label.configure(
                    text=str(self._dest_path) if self._dest_path else "—"
                )
        except QuarantineError as exc:
            self._operation_id = ""
            self._dest_path = None
            self._plan_error = str(exc)
            if hasattr(self, "_dest_label"):
                self._dest_label.configure(text=str(exc))
        self._update_helper_text()

    def _disabled_reason(self) -> str:
        if self._not_writable:
            return PERMISSION_DENIED_MESSAGE
        if not self._ack_var.get():
            return "Check the confirmation box to continue."
        if self._needs_system_ack and not self._system_acknowledged():
            return "System plug-in locations require the second confirmation box."
        if self._plan_error:
            return f"Destination could not be reserved: {self._plan_error}"
        if not self._dest_path or not self._operation_id:
            return "Confirm the checkboxes above to reserve a destination."
        if not is_quarantine_path_movable(self._target.path):
            return PERMISSION_DENIED_MESSAGE
        return ""

    def _update_helper_text(self) -> None:
        if not hasattr(self, "_helper_label"):
            return
        ready = (
            self._ack_var.get()
            and self._system_acknowledged()
            and self._dest_path is not None
            and self._operation_id
            and not self._not_writable
            and is_quarantine_path_movable(self._target.path)
        )
        if ready:
            self._helper_label.configure(
                text="Ready — press Move to Quarantine to proceed.",
                text_color=ACCENT,
            )
        else:
            reason = self._disabled_reason()
            self._helper_label.configure(text=reason, text_color=WARN)

    def _build(self) -> None:
        frame = ctk.CTkScrollableFrame(self, fg_color=BG, corner_radius=0)
        frame.pack(fill="both", expand=True, padx=20, pady=20)

        ctk.CTkLabel(
            frame,
            text="Move to Quarantine",
            font=ctk.CTkFont(size=18, weight="bold"),
            text_color=TEXT,
            anchor="w",
        ).pack(fill="x", pady=(0, 4))

        ctk.CTkLabel(
            frame,
            text="This is reversible if the original location is still available.",
            font=ctk.CTkFont(size=12),
            text_color=MUTED,
            anchor="w",
        ).pack(fill="x", pady=(0, 12))

        hard_fail = (
            (not self._validation.can_offer_in_ui)
            and not self._validation.requires_system_ack
        )
        if hard_fail:
            ctk.CTkLabel(
                frame,
                text=self._validation.message,
                font=ctk.CTkFont(size=12),
                text_color=DANGER,
                anchor="w",
                wraplength=520,
            ).pack(fill="x", pady=8)
            ctk.CTkButton(
                frame, text="Close", command=self.destroy,
                fg_color=BG_INNER, hover_color=BORDER,
            ).pack(pady=16)
            return

        tgt = self._target
        rows: list[tuple[str, str]] = [
            ("Plug-in", tgt.plugin_name),
            ("Developer", tgt.developer or "—"),
            ("Issue", tgt.issue_type or "—"),
            ("Format", tgt.fmt or "—"),
            ("Original path", tgt.path),
            ("Quarantine folder", self._display_quarantine_root),
            ("Reason", (tgt.recommendation or "")[:200]),
        ]
        rows.extend(list(tgt.extra_fields))

        for label, value in rows:
            block = ctk.CTkFrame(frame, fg_color=BG_INNER, corner_radius=8)
            block.pack(fill="x", pady=4)
            ctk.CTkLabel(
                block, text=label, font=ctk.CTkFont(size=10, weight="bold"),
                text_color=MUTED, anchor="w",
            ).pack(fill="x", padx=12, pady=(8, 0))
            ctk.CTkLabel(
                block, text=value, font=ctk.CTkFont(size=11),
                text_color=TEXT, anchor="w", wraplength=500,
            ).pack(fill="x", padx=12, pady=(2, 10))

        dest_block = ctk.CTkFrame(frame, fg_color=BG_INNER, corner_radius=8)
        dest_block.pack(fill="x", pady=4)
        ctk.CTkLabel(
            dest_block, text="Destination (reserved at confirm)",
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color=MUTED, anchor="w",
        ).pack(fill="x", padx=12, pady=(8, 0))
        self._dest_label = ctk.CTkLabel(
            dest_block, text="Confirm checkboxes to reserve destination…",
            font=ctk.CTkFont(size=11),
            text_color=TEXT, anchor="w", wraplength=500,
        )
        self._dest_label.pack(fill="x", padx=12, pady=(2, 10))

        for w in self._validation.warnings:
            ctk.CTkLabel(
                frame, text=f"⚠  {w}",
                font=ctk.CTkFont(size=11), text_color=WARN,
                anchor="w", wraplength=500,
            ).pack(fill="x", pady=2)

        if self._not_writable:
            ctk.CTkLabel(
                frame,
                text=PERMISSION_DENIED_MESSAGE,
                font=ctk.CTkFont(size=11),
                text_color=DANGER,
                anchor="w",
                wraplength=500,
            ).pack(fill="x", pady=(6, 4))

        if self._needs_system_ack and not self._not_writable:
            system_frame = ctk.CTkFrame(
                frame, fg_color=SYSTEM_FRAME, corner_radius=8,
                border_width=1, border_color=DANGER,
            )
            system_frame.pack(fill="x", pady=(6, 4))
            ctk.CTkLabel(
                system_frame,
                text=(
                    "⚠  System plug-in location (/Library/Audio/Plug-Ins)\n"
                    "The app will not request administrator privileges. "
                    "Check the box below if you still want to attempt this move."
                ),
                font=ctk.CTkFont(size=11),
                text_color=DANGER,
                anchor="w",
                wraplength=500,
                justify="left",
            ).pack(fill="x", padx=12, pady=(10, 6))

        self._ack_var = tk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            frame,
            text="I understand this will move the plug-in file and may affect DAW sessions.",
            variable=self._ack_var,
            font=ctk.CTkFont(size=11),
            text_color=TEXT,
            fg_color=ACCENT,
            hover_color=ACCENT,
            command=self._on_ack_change,
        ).pack(fill="x", pady=(12, 4))

        self._system_ack_var = tk.BooleanVar(value=False)
        if self._needs_system_ack and not self._not_writable:
            ctk.CTkCheckBox(
                frame,
                text=(
                    "I understand this is a system-wide plug-in location "
                    "and may affect all users."
                ),
                variable=self._system_ack_var,
                font=ctk.CTkFont(size=11, weight="bold"),
                text_color=TEXT,
                fg_color=DANGER,
                hover_color=WARN,
                border_color=DANGER,
                command=self._on_ack_change,
            ).pack(fill="x", padx=4, pady=(4, 8))

        self._helper_label = ctk.CTkLabel(
            frame,
            text="",
            font=ctk.CTkFont(size=11),
            text_color=WARN,
            anchor="w",
            wraplength=520,
            justify="left",
        )
        self._helper_label.pack(fill="x", pady=(4, 8))

        btn_row = ctk.CTkFrame(frame, fg_color="transparent")
        btn_row.pack(fill="x", pady=(8, 0))

        ctk.CTkButton(
            btn_row, text="Cancel", width=120,
            fg_color=BG_INNER, hover_color=BORDER,
            command=self.destroy,
        ).pack(side="right", padx=(8, 0))

        self._confirm_btn = ctk.CTkButton(
            btn_row, text="Move to Quarantine", width=160,
            fg_color=ACCENT, hover_color="#8BAAF7",
            command=self._confirm,
            state="disabled",
        )
        self._confirm_btn.pack(side="right")

        def _toggle() -> None:
            ready = (
                self._ack_var.get()
                and self._system_acknowledged()
                and self._dest_path is not None
                and self._operation_id
                and not self._not_writable
                and is_quarantine_path_movable(self._target.path)
            )
            self._confirm_btn.configure(state="normal" if ready else "disabled")
            self._update_helper_text()
            if self._ack_var.get() and self._system_acknowledged():
                self._try_plan_destination()

        self._toggle_fn = _toggle
        self._ack_var.trace_add("write", lambda *_: _toggle())
        self._system_ack_var.trace_add("write", lambda *_: _toggle())

    def _on_ack_change(self) -> None:
        self._toggle_fn()

    def _confirm(self) -> None:
        if not self._ack_var.get() or not self._dest_path or not self._operation_id:
            return
        if not self._system_acknowledged():
            return
        if self._not_writable or not is_quarantine_path_movable(self._target.path):
            return
        self._on_confirm(
            self._target.path,
            self._target.recommendation,
            self._operation_id,
            str(self._dest_path),
            self._system_acknowledged(),
        )
        self.destroy()
