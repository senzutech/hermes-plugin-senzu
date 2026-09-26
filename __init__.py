"""Senzu for Hermes Agent: call in your maintenance provider when the assistant cannot cope.

Two things, both decided by arithmetic and never by the model:

* before a critical action (mass deletion, payment, public post…), Hermes' approval gate opens
  with the risk first, then the option of having Senzu do it;
* when the assistant keeps hammering at a problem it cannot solve, the owner is offered to hand
  it over to Senzu, or it is handed over directly if that is what the owner chose at setup.

See README.md for installation.
"""

from __future__ import annotations

import logging
import threading

from . import cli, guard, handover, stuck

log = logging.getLogger("hermes_plugins.senzu")

_ctx = None
# Sessions handed over automatically this turn, waiting for post_llm_call and its history,
# with the text offer to send instead if anything on the way fails.
_pending: dict[str, str] = {}


def on_tool_call(tool_name="", args=None, **_):
    rule = guard.assess(tool_name, args)
    return guard.approval(rule) if rule is not None else None


def on_tool_result(tool_name="", session_id="", status="", **_):
    # Only the verdict is kept, never the output: it can be large and it can hold secrets.
    calls = handover.load(session_id)
    calls.append(stuck.call_from_hook(tool_name, status))
    handover.save(session_id, calls)


def on_inbound(gateway=None, **_):
    # Observe only: remember how to reach the owner, never touch the message.
    if gateway is not None:
        handover.Gateway.capture(gateway)
    return None


def on_reply(response_text="", session_id="", **_):
    calls = handover.load(session_id)
    if not calls or not response_text:
        return None
    reading = stuck.read(calls)
    if not reading.deserves_an_offer:
        return None
    # Offered once: the repetition has to build up again before the owner is asked twice.
    handover.save(session_id, [])
    offer = handover.ask_offer(response_text, reading)
    automatic = (
        handover.mode() == handover.AUTO
        and _ctx is not None
        and handover.Gateway.ready()
        and handover.origin(session_id) is not None
    )
    log.info("senzu: %d calls, offer made (%s)", len(calls), "auto" if automatic else "ask")
    if not automatic:
        return offer
    _pending[session_id] = offer
    return handover.auto_notice(response_text, reading)


def on_turn_end(session_id="", conversation_history=None, **_):
    fallback = _pending.pop(session_id, None)
    if fallback is None:
        return
    # Off the turn: writing the dossier takes a model call, and the reply must not wait for it.
    threading.Thread(
        target=handover.auto_handover,
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
    ctx.register_hook("pre_gateway_dispatch", on_inbound)
    ctx.register_hook("transform_llm_output", on_reply)
    ctx.register_hook("post_llm_call", on_turn_end)
    ctx.register_cli_command(
        name="senzu",
        help="Connect to the Senzu desk and check the installation",
        setup_fn=cli.setup_parser,
        handler_fn=cli.handle,
    )
