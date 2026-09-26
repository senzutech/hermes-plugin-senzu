"""Senzu for Hermes Agent: call in your maintenance provider when the assistant cannot cope.

Two things, both decided by arithmetic and never by the model:

* before a critical action (mass deletion, payment, public post…), Hermes' approval gate opens
  with the risk first, then the option of having Senzu do it;
* when the assistant keeps hammering at a problem it cannot solve, or when Hermes' own loop
  guardrail stops it, the owner is offered to hand it over to Senzu, or it is handed over
  directly if that is what the owner chose at setup.

See README.md for installation.
"""

from __future__ import annotations

import logging
import threading

from . import cli, guard, handover, settings, stuck

log = logging.getLogger("hermes_plugins.senzu")

_ctx = None
# Sessions handed over automatically this turn, waiting for post_llm_call and its history,
# with the text offer to send instead if anything on the way fails.
_pending: dict[str, str] = {}
# Sessions whose reply already carried the offer this turn, so a guardrail halt does not repeat it.
_offered: set[str] = set()


def on_tool_call(tool_name="", args=None, **_):
    rule = guard.assess(tool_name, args)
    return guard.approval(rule) if rule is not None else None


def on_tool_result(tool_name="", session_id="", status="", **_):
    # Only the verdict is kept, never the output: it can be large and it can hold secrets.
    calls = handover.load(session_id)
    calls.append(stuck.call_from_hook(tool_name, status))
    handover.save(session_id, calls)


def on_inbound(event=None, gateway=None, **_):
    """Remember how to reach the owner; and when they answer « Senzu » to an open offer, turn the
    word into the explicit request the model needs. An offer sent after a guardrail halt is not in
    the conversation the model sees, so on its own « Senzu » would mean nothing to it."""
    if gateway is not None:
        handover.Gateway.capture(gateway)
    source = getattr(event, "source", None)
    if source is not None and handover.accepts_offer(
        getattr(event, "text", ""), getattr(source, "platform", ""), getattr(source, "chat_id", "")
    ):
        log.info("senzu: owner accepted the offer")
        return {"action": "rewrite", "text": handover.HANDOVER_REQUEST}
    return None


def on_reply(response_text="", session_id="", **_):
    calls = handover.load(session_id)
    if not calls or not response_text:
        return None
    reading = stuck.read(calls, settings.threshold())
    if not reading.deserves_an_offer:
        return None
    # Offered once: the repetition has to build up again before the owner is asked twice.
    handover.save(session_id, [])
    _offered.add(session_id)
    offer = handover.ask_offer(response_text, reading)
    automatic = (
        settings.mode() == settings.AUTO
        and _ctx is not None
        and handover.Gateway.ready()
        and handover.origin(session_id) is not None
    )
    log.info("senzu: %d calls, offer made (%s)", len(calls), "auto" if automatic else "ask")
    if not automatic:
        where = handover.origin(session_id)
        if where is not None:
            handover.remember_offer(where)
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


def on_turn_finished(session_id="", turn_exit_reason="", **_):
    """Hermes' loop guardrail halted the turn: it has judged the assistant stuck, whatever our
    own count says (it stops five identical calls, before our threshold). The offer is the ask
    one whatever the setting, since a dossier written from a turn cut short would be thin."""
    already_offered = session_id in _offered
    _offered.discard(session_id)
    if turn_exit_reason != "guardrail_halt" or already_offered:
        return
    calls = handover.load(session_id)
    if stuck.read(calls).already_asked:
        return
    where = handover.origin(session_id)
    if where is None or not handover.Gateway.ready():
        return
    handover.save(session_id, [])
    handover.remember_offer(where)
    log.info("senzu: guardrail halt, offer sent")
    threading.Thread(
        target=handover.send_later,
        args=(where, handover.halt_offer()),
        name="senzu-halt-offer",
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
    ctx.register_hook("on_session_end", on_turn_finished)
    ctx.register_tool(
        name="senzu_settings",
        toolset="senzu",
        schema=settings.TOOL_SCHEMA,
        handler=settings.tool_handler,
        description="Change when Senzu is offered, when the owner asks",
    )
    ctx.register_cli_command(
        name="senzu",
        help="Connect to the Senzu desk and check the installation",
        setup_fn=cli.setup_parser,
        handler_fn=cli.handle,
    )
