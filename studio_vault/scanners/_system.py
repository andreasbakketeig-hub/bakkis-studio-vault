"""
Shared wrapper around ``system_profiler``.

Every scanner that reads system_profiler goes through :func:`run_system_profiler`
so tests can replace one function with recorded JSON instead of running the tool.
"""

from __future__ import annotations

import json
import subprocess
from typing import Any

DEFAULT_TIMEOUT = 60


def run_system_profiler(
    data_type: str,
    timeout: int = DEFAULT_TIMEOUT,
) -> tuple[dict[str, Any] | None, str | None]:
    """Run ``system_profiler <data_type> -json`` and return (payload, error)."""
    cmd = ["system_profiler", data_type, "-json"]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, f"{data_type}: {exc}"

    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip() or f"exit {proc.returncode}"
        return None, f"{data_type}: {err}"

    try:
        return json.loads(proc.stdout), None
    except json.JSONDecodeError as exc:
        snippet = (proc.stdout or "")[:200]
        return None, f"{data_type}: invalid JSON ({exc}); snippet={snippet!r}"
