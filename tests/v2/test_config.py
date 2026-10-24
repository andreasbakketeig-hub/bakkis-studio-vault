"""Tests for studio_vault.config."""

from __future__ import annotations

import json

from studio_vault import config


def test_data_dir_follows_env(isolated_data_dir):
    assert config.data_dir() == isolated_data_dir
    config.ensure_data_dirs()
    assert config.snapshots_dir().is_dir()
    assert config.checklists_dir().is_dir()


def test_defaults_when_missing():
    assert config.load_settings() == config.Settings()


def test_round_trip():
    s = config.Settings(scan_on_launch=True, extra_plugin_folders=["/Volumes/Plugins"])
    config.save_settings(s)
    assert config.load_settings() == s


def test_bad_values_fall_back_to_defaults():
    config.settings_path().parent.mkdir(parents=True, exist_ok=True)
    config.settings_path().write_text(json.dumps({
        "scan_on_launch": "yes",
        "extra_plugin_folders": ["/ok", 3, "  "],
        "unknown_key": 1,
    }))
    s = config.load_settings()
    assert s.scan_on_launch is False
    assert s.extra_plugin_folders == ["/ok"]


def test_corrupt_file_gives_defaults():
    config.settings_path().parent.mkdir(parents=True, exist_ok=True)
    config.settings_path().write_text("{oops")
    assert config.load_settings() == config.Settings()
