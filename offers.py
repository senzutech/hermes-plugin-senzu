"""The offer: what the owner reads, and their answer, a « Senzu » or a reaction on the offer."""

from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import Any

from . import channel, home
from .stuck import Reading

log = logging.getLogger("hermes_plugins.senzu")


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


# How long an offer stays open for a one-word « Senzu ».
OFFER_VALIDITY = 24 * 3600
ACCEPTANCES = {"senzu", "ouisenzu", "oksenzu", "gosenzu", "vasysenzu"}
HANDOVER_REQUEST = (
    "Oui, je veux que Senzu prenne le relais. Appelle l'outil senzu_signaler (serveur MCP senzu) "
    "avec un résumé de ce sur quoi tu bloques : l'objectif, le blocage, ce qui a déjà été essayé "
    "et les services concernés. Puis transmets-moi le lien qu'il renvoie."
)


def _offers_file() -> Path:
    return home.cache_dir() / "offers.json"


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
        home.cache_dir().mkdir(parents=True, exist_ok=True)
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


def send_offer_later(where: dict, text: str, delay: float = 3.0) -> None:
    """Send the offer after Hermes' own message has gone out, so it reads as the follow-up, and
    remember which message it is, for the owner's reaction."""
    time.sleep(delay)
    try:
        remember_offer(where, channel.send(where, text))
    except Exception as error:
        log.warning("senzu: offer not delivered: %s", error)
