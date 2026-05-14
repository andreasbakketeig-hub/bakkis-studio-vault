"""
CSV export utility for scan results.
"""

from __future__ import annotations

import csv
import datetime
from pathlib import Path

from app.core.scanner import Plugin

HEADERS = ["Name", "Developer", "Version", "Format", "Size", "Modified", "Path"]


def export_csv(plugins: list[Plugin], dest: Path | str | None = None) -> Path:
    """
    Write *plugins* to a CSV file.

    If *dest* is None the file is written to ~/Desktop with a timestamped name.
    Returns the path that was written.
    """
    if dest is None:
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        dest = Path.home() / "Desktop" / f"bakkis_plugins_{ts}.csv"

    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)

    with dest.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(HEADERS)
        for p in plugins:
            writer.writerow([
                p.name,
                p.developer,
                p.version,
                p.fmt,
                p.file_size_human,
                p.modified,
                p.path,
            ])

    return dest
