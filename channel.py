"""Reaching the owner: the running gateway, where a session's owner is, and sending them a message.

Everything goes through Hermes' gateway, so it reaches the owner on whatever channel they use.
"""

from __future__ import annotations

import json
import sys
from typing import Any

from . import home


class Gateway:
    """The running gateway and its event loop.

    ``pre_gateway_dispatch`` is the documented way for a plugin to reach
    ``gateway.adapters[platform].send``, but it only fires on an inbound message. Until one
    arrives, the runner is found the way Hermes' own send_message tool finds it, so a gateway
    restarted with a handover open keeps checking on it. Outside the gateway (``hermes chat``)
    there is none, and the offer stays in the reply.
    """

    runner: Any = None
    loop: Any = None

    @classmethod
    def capture(cls, gateway: Any) -> None:
        import asyncio

        cls.runner = gateway
        try:
            cls.loop = asyncio.get_running_loop()
        except RuntimeError:
            pass

    @classmethod
    def discover(cls) -> None:
        # Only look where the gateway already is: importing it into another process would be
        # heavy and find nothing.
        module = sys.modules.get("gateway.run")
        reference = getattr(module, "_gateway_runner_ref", None)
        runner = reference() if callable(reference) else None
        loop = getattr(runner, "_gateway_loop", None)
        if runner is not None and loop is not None:
            cls.runner, cls.loop = runner, loop

    @classmethod
    def ready(cls) -> bool:
        if cls.runner is None or cls.loop is None:
            cls.discover()
        return cls.runner is not None and cls.loop is not None


def origin(session_id: str) -> dict | None:
    """Where a session's owner is reached: platform, chat and thread, from Hermes' session map."""
    try:
        sessions = json.loads((home.hermes_home() / "sessions" / "sessions.json").read_text())
    except (OSError, ValueError):
        return None
    for key, entry in sessions.items():
        if isinstance(entry, dict) and entry.get("session_id") == session_id:
            found = dict(entry.get("origin") or {})
            if found.get("platform") and found.get("chat_id"):
                found["session_key"] = entry.get("session_key") or key
                return found
    return None


def send(where: dict, text: str) -> Any:
    """Send one message to the owner through the gateway adapter of their platform, and return
    its message id when the platform gives one."""
    import asyncio

    # Keys are Hermes' Platform enum; match on its value rather than importing gateway internals.
    adapter = next(
        (
            adapter
            for key, adapter in Gateway.runner.adapters.items()
            if getattr(key, "value", key) == where["platform"]
        ),
        None,
    )
    if adapter is None:
        raise RuntimeError(f"no adapter for {where['platform']}")
    thread = where.get("thread_id")
    metadata = {"thread_id": thread} if thread is not None else None
    coroutine = adapter.send(str(where["chat_id"]), text, metadata=metadata)
    result = asyncio.run_coroutine_threadsafe(coroutine, Gateway.loop).result(timeout=30)
    return getattr(result, "message_id", None)
