"""
Pick exactly one redundant plug-in path before quarantine from Cleanup Recommendations.
"""

from __future__ import annotations

import tkinter as tk
from typing import Callable

import customtkinter as ctk

from app.core.cleanup import CleanupRecommendation, RedundantFormatPath, redundant_format_paths
from app.core.quarantine import PERMISSION_DENIED_MESSAGE, preflight_quarantine_target
from app.core.scanner import _fmt_size

BG = "#131720"
BG_INNER = "#181D2C"
TEXT = "#EEF0F8"
MUTED = "#94A3B8"
ACCENT = "#6C8EF5"
BORDER = "#1C2038"


class CleanupFormatPickerDialog(ctk.CTkToplevel):
    """Let the user choose one redundant format copy to quarantine."""

    def __init__(
        self,
        parent: ctk.CTk,
        rec: CleanupRecommendation,
        on_select: Callable[[RedundantFormatPath], None],
        *,
        path_quarantined_check=None,
        scan_paths: list[str] | None = None,
        **kwargs,
    ):
        super().__init__(parent, **kwargs)
        self._rec = rec
        self._on_select = on_select
        self._check = path_quarantined_check
        self._scan_paths = scan_paths

        self.title("Choose format to quarantine")
        self.configure(fg_color=BG)
        self.transient(parent)
        self.grab_set()

        self._paths = redundant_format_paths(rec)
        if self._check:
            self._paths = [p for p in self._paths if not self._check(p.path)]
        self._paths = [
            p for p in self._paths
            if preflight_quarantine_target(
                p.path, scan_paths=scan_paths,
            ).can_offer_in_ui
        ]

        self._choice_var = tk.StringVar(value="")
        self._build()
        self.geometry("560x420")
        self.resizable(False, False)
        self.after(50, self._center_on_parent, parent)

    def _center_on_parent(self, parent: ctk.CTk) -> None:
        self.update_idletasks()
        px = parent.winfo_rootx() + (parent.winfo_width() // 2) - 280
        py = parent.winfo_rooty() + (parent.winfo_height() // 2) - 210
        self.geometry(f"+{max(px, 0)}+{max(py, 0)}")

    def _build(self) -> None:
        frame = ctk.CTkFrame(self, fg_color=BG)
        frame.pack(fill="both", expand=True, padx=20, pady=20)

        ctk.CTkLabel(
            frame,
            text="Choose one file to quarantine",
            font=ctk.CTkFont(size=16, weight="bold"),
            text_color=TEXT,
            anchor="w",
        ).pack(fill="x", pady=(0, 4))

        ctk.CTkLabel(
            frame,
            text=(
                f"{self._rec.product_name} has multiple redundant formats. "
                "Only one plug-in bundle can be moved at a time."
            ),
            font=ctk.CTkFont(size=12),
            text_color=MUTED,
            anchor="w",
            wraplength=500,
        ).pack(fill="x", pady=(0, 12))

        if not self._paths:
            ctk.CTkLabel(
                frame,
                text=(
                    "No movable redundant paths are available.\n\n"
                    f"{PERMISSION_DENIED_MESSAGE}"
                ),
                font=ctk.CTkFont(size=12),
                text_color=MUTED,
                anchor="w",
                wraplength=500,
                justify="left",
            ).pack(fill="x", pady=8)
            ctk.CTkButton(
                frame, text="Close", command=self.destroy,
                fg_color=BG_INNER, hover_color=BORDER,
            ).pack(pady=12)
            return

        scroll = ctk.CTkScrollableFrame(frame, fg_color=BG, height=220)
        scroll.pack(fill="both", expand=True)

        for item in self._paths:
            row = ctk.CTkFrame(scroll, fg_color=BG_INNER, corner_radius=8)
            row.pack(fill="x", pady=4)
            rb = ctk.CTkRadioButton(
                row,
                text="",
                variable=self._choice_var,
                value=item.path,
                fg_color=ACCENT,
                hover_color=ACCENT,
                border_color=BORDER,
            )
            rb.pack(side="left", padx=(12, 4), pady=10)
            text = ctk.CTkFrame(row, fg_color="transparent")
            text.pack(side="left", fill="x", expand=True, padx=(0, 12), pady=8)
            ctk.CTkLabel(
                text,
                text=f"{item.fmt}  ·  {_fmt_size(item.plugin.file_size)}",
                font=ctk.CTkFont(size=12, weight="bold"),
                text_color=TEXT,
                anchor="w",
            ).pack(fill="x")
            ctk.CTkLabel(
                text,
                text=item.path,
                font=ctk.CTkFont(size=10),
                text_color=MUTED,
                anchor="w",
                wraplength=440,
            ).pack(fill="x")

        if len(self._paths) == 1:
            self._choice_var.set(self._paths[0].path)

        btn_row = ctk.CTkFrame(frame, fg_color="transparent")
        btn_row.pack(fill="x", pady=(12, 0))

        ctk.CTkButton(
            btn_row, text="Cancel", width=100,
            fg_color=BG_INNER, hover_color=BORDER,
            command=self.destroy,
        ).pack(side="right", padx=(8, 0))

        ctk.CTkButton(
            btn_row, text="Continue", width=120,
            fg_color=ACCENT, hover_color="#8BAAF7",
            command=self._continue,
        ).pack(side="right")

    def _continue(self) -> None:
        chosen = self._choice_var.get()
        if not chosen:
            return
        for item in self._paths:
            if item.path == chosen:
                self._on_select(item)
                self.destroy()
                return
