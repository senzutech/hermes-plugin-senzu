"""The recorded tool calls of each session, on disk so a gateway restart does not wipe a series
in progress."""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from . import home
from .stuck import HAMMER_WINDOW, Call, calls_from_json

log = logging.getLogger("hermes_plugins.senzu")

# Recorded histories untouched for this long belong to sessions nobody will come back to.
STALE_SECONDS = 7 * 24 * 3600


def _file(session_id: str) -> Path:
    safe = "".join(c for c in session_id if c.isalnum() or c in "-_") or "anonymous"
    return home.cache_dir() / f"{safe}.json"


def load(session_id: str) -> list[Call]:
    try:
        rows = json.loads(_file(session_id).read_text())
    except (OSError, ValueError):
        return []
    return calls_from_json(rows) if isinstance(rows, list) else []


def save(session_id: str, calls: list[Call]) -> None:
    path = _file(session_id)
    rows = [{"tool": call.tool, "failed": call.failed} for call in calls[-HAMMER_WINDOW:]]
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(rows))
        temporary.replace(path)
    except OSError as error:
        log.warning("senzu: history not written: %s", error)


def sweep() -> None:
    cutoff = time.time() - STALE_SECONDS
    try:
        for path in home.cache_dir().glob("*.json"):
            if path.stat().st_mtime < cutoff:
                path.unlink(missing_ok=True)
    except OSError:
        pass
