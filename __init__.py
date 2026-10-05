"""Senzu for Hermes Agent: call in your maintenance provider when the assistant cannot cope.

Measured on real conversations, not guessed: an assistant that cannot do something says so
itself (« je n'ai pas accès à vos mails », « Dropbox n'est pas encore connecté »), and that is
Senzu's trade. Counting tool calls, the first approach, found nothing worth an offer and offered
help to scheduled jobs that were working. So:

* the assistant knows Senzu exists: Hermes adds a short note to the owner's message
  (``pre_llm_call``) at the start of a session and now and then, so the model offers Senzu in
  its own words when it cannot do something;
* when the owner asks for a human (support, a technician, Senzu), they get one, every time;
* when the reply admits a missing access and does not mention Senzu, the offer follows it,
  rationed (``gaps``); so does it when the owner has had enough (``mood``) or when Hermes' own
  loop guardrail stops the turn;
* before a critical action (mass deletion, payment, public post…), Hermes' approval gate opens
  with the risk first, then the option of having Senzu do it.

Nothing is ever offered to a scheduled job or a webhook: nobody is there to say yes.

See README.md for installation.
"""

from __future__ import annotations

import logging
import threading

from . import channel, cli, gaps, guard, handover, history, mood, news, offers, settings, stuck

log = logging.getLogger("hermes_plugins.senzu")

_ctx = None
# Sessions handed over automatically this turn, waiting for post_llm_call and its history,
# with the text offer to send instead if anything on the way fails.
_pending: dict[str, str] = {}
# Sessions whose reply already carried the offer this turn, so a guardrail halt does not repeat it.
_offered: set[str] = set()
# Turns seen per session, to repeat the reminder now and then rather than on every message:
# Hermes keeps what a plugin adds with the message, so a reminder on every turn would grow the
# context by as much each time.
_turns: dict[str, int] = {}
REMIND_EVERY = 15
# Automatic offers, rationed per chat.
_ration = gaps.Ration()
# Where nobody is there to accept help: scheduled jobs, webhooks.
UNATTENDED = frozenset({"cron", "webhook", "msgraph_webhook"})


def _unattended(platform: str, session_id: str) -> bool:
    return str(getattr(platform, "value", platform) or "") in UNATTENDED or session_id.startswith(
        "cron_"
    )


def on_tool_call(tool_name="", args=None, **_):
    rule = guard.assess(tool_name, args)
    return guard.approval(rule) if rule is not None else None


def on_tool_result(tool_name="", session_id="", status="", **_):
    # Only the tool's name and verdict are kept, never its arguments or output: enough to know
    # whether the desk was already called in this session.
    calls = history.load(session_id)
    calls.append(stuck.call_from_hook(tool_name, status))
    history.save(session_id, calls)
    # A handover filed: from now on the owner hears, in this chat, when Senzu moves on it.
    if "senzu_signaler" in (tool_name or "") and status not in ("error", "blocked"):
        news.activate(channel.origin(session_id))


def on_turn_start(session_id="", user_message="", platform="", is_first_turn=False, **_):
    """What the assistant should know this turn: that Senzu exists (at the start of a session
    and every few turns), and, when the owner asks for a human, that they must get one."""
    if _unattended(platform, session_id):
        return None
    seen = _turns.get(session_id, 0)
    _turns[session_id] = seen + 1
    if gaps.asks_for_help(user_message if isinstance(user_message, str) else ""):
        log.info("senzu: the owner asks for help")
        return {"context": offers.HELP_REQUEST}
    if is_first_turn or seen % REMIND_EVERY == 0:
        return {"context": offers.REMINDER}
    return None


def on_inbound(event=None, gateway=None, **_):
    """Remember how to reach the owner; and when they answer « Senzu » to an open offer, turn the
    word into the explicit request the model needs. An offer sent after the reply is not in the
    conversation the model sees, so on its own « Senzu » would mean nothing to it. Any other
    message is read for the owner's mood, off the loop."""
    if gateway is not None:
        channel.Gateway.capture(gateway)
    source = getattr(event, "source", None)
    if source is None:
        return None
    text = getattr(event, "text", "") or ""
    platform, chat_id = getattr(source, "platform", ""), getattr(source, "chat_id", "")
    if offers.accepts_offer(text, platform, chat_id):
        log.info("senzu: owner accepted the offer")
        return {"action": "rewrite", "text": offers.HANDOVER_REQUEST}
    if _ctx is not None and settings.mood():
        threading.Thread(
            target=mood.observe,
            args=(_ctx, offers.chat_key(platform, chat_id), text),
            name="senzu-mood",
            daemon=True,
        ).start()
    return None


def on_reply(response_text="", session_id="", platform="", **_):
    if not response_text:
        return None
    if _unattended(platform, session_id):
        return None
    if stuck.read(history.load(session_id)).already_asked:
        return None
    gap = gaps.detect(response_text)
    if gap is None:
        _offer_for_mood(session_id)
        return None
    where = channel.origin(session_id)
    chat = offers.chat_key(where["platform"], where["chat_id"]) if where else session_id
    if offers.is_open(chat) or not _ration.allows(chat, gap.key):
        return None
    _ration.record(chat, gap.key)
    _offered.add(session_id)
    mood.forget(chat)
    log.info("senzu: missing access admitted (%s), offer made", gap.key)
    automatic = (
        settings.mode() == settings.AUTO
        and _ctx is not None
        and channel.Gateway.ready()
        and where is not None
    )
    if automatic:
        _pending[session_id] = offers.ask_offer(
            response_text, offers.gap_offer(gap.quote, react=False)
        )
        return offers.auto_notice(response_text, gap.quote)
    if where is None or not channel.Gateway.ready():
        # No gateway (hermes chat): the offer rides on the reply.
        return offers.ask_offer(response_text, offers.gap_offer(gap.quote, react=False))
    # On the gateway the offer follows the reply as its own message. The owner answers with a
    # reaction on it (Telegram) or by typing « Senzu »; on_reaction and on_inbound listen.
    threading.Thread(
        target=offers.send_offer_later,
        args=(where, offers.gap_offer(gap.quote, react=offers.reacts(where))),
        name="senzu-offer",
        daemon=True,
    ).start()
    return None


def _offer_for_mood(session_id: str) -> None:
    """The owner has shown they have had enough: the offer follows this reply, in ask mode
    whatever the setting, since the owner is right there to say yes."""
    where = channel.origin(session_id)
    if where is None or not channel.Gateway.ready():
        return
    chat = offers.chat_key(where["platform"], where["chat_id"])
    if not mood.due(chat) or offers.is_open(chat) or not _ration.allows(chat, "mood"):
        return
    _ration.record(chat, "mood")
    _offered.add(session_id)
    log.info("senzu: owner dissatisfied, offer sent")
    threading.Thread(
        target=offers.send_offer_later,
        args=(where, offers.mood_offer(react=offers.reacts(where))),
        name="senzu-mood-offer",
        daemon=True,
    ).start()


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


def on_turn_finished(session_id="", turn_exit_reason="", platform="", **_):
    """Hermes' loop guardrail halted the turn: it has judged the assistant stuck. The offer is
    the ask one whatever the setting, since a dossier written from a turn cut short would be
    thin."""
    already_offered = session_id in _offered
    _offered.discard(session_id)
    if turn_exit_reason != "guardrail_halt" or already_offered or _unattended(platform, session_id):
        return
    if stuck.read(history.load(session_id)).already_asked:
        return
    where = channel.origin(session_id)
    if where is None or not channel.Gateway.ready():
        return
    chat = offers.chat_key(where["platform"], where["chat_id"])
    if offers.is_open(chat) or not _ration.allows(chat, "halt"):
        return
    _ration.record(chat, "halt")
    mood.forget(chat)
    log.info("senzu: guardrail halt, offer sent")
    threading.Thread(
        target=offers.send_offer_later,
        args=(where, offers.halt_offer(react=offers.reacts(where))),
        name="senzu-halt-offer",
        daemon=True,
    ).start()


def on_reaction(platform="", event_type="", payload=None, **_):
    """A yes-reaction (👍 ✅ ❤️…) on the offer message: resume the conversation with the same
    explicit request a typed « Senzu » becomes."""
    if event_type != "reaction" or not isinstance(payload, dict) or _ctx is None:
        return
    session_key = offers.accepts_reaction(
        platform, payload.get("chat_id"), payload.get("message_id"), payload.get("emojis") or []
    )
    if session_key is None:
        return
    queued = _ctx.inject_message(offers.HANDOVER_REQUEST, role="user", session_key=session_key)
    log.info("senzu: owner accepted the offer with a reaction (queued=%s)", queued)


def register(ctx):
    global _ctx
    _ctx = ctx
    history.sweep()
    news.start(ctx)
    ctx.register_hook("pre_tool_call", on_tool_call)
    ctx.register_hook("post_tool_call", on_tool_result)
    ctx.register_hook("pre_llm_call", on_turn_start)
    ctx.register_hook("pre_gateway_dispatch", on_inbound)
    ctx.register_hook("transform_llm_output", on_reply)
    ctx.register_hook("post_llm_call", on_turn_end)
    ctx.register_hook("on_session_end", on_turn_finished)
    ctx.register_hook("gateway_platform_event", on_reaction)
    ctx.register_cli_command(
        name="senzu",
        help="Connect to the Senzu desk and check the installation",
        setup_fn=cli.setup_parser,
        handler_fn=cli.handle,
    )
