"""Every file-dialog filter must be one pywebview accepts (it raises ValueError otherwise, and the dialog never opens)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from webview.util import parse_file_type

SOURCE = Path(__file__).resolve().parents[2] / "studio_vault"
FILTERS = sorted({m for p in SOURCE.rglob("*.py") for m in re.findall(r'"([^"]*\(\*\.[^"]*\))"', p.read_text())})


def test_filters_found():
    assert len(FILTERS) >= 5


@pytest.mark.parametrize("file_type", FILTERS)
def test_pywebview_accepts_filter(file_type):
    parse_file_type(file_type)
