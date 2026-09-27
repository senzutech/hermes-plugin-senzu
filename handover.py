"""Delivering the offer once the session deserves it.

Two modes, chosen by the owner at setup (``hermes senzu setup --handover ask|auto``):

* ``ask`` (default): the offer is appended to the reply, and nothing leaves the machine until
  the owner answers « Senzu ». The model then files the handover itself, which it does reliably
  when its owner asks for it explicitly.
* ``auto``: the owner has decided once that their maintenance provider may step in whenever the
  assistant is stuck. The plugin has the installation's own model write the dossier, files it
  with the Senzu desk over MCP, and sends the owner the link to approve the work.

Nothing here may raise into Hermes: a handover that breaks must never be a reply that goes
missing.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from . import channel, offers

log = logging.getLogger("hermes_plugins.senzu")

# The MCP server name, as `hermes senzu setup` declares it.
DESK = "senzu"
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


def auto_handover(ctx: Any, session_id: str, history: list, fallback: str) -> None:
    """Write the dossier, file it, send the link. Runs off the turn, on its own thread."""
    where = channel.origin(session_id)
    if where is None:
        return
    try:
        dossier = write_dossier(ctx, history)
        link = file_with_desk(ctx, dossier) if dossier else None
        if link:
            from . import news

            news.activate(where)
        if dossier and link:
            channel.send(where, offers.link_message(dossier, link))
        else:
            # Something failed on the way: fall back to asking, which needs nothing but the model.
            channel.send(where, fallback.split("---", 1)[-1].strip())
    except Exception as error:
        log.warning("senzu: handover not delivered: %s", error)
