"""Tests for studio_vault.api with fake scanners and a fake native bridge."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from studio_vault import api as api_mod
from studio_vault import config
from studio_vault import snapshot as snap
from studio_vault.app import NativeBridge, snapshot_files_from_drop
from studio_vault.scanners.plugins import Plugin, ScanResult

THIS_MAC = snap.hash_machine_id("TEST-UUID")


class FakeNative:
    def __init__(self, tmp: Path) -> None:
        self.tmp = tmp
        self.open_result: str | None = None
        self.save_result: str | None = None
        self.folder_result: str | None = None
        self.revealed: list[str] = []
        self.opened: list[str] = []
        self.trashed: list[str] = []
        self.copied: list[str] = []

    def choose_open_file(self, file_types):
        return self.open_result

    def choose_save_file(self, default_name, file_types):
        self.last_default_name = default_name
        return self.save_result

    def choose_folder(self):
        return self.folder_result

    def reveal_in_finder(self, path):
        self.revealed.append(path)

    def open_url(self, url):
        self.opened.append(url)

    def copy_to_clipboard(self, text):
        self.copied.append(text)

    def move_to_trash(self, path):
        self.trashed.append(path)
        Path(path).unlink()


PLUGINS = [Plugin("Serum", "VST3", "/Users/x/Library/Audio/Plug-Ins/VST3/Serum.vst3", "1.36", "Xfer Records",
                  "com.xferrecords.Serum", 100, "2026-01-01", "Instrument"),
           Plugin("Pro-Q 3", "AU", "/Library/Audio/Plug-Ins/Components/Pro-Q 3.component", "3.2", "FabFilter",
                  "com.fabfilter.Pro-Q.3", 50, "2026-01-01")]
APPS = [SimpleNamespace(name="Ableton Live 12 Suite", category="DAW", developer="Ableton", version="12.1",
                        path="/Applications/Ableton Live 12 Suite.app")]
HARDWARE = [SimpleNamespace(name="BiG SiX", vendor="Solid State Logic", device_type="Audio Interface",
                            connection_type="USB")]


@pytest.fixture
def scanners():
    """Fake scanners; tests mutate the lists to simulate a changed studio."""
    state = {"plugins": list(PLUGINS), "apps": list(APPS), "hardware": list(HARDWARE), "content": []}
    with patch.object(snap, "this_machine_id", return_value=THIS_MAC), \
         patch.object(snap, "this_machine_name", return_value="Studio Mac"), \
         patch.object(api_mod, "scan_plugins",
                      side_effect=lambda paths, progress_cb=None, cancel=None, size_cache=None:
                      ScanResult(plugins=list(state["plugins"]))), \
         patch.object(api_mod, "scan_music_apps", side_effect=lambda progress_cb=None: list(state["apps"])), \
         patch.object(api_mod, "scan_hardware",
                      side_effect=lambda debug_log=False: SimpleNamespace(devices=list(state["hardware"]))), \
         patch.object(api_mod.content, "find", side_effect=lambda names: list(state["content"])):
        yield state


@pytest.fixture
def native(tmp_path):
    return FakeNative(tmp_path)


@pytest.fixture
def vault(scanners, native):
    events: list[tuple[str, object]] = []
    a = api_mod.Api(native=native, emit=lambda e, d: events.append((e, d)))
    a._events = events
    return a


def run_scan(a: api_mod.Api) -> None:
    a.scan_start()
    a._scan_thread.join(timeout=5)
    assert a.state()["scan"]["status"] == api_mod.SCAN_DONE


def test_api_exposes_no_public_attributes(vault):
    public = [k for k in vars(vault) if not k.startswith("_")]
    assert public == []


def test_results_are_json_serialisable(vault):
    run_scan(vault)
    for result in (vault.state(), vault.snapshots(), vault.changes(), vault.about(),
                   vault.snapshot("current"), vault.checklist("current")):
        json.dumps(result)


def test_first_scan_auto_saves_and_has_no_changes(vault):
    run_scan(vault)
    st = vault.state()
    assert st["current"]["plugin_count"] == 2
    assert st["current_saved_id"]
    assert vault.changes()["changes"] is None
    assert len(vault.snapshots()["snapshots"]) == 1
    assert ("scan", {"status": "done", "phase": "", "message": "", "error": ""}) in vault._events


def test_unchanged_rescan_is_not_saved_again(vault):
    run_scan(vault)
    run_scan(vault)
    assert vault.changes()["changes"]["empty"] is True
    assert len(vault.snapshots()["snapshots"]) == 1


def test_changed_rescan_reports_and_saves(vault, scanners):
    run_scan(vault)
    scanners["plugins"].append(Plugin("Diva", "AU", "/Library/x/Diva.component", "1.4", "u-he"))
    scanners["hardware"].clear()
    run_scan(vault)
    ch = vault.changes()["changes"]
    assert ch["counts"]["plugins"]["added"] == 1
    assert ch["counts"]["hardware"]["removed"] == 1
    assert len(vault.snapshots()["snapshots"]) == 2


def test_no_auto_save_setting(vault):
    vault.set_settings({"auto_save_snapshot": False})
    run_scan(vault)
    assert vault.snapshots()["snapshots"] == []
    assert vault.save_snapshot("Before upgrade")["ok"]
    [s] = vault.snapshots()["snapshots"]
    assert s["name"] == "Before upgrade"


def test_state_shows_latest_snapshot_before_first_scan(vault, native, scanners):
    run_scan(vault)
    fresh = api_mod.Api(native=native)
    assert fresh.state()["current"] is None
    assert fresh.state()["latest"]["plugin_count"] == 2


def test_set_settings_ignores_unknown_and_internal_keys(vault):
    res = vault.set_settings({"scan_on_launch": True, "legacy_import_done": False, "evil": 1})
    assert res["settings"]["scan_on_launch"] is True
    assert config.load_settings().legacy_import_done is True


def test_scan_failure_is_reported(vault):
    with patch.object(api_mod, "scan_music_apps", side_effect=RuntimeError("boom")):
        vault.scan_start()
        vault._scan_thread.join(timeout=5)
    st = vault.state()["scan"]
    assert st["status"] == api_mod.SCAN_FAILED
    assert "boom" in st["error"]


def test_cancel_before_apps(vault):
    gate = threading.Event()

    def slow_plugins(paths, progress_cb=None, cancel=None, size_cache=None):
        gate.wait(2)
        return ScanResult(plugins=[])

    with patch.object(api_mod, "scan_plugins", side_effect=slow_plugins):
        vault.scan_start()
        vault.scan_cancel()
        gate.set()
        vault._scan_thread.join(timeout=5)
    assert vault.state()["scan"]["status"] == api_mod.SCAN_CANCELLED
    assert vault.state()["current"] is None


def test_export_import_and_trash(vault, native, tmp_path):
    run_scan(vault)
    [s] = vault.snapshots()["snapshots"]
    native.save_result = str(tmp_path / "share" / "studio")
    res = vault.export_snapshot(s["id"])
    assert res["ok"] and res["path"].endswith(".studiovault")
    assert native.last_default_name.endswith(".studiovault")

    assert vault.delete_snapshot(s["id"])["ok"]
    assert native.trashed and vault.snapshots()["snapshots"] == []

    native.open_result = res["path"]
    imported = vault.import_snapshot()
    assert imported["ok"] and imported["name"] == "Studio Mac"
    assert len(vault.snapshots()["snapshots"]) == 1


def test_dialog_cancel(vault):
    run_scan(vault)
    assert vault.export_snapshot("current") == {"ok": True, "cancelled": True}
    assert vault.import_snapshot() == {"ok": True, "cancelled": True}


def test_import_bad_file_is_a_friendly_error(vault, tmp_path):
    bad = tmp_path / "x.studiovault"
    bad.write_text("nope")
    res = vault.import_path(str(bad))
    assert res["ok"] is False and "Could not read" in res["error"]


def test_unknown_snapshot_id(vault):
    assert vault.snapshot("nope") == {"ok": False, "error": "That snapshot no longer exists."}
    assert vault.checklist("current")["error"] == "Scan this Mac first."


def test_rename(vault):
    run_scan(vault)
    sid = vault.snapshots()["snapshots"][0]["id"]
    assert vault.rename_snapshot(sid, "  ")["ok"] is False
    assert vault.rename_snapshot(sid, "Mac Studio — before macOS 28")["ok"]
    assert vault.snapshots()["snapshots"][0]["name"] == "Mac Studio — before macOS 28"


def test_checklist_and_tick(vault):
    run_scan(vault)
    sid = vault.snapshots()["snapshots"][0]["id"]
    c = vault.checklist(sid)["checklist"]
    assert c["total"] == c["done_count"] == 4    # everything is on this Mac
    other = snap.parse({**snap.load(snap.find_path(sid)).to_dict(), "id": "old-mac", "machine_id": "",
                        "plugins": [{"name": "Diva", "fmt": "AU", "developer": "u-he"}]})
    snap.save(other)
    c = vault.checklist("old-mac")["checklist"]
    diva = next(i for g in c["groups"] for i in g["items"] if i["name"] == "Diva")
    assert not diva["done"]
    c = vault.checklist_tick("old-mac", diva["id"], True)["checklist"]
    assert next(i for g in c["groups"] for i in g["items"] if i["name"] == "Diva")["done"]


def test_export_checklist_and_inventory(vault, native, tmp_path):
    run_scan(vault)
    sid = vault.snapshots()["snapshots"][0]["id"]
    native.save_result = str(tmp_path / "c")
    assert vault.export_checklist(sid, "html")["path"].endswith(".html")
    native.save_result = str(tmp_path / "c.csv")
    assert vault.export_checklist(sid, "csv")["ok"]
    native.save_result = str(tmp_path / "inv.csv")
    assert Path(vault.export_inventory(sid)["path"]).read_text(encoding="utf-8-sig").startswith("Type,")


def test_reveal_only_existing_absolute_paths(vault, native, tmp_path):
    f = tmp_path / "Thing.vst3"
    f.mkdir()
    assert vault.reveal(str(f))["ok"]
    assert native.revealed == [str(f)]
    assert vault.reveal("~/definitely/not/here.vst3")["ok"] is False
    assert vault.reveal("relative/path")["ok"] is False


def test_open_url_allows_only_https_and_mailto(vault, native):
    assert vault.open_url("https://bakkis.com")["ok"]
    assert vault.open_url("mailto:bakkis@bakkis.com")["ok"]
    assert vault.open_url("file:///etc/passwd")["ok"] is False
    assert vault.open_url("javascript:alert(1)")["ok"] is False
    assert native.opened == ["https://bakkis.com", "mailto:bakkis@bakkis.com"]


def test_without_native_bridge(scanners):
    a = api_mod.Api()
    assert a.import_snapshot() == {"ok": False, "error": "Not available."}


class TestBridge:
    def test_snapshot_files_from_drop(self, tmp_path):
        good = tmp_path / "a.studiovault"
        good.write_text("{}")
        legacy = tmp_path / "b.json"
        legacy.write_text("{}")
        (tmp_path / "c.txt").write_text("x")
        got = snapshot_files_from_drop([str(good), str(legacy), str(tmp_path / "c.txt"), None,
                                        str(tmp_path / "missing.studiovault")])
        assert got == [str(good), str(legacy)]

    def test_emit_escapes_data(self):
        calls = []
        bridge = NativeBridge(SimpleNamespace(evaluate_js=calls.append))
        bridge.emit("toast", {"text": "</script><b>\"x\""})
        assert calls == ['window.vault && vault.onEvent("toast", {"text": "</script><b>\\"x\\""})']

    def test_drop_imports_snapshot(self, vault, tmp_path):
        run_scan(vault)
        sid = vault.snapshots()["snapshots"][0]["id"]
        exported = snap.export(snap.load(snap.find_path(sid)), tmp_path / "x")
        snap.find_path(sid).unlink()
        calls = []
        bridge = NativeBridge(SimpleNamespace(evaluate_js=calls.append))
        bridge.api = vault
        bridge.on_drop({"dataTransfer": {"files": [{"pywebviewFullPath": str(exported)}]}})
        assert "Imported" in calls[0]
        assert len(vault.snapshots()["snapshots"]) == 1

    def test_drop_wrong_file_warns(self, tmp_path):
        calls = []
        bridge = NativeBridge(SimpleNamespace(evaluate_js=calls.append))
        bridge.on_drop({"dataTransfer": {"files": [{"pywebviewFullPath": str(tmp_path / "x.mp3")}]}})
        assert "warning" in calls[0]


def test_inventory_groups_formats_per_product(vault, scanners):
    scanners["plugins"].append(Plugin("Serum", "AU", "/Library/Audio/Plug-Ins/Components/Serum.component",
                                      "1.36", "Xfer Records", "", 40))
    run_scan(vault)
    inv = vault.inventory("current")
    serum = next(p for p in inv["products"] if p["name"] == "Serum")
    assert serum["formats"] == ["VST3", "AU"]
    assert serum["size"] == 140
    assert serum["vendor"] == "Xfer Records" and serum["matched"]
    assert [p["name"] for p in inv["products"]] == ["Pro-Q 3", "Serum"]
    assert inv["apps"][0]["name"] == "Ableton Live 12 Suite"
    assert inv["hardware"][0]["name"] == "BiG SiX"


def test_summary_counts(vault):
    run_scan(vault)
    cur = vault.state()["current"]
    assert cur["product_count"] == 2
    assert cur["vendor_count"] == 2
    assert cur["matched_pct"] == 100
    assert cur["hardware_names"] == ["BiG SiX"]


def test_add_and_remove_plugin_folder(vault, native):
    assert vault.add_plugin_folder() == {"ok": True, "cancelled": True}
    native.folder_result = "/Volumes/Plugins SSD/VST3"
    vault.add_plugin_folder()
    vault.add_plugin_folder()  # no duplicates
    assert vault.state()["settings"]["extra_plugin_folders"] == ["/Volumes/Plugins SSD/VST3"]
    vault.remove_plugin_folder("/Volumes/Plugins SSD/VST3")
    assert vault.state()["settings"]["extra_plugin_folders"] == []


def test_report_problem_mail_is_prefilled(vault):
    url = vault.about()["report_url"]
    assert url.startswith("mailto:bakkis@bakkis.com?subject=")
    assert "macOS" in url and " " not in url


def test_product_kind_vendor_url_and_copy_path(vault, native, scanners):
    scanners["plugins"].append(Plugin("Serum", "AAX", "/Library/x/Serum.aaxplugin", "1.36", "Xfer Records"))
    run_scan(vault)
    serum = next(p for p in vault.inventory("current")["products"] if p["name"] == "Serum")
    assert serum["kind"] == "Instrument"            # AAX copy inherits it from the VST3
    assert serum["vendor_url"].startswith("https://")
    res = vault.copy_path(serum["path"])
    assert res["ok"] and native.copied == [res["path"]]
    assert native.copied[0].endswith("/Library/Audio/Plug-Ins/VST3/Serum.vst3")
    assert not native.copied[0].startswith("~")
    assert vault.copy_path("")["ok"] is False


def test_side_by_side_api(vault, scanners):
    run_scan(vault)
    sid = vault.snapshots()["snapshots"][0]["id"]
    scanners["plugins"].pop()                  # Pro-Q 3 gone on "this Mac"
    run_scan(vault)
    res = vault.side_by_side(sid, "current")["compare"]
    assert res["counts"]["only_a"] == 1
    assert res["a"]["id"] == sid
    json.dumps(res)
    assert vault.side_by_side("nope", "current")["ok"] is False


def test_intel_only_products_and_summary(vault, scanners):
    scanners["plugins"] = [
        Plugin("Absynth 5", "VST", "/Library/a.vst", "5.3", "Native Instruments", arch="intel"),
        Plugin("Absynth 5", "AU", "/Library/a.component", "5.3", "Native Instruments", arch="intel"),
        Plugin("Mixed", "VST3", "/Library/m.vst3", "1", "Acme", arch="universal", min_macos="11.0"),
        Plugin("Mixed", "VST", "/Library/m.vst", "1", "Acme", arch="intel", min_macos="10.13"),
    ]
    run_scan(vault)
    products = {p["name"]: p for p in vault.inventory("current")["products"]}
    assert products["Absynth 5"]["arch"] == "intel"
    assert products["Mixed"]["arch"] == "mixed" and products["Mixed"]["intel_formats"] == ["VST"]
    assert products["Mixed"]["min_macos"] == "11.0"
    cur = vault.state()["current"]
    assert cur["intel_files"] == 3 and cur["intel_products"] == 2


def test_leave_list_api(vault, scanners):
    assert vault.leave_list()["ok"] is False                 # nothing scanned yet
    scanners["plugins"].append(Plugin("H-Delay", "AU", "/Library/x/H-Delay.component", "15", "Waves Audio Ltd."))
    run_scan(vault)
    res = vault.leave_list()["leave"]
    assert [i["title"] for i in res["licenses"]] == ["Waves"]
    assert res["export_id"] == "current"
    res = vault.leave_tick("license:waves", True)["leave"]
    assert res["licenses"][0]["done"] is True
    json.dumps(res)


def test_project_check_api(vault, native, tmp_path):
    from tests.v2.test_projects import write_als
    run_scan(vault)
    folder = tmp_path / "Live Projects"
    write_als(folder / "One Project" / "One.als")
    native.folder_result = str(folder)
    assert vault.projects_choose_folder()["ok"]
    vault._projects_thread.join(timeout=5)
    res = vault.projects_result()
    assert res["job"]["status"] == "done" and res["job"]["total"] == 1
    [p] = res["projects"]
    assert p["name"] == "One" and p["missing"] >= 1
    assert res["missing"]
    json.dumps(res)
    assert vault.projects_check_paths(["/x/notes.txt"])["ok"] is False
