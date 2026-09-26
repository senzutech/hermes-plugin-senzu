"""Senzu for Hermes Agent: hand a stuck assistant over to the people who maintain it.

Two things, both decided by arithmetic and never by the model:

* before a critical action (mass deletion, payment, public post…), Hermes' approval gate opens
  with the warning first and the Senzu offer after it;
* when the assistant keeps hammering at a problem it cannot solve, the owner is offered a
  handover: a card with a button on Telegram, a line of text everywhere else.

See README.md for installation.
"""

from __future__ import annotations

import logging
import threading

from . import cli, guard, handover, stuck

log = logging.getLogger("hermes_plugins.senzu")

_ctx = None
# Sessions whose reply deserved the offer this turn, waiting for post_llm_call and its history,
# with the text offer to send instead of the card if anything on the way fails.
_pending: dict[str, str] = {}


def on_tool_call(tool_name="", args=None, **_):
    rule = guard.assess(tool_name, args)
    if rule is not None and rule.criticality is guard.Criticality.CRITICAL:
        return guard.approval(rule)
    return None


def on_tool_result(tool_name="", session_id="", status="", **_):
    # Only the verdict is kept, never the output: it can be large and it can hold secrets.
    calls = handover.load(session_id)
    calls.append(stuck.call_from_hook(tool_name, status))
    handover.save(session_id, calls)


def on_reply(response_text="", session_id="", platform="", **_):
    calls = handover.load(session_id)
    if not calls or not response_text:
        return None
    reading = stuck.read(calls)
    log.info("senzu: %d calls, offer %s", len(calls), reading.deserves_an_offer)
    if not reading.deserves_an_offer:
        return None
    # Offered once: the repetition has to build up again before the owner is asked twice.
    handover.save(session_id, [])
    offer = handover.text_offer(response_text, reading)
    chat_id, _private = handover.telegram_chat(session_id)
    if platform == "telegram" and chat_id and handover.env("TELEGRAM_BOT_TOKEN") and _ctx:
        _pending[session_id] = offer
        return None
    return offer


def on_turn_end(session_id="", conversation_history=None, **_):
    fallback = _pending.pop(session_id, None)
    if fallback is None:
        return
    # Off the turn: writing the dossier takes a model call, and the reply must not wait for it.
    threading.Thread(
        target=handover.card,
        args=(_ctx, session_id, list(conversation_history or []), fallback),
        name="senzu-handover",
        daemon=True,
    ).start()


def register(ctx):
    global _ctx
    _ctx = ctx
    handover.sweep()
    ctx.register_hook("pre_tool_call", on_tool_call)
    ctx.register_hook("post_tool_call", on_tool_result)
    ctx.register_hook("transform_llm_output", on_reply)
    ctx.register_hook("post_llm_call", on_turn_end)
    ctx.register_cli_command(
        name="senzu",
        help="Connect to the Senzu desk and check the installation",
        setup_fn=cli.setup_parser,
        handler_fn=cli.handle,
    )
