"""Shared fixtures for v2 (studio_vault) tests."""

from __future__ import annotations

import plistlib
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch) -> Path:
    """Point the app's data folder at a temp dir so tests never touch real user data."""
    data = tmp_path / "data"
    monkeypatch.setenv("STUDIO_VAULT_DATA_DIR", str(data))
    return data


def make_bundle(parent: Path, name: str, plist: dict | None = None, payload: int = 0) -> Path:
    """Create a fake macOS bundle (<name>/Contents/Info.plist) with *payload* bytes of content."""
    bundle = parent / name
    contents = bundle / "Contents"
    contents.mkdir(parents=True)
    with (contents / "Info.plist").open("wb") as fh:
        plistlib.dump(plist or {}, fh)
    if payload:
        (contents / "MacOS").mkdir()
        (contents / "MacOS" / "binary").write_bytes(b"\0" * payload)
    return bundle
