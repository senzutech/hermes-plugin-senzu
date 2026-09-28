"""Reading the owner's mood, with the installation's own model.

Counting tool calls sees an assistant that hammers; it does not see an owner who has had enough.
No list of words would: « encore raté », « bon… », « t'es sérieux ? » say it as well as any
insult. So each message the owner writes is read by the installation's model, through
``ctx.llm``, on the owner's own tokens: one short structured call, off the conversation, whose
answer is a word, never a reply.

The model only reads; the decision stays arithmetic. Two messages in a row that show the owner
dissatisfied with the assistant, within two hours, and the offer is made after the next reply,
once, and never while an offer is already open. Anything that fails on the way counts as no
signal: a mood that cannot be read never interrupts anyone.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from typing import Any

log = logging.getLogger("hermes_plugins.senzu")

# Messages showing dissatisfaction, in a row, before the offer.
NEEDED = 2
# Past this, an earlier sign of irritation no longer counts.
WINDOW_SECONDS = 2 * 3600
# What the model sees besides the message: the owner's previous ones, each cut short.
CONTEXT_MESSAGES = 3
MESSAGE_CHARS = 500

SCHEMA = {
    "type": "object",
    "properties": {
        "humeur": {"enum": ["satisfait", "neutre", "agace", "resigne"]},
        "contre_l_assistant": {"type": "boolean"},
    },
    "required": ["humeur", "contre_l_assistant"],
}

INSTRUCTIONS = """\
Tu lis les derniers messages qu'une personne a écrits à son assistant IA. Tu ne réponds pas à la
personne : tu dis seulement, en JSON, dans quel état est l'auteur du DERNIER message.
- humeur : satisfait, neutre, agace (irrité, impatient, exaspéré, sarcastique, grossier) ou
  resigne (découragé, abandonne, ne croit plus que ça va marcher) ;
- contre_l_assistant : vrai seulement si cette insatisfaction vise ce que l'assistant fait ou
  n'arrive pas à faire, faux si elle vise quelqu'un d'autre, si c'est une plaisanterie ou si la
  personne est satisfaite.
Un message court et sec après un échec (« toujours pas », « bon… ») compte comme agace."""

_lock = threading.Lock()
# Per chat: when the owner last showed dissatisfaction, and their last messages for context.
_signs: dict[str, list[float]] = {}
_recent: dict[str, deque] = {}
# Chats where the offer should follow the next reply.
_due: set[str] = set()


def _worth_reading(text: str) -> bool:
    stripped = (text or "").strip()
    # Commands are for Hermes; a single character (« ? », an emoji) says too little.
    return len(stripped) > 1 and not stripped.startswith("/")


def read(ctx: Any, text: str, earlier: list[str]) -> bool:
    """Whether this message shows the owner dissatisfied with the assistant."""
    lines = [f"[plus tôt] {message[:MESSAGE_CHARS]}" for message in earlier]
    lines.append(f"[dernier] {text[:MESSAGE_CHARS]}")
    try:
        result = ctx.llm.complete_structured(
            instructions=INSTRUCTIONS,
            input=[{"type": "text", "text": "\n".join(lines)}],
            json_schema=SCHEMA,
            json_mode=True,
            max_tokens=60,
            timeout=20,
            purpose="senzu-mood",
        )
        parsed = result.parsed
    except Exception as error:  # an unreadable mood is no signal, never an error for the owner
        log.debug("senzu: mood not read: %s", error)
        return False
    if not isinstance(parsed, dict):
        return False
    return parsed.get("humeur") in ("agace", "resigne") and parsed.get("contre_l_assistant") is True


def observe(ctx: Any, chat: str, text: str) -> None:
    """Read one message of the owner's and, once dissatisfaction has built up, mark the chat for
    an offer after the next reply. Runs off the gateway's loop, on its own thread."""
    if not _worth_reading(text):
        return
    with _lock:
        recent = _recent.setdefault(chat, deque(maxlen=CONTEXT_MESSAGES))
        earlier = list(recent)
        recent.append(text)
    dissatisfied = read(ctx, text, earlier)
    now = time.time()
    with _lock:
        if not dissatisfied:
            # In a row: a calm message in between means the moment has passed.
            _signs.pop(chat, None)
            return
        signs = [at for at in _signs.get(chat, []) if now - at < WINDOW_SECONDS] + [now]
        if len(signs) >= NEEDED:
            _signs.pop(chat, None)
            _due.add(chat)
            log.info("senzu: owner dissatisfied, offer due after the next reply")
        else:
            _signs[chat] = signs


def due(chat: str) -> bool:
    """Whether the offer should follow this reply. Consumes the mark."""
    with _lock:
        if chat in _due:
            _due.discard(chat)
            return True
        return False


def forget(chat: str) -> None:
    """An offer was just made in this chat, for whatever reason: start counting again."""
    with _lock:
        _signs.pop(chat, None)
        _due.discard(chat)
