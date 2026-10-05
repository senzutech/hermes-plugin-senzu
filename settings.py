"""The owner's settings, per installation: when Senzu is offered, and how the handover goes.

They live in ``config.yaml`` under ``plugins.entries.senzu`` and are read on every reply, so a
change takes effect at the next one, without restarting anything. They are changed from the
command line (``hermes senzu setup``, ``hermes config set``), never through a tool the model can
see: a model that knows about settings and modes recites them to the owner instead of handing
over, which is what happened the one time it had such a tool.
"""

from __future__ import annotations

from typing import Any

ASK, AUTO = "ask", "auto"
ON, OFF = "on", "off"


def _entry() -> dict:
    try:
        from hermes_cli.config import load_config

        plugins = (load_config() or {}).get("plugins") or {}
        return (plugins.get("entries") or {}).get("senzu") or {}
    except Exception:
        return {}


def mode() -> str:
    """``auto`` only when the owner chose it; anything else, or no config at all, asks."""
    return AUTO if _entry().get("handover") == AUTO else ASK


def mood() -> bool:
    """Whether the owner's messages are read for dissatisfaction. On unless turned off: it is one
    short call on the installation's own model per message the owner writes."""
    return _entry().get("mood", ON) != OFF


def current() -> dict[str, Any]:
    return {"handover": mode(), "mood": ON if mood() else OFF}


def change(handover: str | None = None, mood: str | None = None) -> dict[str, Any]:
    """Write what was given, leave the rest as it is, and return the settings now in force."""
    from hermes_cli.config import set_config_value

    if handover is not None:
        if handover not in (ASK, AUTO):
            raise ValueError("handover must be 'ask' or 'auto'")
        set_config_value("plugins.entries.senzu.handover", handover, force=True)
    if mood is not None:
        if mood not in (ON, OFF):
            raise ValueError("mood must be 'on' or 'off'")
        set_config_value("plugins.entries.senzu.mood", mood, force=True)
    return current()
