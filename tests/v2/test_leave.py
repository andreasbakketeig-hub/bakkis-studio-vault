"""Tests for studio_vault.leave ("Before you leave this Mac")."""

from __future__ import annotations

import datetime

from studio_vault import leave
from studio_vault.snapshot import SnapApp, SnapPlugin, Snapshot


def _mac(plugins=(), apps=(), created_at=None) -> Snapshot:
    created = created_at or datetime.datetime.now().isoformat(timespec="seconds")
    return Snapshot(id="mine", name="Studio", machine_name="Studio", machine_id="x", created_at=created,
                    plugins=list(plugins), apps=list(apps))


def test_vendors_with_machine_bound_licenses():
    mac = _mac([SnapPlugin("H-Delay", "AU", "Waves Audio Ltd."), SnapPlugin("CLA-2A", "VST3", "", bundle_id="com.wavesaudio.cla2a"),
                SnapPlugin("Decapitator", "AU", "Soundtoys"), SnapPlugin("Pro-Q 3", "AU", "FabFilter")])
    lst = leave.build(mac, manual=set())
    by_title = {i.title: i for i in lst.licenses}
    assert set(by_title) == {"Soundtoys", "Waves"}           # FabFilter needs nothing
    assert by_title["Waves"].products == ["CLA-2A", "H-Delay"]
    assert "Waves Central" in by_title["Waves"].detail
    assert "iLok" in by_title["Soundtoys"].detail


def test_waveshells_collapse():
    mac = _mac([SnapPlugin("WaveShell1-AU 14.12", "AU", "Waves Audio Ltd."), SnapPlugin("WaveShell1-VST3 15.0", "VST3", "Waves")])
    [w] = leave.build(mac, manual=set()).licenses
    assert w.products == ["WaveShell (all Waves plug-ins)"]


def test_backup_step_lists_content_folders():
    from studio_vault.snapshot import SnapContent
    mac = _mac()
    assert leave.build(mac, manual=set()).backup == []
    mac.content = [SnapContent("Ableton Live User Library", "~/Music/Ableton/User Library", 16_000_000_000, 38000, True)]
    lst = leave.build(mac, manual=set())
    assert [i.id for i in lst.backup] == [leave.STEP_BACKUP]
    assert lst.folders[0]["path"] == "~/Music/Ableton/User Library"
    assert lst.folders[0]["approximate"] is True


def test_ilok_reminder_from_installed_app_only():
    lst = leave.build(_mac(apps=[SnapApp("iLok License Manager")]), manual=set())
    assert [i.id for i in lst.licenses] == ["license:ilok"]


def test_no_double_ilok_reminder():
    lst = leave.build(_mac([SnapPlugin("Decapitator", "AU", "Soundtoys")], [SnapApp("iLok License Manager")]), manual=set())
    assert [i.id for i in lst.licenses] == ["license:soundtoys"]


def test_steps_ticks_and_freshness():
    old = _mac(created_at="2020-01-01T00:00:00")
    lst = leave.build(old, manual={leave.STEP_COPY})
    assert not lst.snapshot_is_fresh
    assert [i.id for i in lst.snapshot] == [leave.STEP_SNAPSHOT]
    assert lst.finish[0].done
    assert leave.build(_mac(), manual=set()).snapshot_is_fresh
