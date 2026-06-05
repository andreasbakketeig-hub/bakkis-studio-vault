"""
Quarantined Items — list and restore plug-ins moved to quarantine.
"""

from __future__ import annotations

import subprocess
import tkinter as tk
from tkinter import messagebox, ttk

import customtkinter as ctk

from app.core.quarantine import (
    ATTENTION_STATUSES,
    QuarantineError,
    QuarantineOperation,
    STATUS_FAILED,
    STATUS_PENDING,
    STATUS_QUARANTINED,
    get_quarantine_root,
    restore_from_quarantine,
    safe_load_manifest,
)

BG_CARD = "#131720"
BG_TABLE = "#0D1020"
BG_TABLE_ROW = "#131720"
BG_TABLE_ROW_ALT = "#161B28"
BG_TABLE_SEL = "#1B2848"
ACCENT = "#6C8EF5"
ACCENT_HOVER = "#8BAAF7"
TEXT_PRIMARY = "#EEF0F8"
TEXT_MUTED = "#94A3B8"
WARN = "#F59E0B"
DANGER = "#F87171"
BORDER = "#1C2038"


class QuarantinedItemsView(ctk.CTkFrame):
    """View quarantined plug-ins and restore them when safe."""

    def __init__(
        self,
        parent: ctk.CTkFrame,
        on_restore_complete=None,
        **kwargs,
    ):
        super().__init__(parent, fg_color="transparent", **kwargs)
        self._on_restore_complete = on_restore_complete
        self._ops: list[QuarantineOperation] = []
        self._iid_to_op: dict[str, QuarantineOperation] = {}
        self._manifest_error: str | None = None

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)
        self._build()

    def refresh(self) -> None:
        self._manifest_error = None
        self._ops = []
        data, err = safe_load_manifest()
        if err:
            self._manifest_error = err
        elif data is not None:
            ops = [
                QuarantineOperation.from_dict(o)
                for o in data.get("operations", [])
            ]
            self._ops = [o for o in ops if o.status in ATTENTION_STATUSES]
            self._ops.sort(key=lambda o: o.timestamp, reverse=True)
        self._populate()

    def _build(self) -> None:
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=30, pady=(28, 0))

        ctk.CTkLabel(
            header,
            text="Quarantined Items",
            font=ctk.CTkFont(size=22, weight="bold"),
            text_color=TEXT_PRIMARY,
        ).grid(row=0, column=0, sticky="w")

        ctk.CTkLabel(
            header,
            text="Reversible moves only — nothing is permanently deleted.",
            font=ctk.CTkFont(size=12),
            text_color=TEXT_MUTED,
        ).grid(row=1, column=0, sticky="w", pady=(4, 0))

        ctk.CTkLabel(
            header,
            text=f"Folder: {get_quarantine_root()}",
            font=ctk.CTkFont(size=10),
            text_color=TEXT_MUTED,
        ).grid(row=2, column=0, sticky="w", pady=(6, 0))

        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.grid(row=1, column=0, sticky="ew", padx=30, pady=(14, 0))
        ctk.CTkButton(
            bar, text="↻  Refresh", width=100, height=32,
            fg_color=BG_CARD, hover_color=BORDER,
            command=self.refresh,
        ).pack(side="left")

        container = ctk.CTkFrame(
            self, fg_color=BG_CARD, corner_radius=14,
            border_width=1, border_color=BORDER,
        )
        container.grid(row=2, column=0, sticky="nsew", padx=30, pady=(14, 22))
        container.grid_rowconfigure(1, weight=1)
        container.grid_columnconfigure(0, weight=1)

        self._error_frame = ctk.CTkFrame(container, fg_color="transparent")
        self._error_frame.grid(row=0, column=0, sticky="ew", padx=16, pady=(12, 0))
        self._error_frame.grid_columnconfigure(0, weight=1)
        self._error_label = ctk.CTkLabel(
            self._error_frame,
            text="",
            font=ctk.CTkFont(size=12),
            text_color=DANGER,
            anchor="w",
            wraplength=700,
            justify="left",
        )
        self._error_label.grid(row=0, column=0, sticky="ew")
        ctk.CTkButton(
            self._error_frame,
            text="⌘  Reveal quarantine folder",
            width=200,
            height=32,
            fg_color=BG_CARD,
            hover_color=BORDER,
            command=self._reveal_quarantine_folder,
        ).grid(row=1, column=0, sticky="w", pady=(8, 0))
        self._error_frame.grid_remove()

        tree_frame = tk.Frame(container, bg=BG_TABLE)
        tree_frame.grid(row=1, column=0, sticky="nsew", padx=16, pady=12)
        tree_frame.grid_rowconfigure(0, weight=1)
        tree_frame.grid_columnconfigure(0, weight=1)

        style = ttk.Style()
        style.configure(
            "Quarantine.Treeview",
            background=BG_TABLE, foreground=TEXT_PRIMARY,
            fieldbackground=BG_TABLE, rowheight=34,
            font=("SF Pro Text", 11),
        )
        style.configure(
            "Quarantine.Treeview.Heading",
            background=BG_TABLE, foreground=TEXT_MUTED,
            font=("SF Pro Text", 10),
        )

        cols = ("status", "plugin", "original", "quarantine", "date", "reason")
        self._tree = ttk.Treeview(
            tree_frame, columns=cols, show="headings",
            style="Quarantine.Treeview", selectmode="browse",
        )
        for cid, title, w in (
            ("status", "STATUS", 110),
            ("plugin", "PLUGIN", 120),
            ("original", "ORIGINAL PATH", 180),
            ("quarantine", "QUARANTINE PATH", 180),
            ("date", "DATE", 90),
            ("reason", "REASON", 160),
        ):
            self._tree.heading(cid, text=title)
            self._tree.column(cid, width=w, minwidth=70)

        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=vsb.set)
        self._tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        self._tree.bind("<<TreeviewSelect>>", self._on_select)

        self._empty = ctk.CTkLabel(
            container, text="No items in quarantine.",
            font=ctk.CTkFont(size=13), text_color=TEXT_MUTED,
        )
        self._empty.grid(row=1, column=0)

        status = ctk.CTkFrame(self, fg_color="transparent")
        status.grid(row=3, column=0, sticky="ew", padx=30, pady=(0, 22))
        status.grid_columnconfigure(0, weight=1)

        self._status = ctk.CTkLabel(
            status, text="", font=ctk.CTkFont(size=11), text_color=TEXT_MUTED, anchor="w",
        )
        self._status.grid(row=0, column=0, sticky="w")

        self._reveal_btn = ctk.CTkButton(
            status, text="⌘  Reveal in Finder", width=150, height=34,
            fg_color=BG_CARD, hover_color=BORDER, state="disabled",
            command=self._reveal,
        )
        self._reveal_btn.grid(row=0, column=1, padx=(0, 8))

        self._restore_btn = ctk.CTkButton(
            status, text="↩  Restore", width=120, height=34,
            fg_color=ACCENT, hover_color=ACCENT_HOVER, state="disabled",
            command=self._restore_selected,
        )
        self._restore_btn.grid(row=0, column=2)

        self.refresh()

    def _status_label(self, op: QuarantineOperation) -> str:
        if op.status == STATUS_PENDING:
            return "Needs attention"
        if op.status == STATUS_FAILED:
            return "Failed"
        return "Quarantined"

    def _populate(self) -> None:
        for iid in self._tree.get_children():
            self._tree.delete(iid)
        self._iid_to_op.clear()

        if self._manifest_error:
            self._error_frame.grid()
            self._error_label.configure(
                text=(
                    f"Could not load quarantine manifest:\n{self._manifest_error}\n\n"
                    "Your quarantine folder is unchanged. Use Reveal in Finder to inspect it."
                ),
            )
            self._empty.grid_remove()
            self._tree.grid_remove()
            self._status.configure(text="Manifest load failed")
            self._set_action_buttons(False)
            return

        self._error_frame.grid_remove()
        self._tree.grid()

        if not self._ops:
            self._empty.grid()
            self._status.configure(text="0 item(s) needing attention")
            self._set_action_buttons(False)
            return

        self._empty.grid_remove()
        for i, op in enumerate(self._ops):
            parity = "even" if i % 2 == 0 else "odd"
            reason = (op.reason or "")[:60]
            if op.status == STATUS_FAILED and op.error_message:
                reason = op.error_message[:80]
            elif op.status == STATUS_PENDING:
                reason = "Move was not completed — check original path or retry from Plugin Health."
            iid = self._tree.insert(
                "", "end",
                values=(
                    self._status_label(op),
                    op.plugin_name,
                    op.original_path,
                    op.quarantine_path or "—",
                    op.timestamp[:10] if op.timestamp else "",
                    reason,
                ),
                tags=(parity, op.status),
            )
            self._iid_to_op[iid] = op

        active = sum(1 for o in self._ops if o.status == STATUS_QUARANTINED)
        pending_failed = sum(
            1 for o in self._ops if o.status in (STATUS_PENDING, STATUS_FAILED)
        )
        parts = [f"{active} quarantined"]
        if pending_failed:
            parts.append(f"{pending_failed} need attention")
        self._status.configure(text=", ".join(parts))

    def _on_select(self, _event=None) -> None:
        op = self._selected_op()
        can_restore = op is not None and op.status == STATUS_QUARANTINED
        can_reveal = op is not None and bool(
            op.quarantine_path if op.status == STATUS_QUARANTINED else op.original_path
        )
        self._restore_btn.configure(
            state="normal" if can_restore else "disabled",
            text_color=TEXT_PRIMARY if can_restore else TEXT_MUTED,
        )
        self._reveal_btn.configure(
            state="normal" if can_reveal else "disabled",
            text_color=TEXT_PRIMARY if can_reveal else TEXT_MUTED,
        )

    def _set_action_buttons(self, on: bool) -> None:
        state = "normal" if on else "disabled"
        color = TEXT_PRIMARY if on else TEXT_MUTED
        self._reveal_btn.configure(state=state, text_color=color)
        self._restore_btn.configure(state=state, text_color=color)

    def _selected_op(self) -> QuarantineOperation | None:
        sel = self._tree.selection()
        if not sel:
            return None
        return self._iid_to_op.get(sel[0])

    def _reveal_quarantine_folder(self) -> None:
        subprocess.run(["open", str(get_quarantine_root())], check=False)

    def _reveal(self) -> None:
        op = self._selected_op()
        if not op:
            return
        path = op.quarantine_path if op.status == STATUS_QUARANTINED else op.original_path
        if path:
            subprocess.run(["open", "-R", path], check=False)

    def _restore_selected(self) -> None:
        op = self._selected_op()
        if not op or op.status != STATUS_QUARANTINED:
            return
        if not messagebox.askyesno(
            "Restore plug-in",
            f"Move back to original location?\n\n{op.original_path}\n\n"
            "This is reversible only if the destination is empty.",
        ):
            return
        try:
            result = restore_from_quarantine(op.operation_id)
            messagebox.showinfo("Restore complete", result.message)
            self.refresh()
            if self._on_restore_complete:
                self._on_restore_complete()
        except QuarantineError as exc:
            messagebox.showerror("Restore failed", str(exc))
            if op.quarantine_path:
                subprocess.run(["open", "-R", op.quarantine_path], check=False)
