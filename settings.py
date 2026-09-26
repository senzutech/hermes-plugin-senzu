"""The owner's settings, per installation: when Senzu is offered, and how the handover goes.

They live in ``config.yaml`` under ``plugins.entries.senzu`` and are read on every reply, so a
change takes effect at the next one, without restarting anything. They are changed from the
command line (``hermes senzu setup``, ``hermes config set``), never through a tool the model can
see: a model that knows about thresholds and modes recites them to the owner instead of handing
over, which is what happened the one time it had such a tool.
"""

from __future__ import annotations

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
