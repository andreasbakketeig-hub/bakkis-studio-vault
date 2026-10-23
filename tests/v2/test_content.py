"""Tests for studio_vault.content (presets and user content folders)."""

from __future__ import annotations

from studio_vault import content


def _file(path, size=10):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)


def test_known_and_vendor_folders(tmp_path):
    _file(tmp_path / "Music" / "Audio Music Apps" / "Patches" / "a.patch", 100)
    _file(tmp_path / "Music" / "Ableton" / "User Library" / "Presets" / "x.adg", 50)
    _file(tmp_path / "Music" / "Ableton" / "Factory Packs" / "big.alp", 999)
    _file(tmp_path / "Documents" / "KORG" / "preset.x", 5)
    _file(tmp_path / "Music" / "Spitfire Audio" / "s.json", 5)
    _file(tmp_path / "Documents" / "Taxes 2026" / "t.pdf", 5)
    (tmp_path / "Documents" / "oeksound").mkdir()
    found = {f.label: f for f in content.find(["Korg Inc", "Spitfire Audio", "oeksound"], home=tmp_path)}
    assert set(found) == {"Logic Pro: patches, channel strips, plug-in settings", "Ableton Live User Library",
                          "KORG (Documents)", "Spitfire Audio (Music)"}
    assert found["Logic Pro: patches, channel strips, plug-in settings"].size == 100
    assert found["Ableton Live User Library"].files == 1
    assert not found["KORG (Documents)"].approximate


def test_size_budget_marks_approximate(tmp_path):
    for i in range(50):
        _file(tmp_path / f"d{i}" / "f", 1)
    _size, _files, approximate = content.folder_size(tmp_path, budget=-1)
    assert approximate


def test_nothing_found(tmp_path):
    assert content.find(["Acme"], home=tmp_path) == []
