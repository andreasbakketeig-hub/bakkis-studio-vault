"""Tests for studio_vault.report."""

from __future__ import annotations

import csv

import pytest

from studio_vault import checklist as cl
from studio_vault import report
from studio_vault.snapshot import SnapApp, SnapHardware, SnapPlugin, Snapshot


def _snap(id="old", plugins=(), apps=(), hardware=()) -> Snapshot:
    return Snapshot(id=id, name="Old <Mac>", machine_name="Old Mac", machine_id="",
                    created_at="2026-06-01T10:00:00",
                    plugins=list(plugins), apps=list(apps), hardware=list(hardware))


OLD = _snap(
    plugins=[SnapPlugin("Serum", "VST3", "Xfer Records", "1.36"),
             SnapPlugin("Serum", "AU", "Xfer Records", "1.36"),
             SnapPlugin("<script>alert(1)</script>", "AU", "Evil & Co", "1.0"),
             SnapPlugin("=HYPERLINK(\"http://x\")", "VST", "Sheet Dev", "1.0")],
    apps=[SnapApp("Ableton Live 12 Suite", "DAW", "Ableton", "12.1")],
    hardware=[SnapHardware("H90 Pedal", "Eventide", "MIDI Device", "MIDI")],
)
NEW = _snap(id="new", plugins=[SnapPlugin("Serum", "VST3", "Xfer Records", "1.36")])


@pytest.fixture
def checklist():
    return cl.build(OLD, NEW, manual_done=set())


@pytest.mark.parametrize("value,expected", [
    ("=SUM(A1)", "'=SUM(A1)"), ("+1", "'+1"), ("-cmd", "'-cmd"), ("@x", "'@x"),
    ("Serum", "Serum"), (12, "12"), (None, ""),
])
def test_csv_cell(value, expected):
    assert report.csv_cell(value) == expected


def test_checklist_html_is_escaped_and_self_contained(checklist):
    page = report.checklist_html(checklist)
    assert "<script>alert(1)</script>" not in page
    assert "&lt;script&gt;" in page
    assert "Old &lt;Mac&gt;" in page
    assert "<script" not in page.lower()
    for remote in ("src=", "<link", "@import", "url("):  # nothing loaded from elsewhere
        assert remote not in page
    assert "Xfer Records" in page
    assert "Partly installed — missing AU" in page
    assert "Hardware" in page and "H90 Pedal" in page
    assert "https://www.eventideaudio.com/" in page  # driver link
    assert f"0 of {checklist.total} done" in page


def test_write_checklist_html_adds_suffix(checklist, tmp_path):
    out = report.write_checklist_html(checklist, tmp_path / "out" / "New Mac")
    assert out.name == "New Mac.html"
    assert out.read_text(encoding="utf-8").startswith("<!doctype html>")


def test_checklist_csv(checklist, tmp_path):
    out = report.checklist_csv(checklist, tmp_path / "c.csv")
    rows = list(csv.reader(out.open(encoding="utf-8-sig")))
    assert rows[0][:3] == ["Vendor", "Type", "Name"]
    assert len(rows) == 1 + checklist.total
    serum = next(r for r in rows if r[2] == "Serum")
    assert serum[0] == "Xfer Records"
    assert serum[4] == "VST3 AU"
    assert serum[5].startswith("Partly installed")
    assert any(r[2] == "'=HYPERLINK(\"http://x\")" for r in rows)
    assert any(r[1] == "hardware" and r[2] == "H90 Pedal" for r in rows)


def test_inventory_csv(tmp_path):
    out = report.inventory_csv(OLD, tmp_path / "inv.csv")
    rows = list(csv.reader(out.open(encoding="utf-8-sig")))
    assert rows[0][0] == "Type"
    assert [r[0] for r in rows[1:]].count("Plug-in") == 4
    assert ["App", "Ableton Live 12 Suite"] == rows[5][:2]
    assert rows[-1][:2] == ["Hardware", "H90 Pedal"]


def test_status_text_manual_tick():
    item = cl.ChecklistItem(id="x", kind="plugin", name="X", manual_done=True)
    assert report.item_status_text(item) == "Done (ticked)"
