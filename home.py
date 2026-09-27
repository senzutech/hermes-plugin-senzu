"""Where Hermes keeps things, and where this plugin keeps its own."""

from __future__ import annotations

import os
from pathlib import Path


def hermes_home() -> Path:
    return Path(os.environ.get("HERMES_HOME") or Path.home() / ".hermes")


def env(name: str) -> str | None:
    """A variable from the process, else from Hermes' ``.env``."""
    if os.environ.get(name):
        return os.environ[name]
    try:
        for line in (hermes_home() / ".env").read_text().splitlines():
            key, _, value = line.partition("=")
            if key.strip() == name:
                return value.strip().strip("\"'") or None
    except OSError:
        pass
    return None


def cache_dir() -> Path:
    """The plugin's own files: recorded calls, open offers, the news cursor."""
    return hermes_home() / "cache" / "senzu"
