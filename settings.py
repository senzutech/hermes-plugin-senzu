"""The owner's settings, per installation: when Senzu is offered, and how the handover goes.

They live in ``config.yaml`` under ``plugins.entries.senzu`` and are read on every reply, so a
change takes effect at the next one, without restarting anything. Three ways to change them,
all writing the same keys: ``hermes senzu setup``, the ``senzu_settings`` tool the assistant
calls when its owner asks, or ``hermes config set``.
"""

from __future__ import annotations

import json
from typing import Any

from .stuck import HAMMERING

ASK, AUTO = "ask", "auto"
# Below three, ordinary work would trigger it; above fifty, it would never fire within the
# forty calls the reading looks at... except that the share rule still applies, so the cap is
# where the setting stops meaning anything.
THRESHOLD_RANGE = (3, 50)


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


def threshold() -> int:
    """Calls to one same tool before the offer. Out-of-range or unreadable values fall back."""
    try:
        value = int(_entry().get("threshold", HAMMERING))
    except (TypeError, ValueError):
        return HAMMERING
    low, high = THRESHOLD_RANGE
    return value if low <= value <= high else HAMMERING


def current() -> dict[str, Any]:
    return {"threshold": threshold(), "handover": mode()}


def change(threshold: int | None = None, handover: str | None = None) -> dict[str, Any]:
    """Write what was given, leave the rest as it is, and return the settings now in force."""
    from hermes_cli.config import set_config_value

    low, high = THRESHOLD_RANGE
    if threshold is not None:
        if not low <= int(threshold) <= high:
            raise ValueError(f"threshold must be between {low} and {high}")
        set_config_value("plugins.entries.senzu.threshold", str(int(threshold)), force=True)
    if handover is not None:
        if handover not in (ASK, AUTO):
            raise ValueError("handover must be 'ask' or 'auto'")
        set_config_value("plugins.entries.senzu.handover", handover, force=True)
    return current()


# --- The tool the assistant sees -----------------------------------------------------------------

TOOL_SCHEMA = {
    "name": "senzu_settings",
    "description": (
        "Settings only: read or change WHEN Senzu, the maintenance provider of this installation, "
        "is offered. This tool never hands anything over. When the owner answers « Senzu » or "
        "asks to hand a problem over to Senzu, call the Senzu MCP tool `senzu_signaler` instead. "
        "Call this one only when the owner explicitly asks to change the settings, for "
        "instance « propose Senzu moins souvent », « attends plus longtemps "
        "avant de proposer Senzu », or « envoie directement le dossier à Senzu ». "
        "`threshold` is how many calls to one same tool, without progress, trigger the offer "
        f"(default {HAMMERING}, allowed {THRESHOLD_RANGE[0]} to {THRESHOLD_RANGE[1]}): raise it to "
        "offer less often, lower it to offer sooner. `handover` is `ask` (default: offer and wait "
        "for the owner's « Senzu ») or `auto` (send the dossier to Senzu right away; the owner "
        "still approves the work before anything is done). Call with no argument to read the "
        "current settings. Changes apply from the next reply, no restart needed. Tell the owner "
        "what changed."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "threshold": {
                "type": "integer",
                "minimum": THRESHOLD_RANGE[0],
                "maximum": THRESHOLD_RANGE[1],
                "description": "Calls to one same tool before Senzu is offered.",
            },
            "handover": {
                "type": "string",
                "enum": [ASK, AUTO],
                "description": "ask: offer and wait; auto: send the dossier right away.",
            },
        },
    },
}


def tool_handler(args: dict | None = None, **_: Any) -> str:
    args = args or {}
    try:
        settings = change(args.get("threshold"), args.get("handover"))
    except (ValueError, TypeError) as error:
        return json.dumps({"error": str(error)})
    except Exception as error:  # a config write that fails must not break the turn
        return json.dumps({"error": f"settings not saved: {error}"})
    return json.dumps(settings)
