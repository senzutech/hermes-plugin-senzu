"""Telling the owner when Senzu moves on a handover.

A webhook would need the owner's gateway to be reachable from the internet, which most are not.
So the plugin asks instead, through the same MCP connection it already has: one call per
installation, whatever the number of handovers, and only while one is open. The desk says when
to ask again (two minutes after something happened, up to half an hour when it goes quiet) and
zero once nothing is open, which stops the asking until the next handover is filed.

The words the owner reads are the desk's; this module only carries them.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any

from . import access, handover

log = logging.getLogger("hermes_plugins.senzu")

# How long to wait after a failed check before trying again.
RETRY_SECONDS = 300
# The first check after a handover is filed.
FIRST_CHECK_SECONDS = 120

_wake = threading.Event()
_started = threading.Lock()
_running = False


def _state_file():
    return handover.hermes_home() / "cache" / "senzu" / "news.json"


def _load() -> dict:
    try:
        state = json.loads(_state_file().read_text())
    except (OSError, ValueError):
        return {}
    return state if isinstance(state, dict) else {}


def _save(state: dict) -> None:
    path = _state_file()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(state))
        temporary.replace(path)
    except OSError as error:
        log.warning("senzu: news state not written: %s", error)


def activate(where: dict | None) -> None:
    """A handover was just filed: start asking, and tell the owner in this chat."""
    state = _load()
    state["active"] = True
    state["next_at"] = min(state.get("next_at") or float("inf"), time.time() + FIRST_CHECK_SECONDS)
    if where:
        state["where"] = where
    _save(state)
    _wake.set()


def _parse(answer: Any) -> dict | None:
    """The tool's JSON text, however Hermes wrapped it."""
    value = answer.get("result") if isinstance(answer, dict) else answer
    for _ in range(3):
        if isinstance(value, dict) and "cursor" in value:
            return value
        if isinstance(value, dict) and isinstance(value.get("result"), str):
            value = value["result"]
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except ValueError:
                return None
    return value if isinstance(value, dict) and "cursor" in value else None


def check_once(ctx: Any) -> float:
    """Ask the desk once, deliver what it says, and return the seconds until the next check,
    or 0 to stop."""
    state = _load()
    arguments = {} if state.get("cursor") is None else {"depuis": state["cursor"]}
    news = _parse(ctx.call_mcp(handover.DESK, "senzu_nouvelles", arguments, timeout=30))
    if news is None:
        raise ValueError("unreadable answer from senzu_nouvelles")
    where = state.get("where")
    for update in news.get("updates") or []:
        text = update.get("text") if isinstance(update, dict) else None
        if text and where:
            handover.send(where, text)
    state["cursor"] = news.get("cursor")
    # Open Senzu's access while a paid handover is in progress, close it after; tell the owner,
    # and tell the desk where to connect.
    report = access.reconcile(bool(news.get("acces_requis")), state.get("access_reported"))
    if report is not None:
        state["access_reported"] = "open" if report["etat"] == "ouvert" else "closed"
        if where:
            handover.send(where, access.owner_message(report))
        confirm = {"acces": report}
        if state.get("cursor") is not None:
            confirm["depuis"] = state["cursor"]
        ctx.call_mcp(handover.DESK, "senzu_nouvelles", confirm, timeout=30)
    delay = float(news.get("next_check_seconds") or 0)
    state["active"] = delay > 0
    state["next_at"] = time.time() + delay if delay > 0 else None
    _save(state)
    return delay


def _loop(ctx: Any) -> None:
    while True:
        state = _load()
        if not state.get("active") or not handover.Gateway.ready():
            # Asleep until a handover is filed or the gateway shows up; a periodic look covers
            # a restart with a series still open.
            _wake.wait(timeout=60)
            _wake.clear()
            continue
        wait = (state.get("next_at") or 0) - time.time()
        if wait > 0:
            _wake.wait(timeout=wait)
            _wake.clear()
            continue
        try:
            check_once(ctx)
        except Exception as error:  # a failed check is retried later, never raised into Hermes
            log.warning("senzu: news check failed: %s", error)
            state = _load()
            state["next_at"] = time.time() + RETRY_SECONDS
            _save(state)


def start(ctx: Any) -> None:
    """Start the one background checker of this process. It sleeps until there is something to
    ask about, so a process that is not the gateway never makes a call."""
    global _running
    with _started:
        if _running:
            return
        _running = True
    threading.Thread(target=_loop, args=(ctx,), name="senzu-news", daemon=True).start()
