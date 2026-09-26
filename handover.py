"""Delivering the offer once the session deserves it.

Two modes, chosen by the owner at setup (``hermes senzu setup --handover ask|auto``):

* ``ask`` (default): the offer is appended to the reply, and nothing leaves the machine until
  the owner answers « Senzu ». The model then files the handover itself, which it does reliably
  when its owner asks for it explicitly.
* ``auto``: the owner has decided once that their maintenance provider may step in whenever the
  assistant is stuck. The plugin has the installation's own model write the dossier, files it
  with the Senzu desk over MCP, and sends the owner the link to approve the work.

Everything goes through Hermes' gateway, so it reaches the owner on whatever channel they use.
Nothing here may raise into Hermes: a handover that breaks must never be a reply that goes
missing.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any

from .stuck import HAMMER_WINDOW, Call, Reading, calls_from_json

log = logging.getLogger("hermes_plugins.senzu")

# The MCP server name, as `hermes senzu setup` declares it.
DESK = "senzu"
# Recorded histories untouched for this long belong to sessions nobody will come back to.
STALE_SECONDS = 7 * 24 * 3600
# What the model reads to write the dossier: the last messages, each cut short.
TRANSCRIPT_MESSAGES = 30
TRANSCRIPT_CHARS = 600
LINK = re.compile(r"https://\S+?/(?:consentement|accepter|payer)/[\w-]+")

DOSSIER_SCHEMA = {
    "type": "object",
    "properties": {
        "objectif": {"type": "string"},
        "blocage": {"type": "string"},
        "tentatives": {"type": "array", "items": {"type": "string"}},
        "systemes": {"type": "array", "items": {"type": "string"}},
        "urgence": {"enum": ["bloquant", "genant", "confort"]},
        "climat": {"enum": ["agace", "neutre", "resigne"]},
    },
    "required": ["objectif", "blocage", "tentatives", "urgence", "climat"],
}

DOSSIER_INSTRUCTIONS = """\
Tu rédiges un signalement pour Senzu, le prestataire qui maintient cet assistant. La conversation
ci-dessous montre l'assistant bloqué sur une demande de son utilisateur. Réponds en JSON, en
français, sans rien d'autre :
- objectif : ce que l'utilisateur veut obtenir, dans ses mots, une phrase (300 caractères max) ;
- blocage : ce qui coince et ce que l'assistant n'arrive pas à faire, franchement (350 max) ;
- tentatives : ce qui a déjà été essayé, une ligne courte chacune, 5 au plus ;
- systemes : les services concernés (ClickUp, WhatsApp, Odoo…) ;
- urgence : bloquant, genant ou confort ; climat : agace, neutre ou resigne.
Jamais de mot de passe, de clé, de jeton, d'URL d'autorisation ni d'identifiant client."""


# --- Where things live -------------------------------------------------------------------------


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


# --- The recorded calls, on disk so a gateway restart does not wipe a series in progress -------


def _store() -> Path:
    return hermes_home() / "cache" / "senzu"


def _file(session_id: str) -> Path:
    safe = "".join(c for c in session_id if c.isalnum() or c in "-_") or "anonymous"
    return _store() / f"{safe}.json"


def load(session_id: str) -> list[Call]:
    try:
        rows = json.loads(_file(session_id).read_text())
    except (OSError, ValueError):
        return []
    return calls_from_json(rows) if isinstance(rows, list) else []


def save(session_id: str, calls: list[Call]) -> None:
    path = _file(session_id)
    rows = [{"tool": call.tool, "failed": call.failed} for call in calls[-HAMMER_WINDOW:]]
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(rows))
        temporary.replace(path)
    except OSError as error:
        log.warning("senzu: history not written: %s", error)


def sweep() -> None:
    cutoff = time.time() - STALE_SECONDS
    try:
        for path in _store().glob("*.json"):
            if path.stat().st_mtime < cutoff:
                path.unlink(missing_ok=True)
    except OSError:
        pass


# --- What the owner reads ----------------------------------------------------------------------


# Reactions that mean yes, on the offer message itself. Telegram reports them to plugins through
# Hermes' gateway_platform_event hook; nothing to tap, nothing Hermes would have to forward.
YES_REACTIONS = {"👍", "✅", "❤", "❤️", "👌", "🙏", "💯", "🔥", "🤝"}


def reacts(where: dict) -> bool:
    """Telegram reports reactions to plugins; elsewhere the owner types the word."""
    return where.get("platform") == "telegram"


def _how(react: bool) -> str:
    return "réagissez 👍 à ce message (ou répondez « Senzu »)" if react else "répondez « Senzu »"


def offer_message(reading: Reading, *, react: bool) -> str:
    """The offer on its own, sent after the reply."""
    return (
        f"🛟 Je n'avance plus : {reading.observed}. Vos experts Senzu peuvent prendre le relais : "
        f"{_how(react)} et je leur prépare le dossier. Rien ne leur est envoyé sans votre accord."
    )


def ask_offer(reply: str, reading: Reading) -> str:
    """The reply, then the offer, for when there is no gateway to send a separate message."""
    return f"{reply.rstrip()}\n\n---\n{offer_message(reading, react=False)}"


def auto_notice(reply: str, reading: Reading) -> str:
    """The reply, then what is about to happen, as the owner agreed at setup."""
    return (
        f"{reply.rstrip()}\n\n---\n[Senzu] Je n'avance plus : {reading.observed}. Comme "
        "convenu, je transmets le dossier à vos experts Senzu ; le lien pour valider leur "
        "intervention arrive dans un instant."
    )


def halt_offer(*, react: bool) -> str:
    """Hermes itself stopped the turn for looping: the plainest proof the assistant is stuck."""
    return (
        "🛟 Hermes vient d'arrêter cette tâche : l'assistant tournait en rond. Vos experts Senzu "
        f"peuvent prendre le relais : {_how(react)} et je leur prépare le dossier. Rien ne leur "
        "est envoyé sans votre accord."
    )


def link_message(dossier: dict, link: str) -> str:
    if "/consentement/" in link:
        return (
            "[Senzu] Avant le premier envoi à vos experts Senzu, lisez ce qui leur sera "
            f"transmis et donnez votre accord : {link}"
        )
    return (
        f"[Senzu] Dossier transmis à vos experts Senzu : « {dossier['objectif']} ». "
        f"Pour valider leur intervention, sans engagement avant ce clic : {link}"
    )


# --- The gateway -------------------------------------------------------------------------------


class Gateway:
    """The running gateway and its event loop, captured on the first inbound message.

    ``pre_gateway_dispatch`` is the documented way for a plugin to reach
    ``gateway.adapters[platform].send``; outside the gateway (``hermes chat``) there is none,
    and the offer stays in the reply.
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
    def ready(cls) -> bool:
        return cls.runner is not None and cls.loop is not None


def origin(session_id: str) -> dict | None:
    """Where a session's owner is reached: platform, chat and thread, from Hermes' session map."""
    try:
        sessions = json.loads((hermes_home() / "sessions" / "sessions.json").read_text())
    except (OSError, ValueError):
        return None
    for key, entry in sessions.items():
        if isinstance(entry, dict) and entry.get("session_id") == session_id:
            found = dict(entry.get("origin") or {})
            if found.get("platform") and found.get("chat_id"):
                found["session_key"] = entry.get("session_key") or key
                return found
    return None


# --- The owner's « Senzu » ---------------------------------------------------------------------

# How long an offer stays open for a one-word « Senzu ».
OFFER_VALIDITY = 24 * 3600
ACCEPTANCES = {"senzu", "ouisenzu", "oksenzu", "gosenzu", "vasysenzu"}
HANDOVER_REQUEST = (
    "Oui, je veux que Senzu prenne le relais. Appelle l'outil senzu_signaler (serveur MCP senzu) "
    "avec un résumé de ce sur quoi tu bloques : l'objectif, le blocage, ce qui a déjà été essayé "
    "et les services concernés. Puis transmets-moi le lien qu'il renvoie."
)


def _offers_file() -> Path:
    return _store() / "offers.json"


def _chat_key(platform: Any, chat_id: Any) -> str:
    return f"{getattr(platform, 'value', platform)}:{chat_id}"


def _load_offers() -> dict:
    try:
        offers = json.loads(_offers_file().read_text())
    except (OSError, ValueError):
        return {}
    now = time.time()
    return {
        key: offer
        for key, offer in offers.items()
        if isinstance(offer, dict) and now - offer.get("at", 0) < OFFER_VALIDITY
    }


def _save_offers(offers: dict) -> None:
    try:
        _store().mkdir(parents=True, exist_ok=True)
        _offers_file().write_text(json.dumps(offers))
    except OSError as error:
        log.warning("senzu: offer not remembered: %s", error)


def remember_offer(where: dict, message_id: Any = None) -> None:
    """Note that this chat was just offered Senzu, and on which message, so that a one-word
    answer or a reaction on that message can be understood."""
    offers = _load_offers()
    offers[_chat_key(where["platform"], where["chat_id"])] = {
        "at": time.time(),
        "message_id": None if message_id is None else str(message_id),
        "session_key": where.get("session_key"),
    }
    _save_offers(offers)


def accepts_offer(text: str, platform: Any, chat_id: Any) -> bool:
    """Whether this inbound message is the owner's « Senzu » to an open offer. Consumes it."""
    if re.sub(r"[\W_]", "", (text or "").lower()) not in ACCEPTANCES:
        return False
    offers = _load_offers()
    if offers.pop(_chat_key(platform, chat_id), None) is None:
        return False
    _save_offers(offers)
    return True


def accepts_reaction(platform: Any, chat_id: Any, message_id: Any, emojis: list) -> str | None:
    """The session to resume when a yes-reaction lands on the open offer message. Consumes it."""
    if not YES_REACTIONS.intersection(emojis or []):
        return None
    offers = _load_offers()
    key = _chat_key(platform, chat_id)
    offer = offers.get(key)
    if offer is None or offer.get("message_id") not in (None, str(message_id)):
        return None
    offers.pop(key)
    _save_offers(offers)
    return offer.get("session_key")


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


# --- The dossier -------------------------------------------------------------------------------


def _transcript(history: list) -> str:
    lines = []
    labels = {"user": "utilisateur", "assistant": "assistant"}
    for message in history[-TRANSCRIPT_MESSAGES:]:
        role, content = message.get("role"), message.get("content")
        if role not in ("user", "assistant", "tool") or not isinstance(content, str) or not content:
            continue
        name = message.get("tool_name") or message.get("name") or ""
        label = f"outil {name}" if role == "tool" else labels[role]
        lines.append(f"[{label}] {content[:TRANSCRIPT_CHARS]}")
    return "\n".join(lines)


def write_dossier(ctx: Any, history: list) -> dict | None:
    try:
        result = ctx.llm.complete_structured(
            instructions=DOSSIER_INSTRUCTIONS,
            input=[{"type": "text", "text": _transcript(history)}],
            json_schema=DOSSIER_SCHEMA,
            json_mode=True,
            max_tokens=900,
            timeout=90,
            purpose="senzu-dossier",
        )
        parsed = result.parsed
        if parsed is None:  # providers without structured output answer in plain text
            text = result.text or ""
            parsed = json.loads(text[text.find("{") : text.rfind("}") + 1])
    except Exception as error:  # a broken dossier must not break the handover
        log.warning("senzu: dossier not written: %s", error)
        return None
    if not isinstance(parsed, dict) or not parsed.get("objectif") or not parsed.get("blocage"):
        return None
    parsed["objectif"] = str(parsed["objectif"])[:300]
    parsed["blocage"] = str(parsed["blocage"])[:400]
    parsed["tentatives"] = [str(t)[:200] for t in (parsed.get("tentatives") or [])][:5]
    parsed["systemes"] = [str(s)[:60] for s in (parsed.get("systemes") or [])][:8]
    return parsed


def file_with_desk(ctx: Any, dossier: dict) -> str | None:
    """The link the owner should open: the consent notice the first time, the acceptance after.

    Both come back from ``senzu_signaler`` and carry a secret token. ``senzu_accepter`` is never
    called here: it marks the work accepted, and only the owner's click may do that.
    """
    try:
        answer = ctx.call_mcp(DESK, "senzu_signaler", dossier, timeout=30)
    except Exception as error:
        log.warning("senzu: dossier not filed: %s", error)
        return None
    found = LINK.search(json.dumps(answer, ensure_ascii=False))
    if not found:
        log.warning("senzu: desk answered without a link: %s", str(answer)[:300])
    return found.group(0) if found else None


def send_offer_later(where: dict, text: str, delay: float = 3.0) -> None:
    """Send the offer after Hermes' own message has gone out, so it reads as the follow-up, and
    remember which message it is, for the owner's reaction."""
    time.sleep(delay)
    try:
        remember_offer(where, send(where, text))
    except Exception as error:
        log.warning("senzu: offer not delivered: %s", error)


def auto_handover(ctx: Any, session_id: str, history: list, fallback: str) -> None:
    """Write the dossier, file it, send the link. Runs off the turn, on its own thread."""
    where = origin(session_id)
    if where is None:
        return
    try:
        dossier = write_dossier(ctx, history)
        link = file_with_desk(ctx, dossier) if dossier else None
        if link:
            from . import news

            news.activate(where)
        if dossier and link:
            send(where, link_message(dossier, link))
        else:
            # Something failed on the way: fall back to asking, which needs nothing but the model.
            send(where, fallback.split("---", 1)[-1].strip())
    except Exception as error:
        log.warning("senzu: handover not delivered: %s", error)
