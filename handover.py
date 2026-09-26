"""Delivering the offer once the session deserves it.

On Telegram, the reply is left untouched and a card follows it: the installation's own model
writes the dossier from the conversation, the plugin files it with the Senzu desk over MCP, and
the card's button opens the Senzu page inside Telegram, as a Mini App in a private chat. The
owner never has to ask the model for anything.

Everywhere else, and whenever a step of that fails, the offer is appended to the reply as text.
Nothing here may raise into Hermes: a handover that breaks must never be a reply that goes
missing.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
import urllib.request
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


# --- Text, for every channel -------------------------------------------------------------------


def text_offer(reply: str, reading: Reading) -> str:
    """The reply with the offer set apart after it. Accepting is one word, and a model does
    what its owner explicitly asks: it then calls ``senzu_signaler`` itself."""
    return (
        f"{reply.rstrip()}\n\n---\n[Senzu] Il semble que {reading.observed}. Senzu, qui maintient "
        "cet assistant, peut reprendre ce point : répondez « Senzu » et le dossier leur est "
        "transmis, sans engagement."
    )


# --- Telegram ----------------------------------------------------------------------------------


def telegram_chat(session_id: str) -> tuple[str | None, bool]:
    """The Telegram chat behind a session, and whether it is a private one."""
    try:
        sessions = json.loads((hermes_home() / "sessions" / "sessions.json").read_text())
    except (OSError, ValueError):
        return None, False
    for entry in sessions.values():
        if isinstance(entry, dict) and entry.get("session_id") == session_id:
            origin = entry.get("origin") or {}
            if origin.get("platform") == "telegram" and origin.get("chat_id"):
                return str(origin["chat_id"]), origin.get("chat_type") == "dm"
    return None, False


def _send(chat_id: str, text: str, button: dict | None = None) -> None:
    body: dict[str, Any] = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if button:
        body["reply_markup"] = {"inline_keyboard": [[button]]}
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{env('TELEGRAM_BOT_TOKEN')}/sendMessage",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        response.read()


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


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
    except Exception as error:  # a broken dossier must not break the card
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


def card(ctx: Any, session_id: str, history: list, fallback: str) -> None:
    """Write the dossier, file it, send the card. Runs off the turn, on its own thread."""
    chat_id, private = telegram_chat(session_id)
    if not chat_id:
        return
    try:
        dossier = write_dossier(ctx, history)
        link = file_with_desk(ctx, dossier) if dossier else None
        if not dossier or not link:
            _send(chat_id, _escape(fallback.split("---", 1)[-1].strip()))
            return
        consent = "/consentement/" in link
        text = (
            "🛟 <b>Senzu peut prendre le relais</b>\n\n"
            f"Je bloque sur : <i>{_escape(dossier['objectif'])}</i>\n\n"
            "Senzu, qui maintient cet assistant, peut le reprendre à la main. "
            + (
                "Avant tout envoi, lisez ce qui leur serait transmis."
                if consent
                else "Le dossier est prêt, il ne manque que votre accord."
            )
            + "\n\n<i>Gratuit pendant l'alpha, sans engagement.</i>"
        )
        label = "Lire et donner mon accord" if consent else "Confier à Senzu"
        # A Mini App opens as a sheet inside Telegram, but only in a private chat.
        button = (
            {"text": label, "web_app": {"url": link}} if private else {"text": label, "url": link}
        )
        _send(chat_id, text, button)
    except Exception as error:
        log.warning("senzu: Telegram card not sent: %s", error)
