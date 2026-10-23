#!/bin/bash
# Double-click to start BAKKIS STUDIO VAULT v2 from the source folder.
# Quits a copy that is already running first, so you always get the newest code.
set -euo pipefail

cd "$(cd "$(dirname "$0")" && pwd -P)"

if [ ! -x .venv/bin/python ]; then
  echo "Setting up for the first time (this takes a minute)…"
  PY=/Library/Frameworks/Python.framework/Versions/3.12/bin/python3.12
  [ -x "$PY" ] || PY=/usr/bin/python3
  "$PY" -m venv .venv
  .venv/bin/python -m pip install -q -r requirements.txt
fi

pkill -f "python -m studio_vault" 2>/dev/null && sleep 1 || true
exec .venv/bin/python -m studio_vault
