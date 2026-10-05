"""What the assistant cannot do on its own, in its own words, and what the owner asks for.

Measured on real conversations (two installations, 22 sessions, 374 turns): counting tool calls
found nothing worth an offer, while the moments Senzu was needed were all said plainly by the
assistant itself. « je n'ai pas accès à vos mails, la connexion Gmail n'est pas encore faite »,
« Dropbox n'est pas encore connecté », « mon accès à Artinove est en lecture seule », « un filtre
anti-robot que mon navigateur n'arrive pas à passer ». Connecting, opening and repairing those
is Senzu's trade. So the reply is read for that admission, and only that.

The owner's side is simpler: when they ask for support, a technician, their provider, or Senzu
by name, they get it, every time.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass

# The assistant admitting a missing access, connection, right, or a service that blocks it.
_GAP = re.compile(
    r"""(
      je\ n'ai\ (toujours\ |encore\ )?(pas|aucun|plus)\ (encore\ )?(d')?accès
        \ (à|au|aux|en)\ [^.\n]{2,60}
    | [^.\n]{0,40}\ (n'est|ne\ sont)\ (toujours\ )?pas\ (encore\ )?(connecté|relié|branché)e?s?
    | (la\ )?connexion\ [\w'’-]+
        \ (n'est\ (toujours\ )?pas\ (encore\ )?faite|est\ (encore\ )?à\ faire)
    | (mon\ accès|je\ suis)\ [^.\n]{0,30}en\ \*{0,2}lecture\ seule
    | je\ n'ai\ pas\ (les\ )?(droits|l'autorisation)\ [^.\n]{0,60}
    | (filtre\ anti-?robot|cloudflare|captcha)[^.\n]{0,60}
    | (a|ont)\ bloqué\ ma\ (recherche|connexion|requête)
    | il\ me\ manque\ (un|deux|trois|des|l')\ ?accès[^.\n]{0,60}
    | les\ outils\ [\w'’]+\ ne\ se\ chargent\ pas
    )""",
    re.IGNORECASE | re.VERBOSE,
)
# Admissions that are true but that no technician can change: a phone call, a visit, a signature.
_NOT_OURS = re.compile(
    r"appel(er)?\b|téléphon|me déplacer|sur place|signer|en personne|ton mot de passe ici",
    re.IGNORECASE,
)
# The owner asking for a human: Senzu by name, support, a technician, someone to take over.
# « notre prestataire » alone is only a mention; asking them to step in is a request.
_HELP = re.compile(
    r"""\bsenzu\b
    | \b(assistance|aide|support)\ (technique|humaine|d'un\ (humain|expert|technicien|pro))\b
    | \b(un|le|ton|votre|notre)\ technicien\b
    | passe(r)?\ le\ relais
    | (appelle|contacte|préviens|demande\ à|fais\ venir)\ (un|le|mon|notre|ton|votre)
      \ (support|technicien|prestataire|informaticien|expert)""",
    re.IGNORECASE | re.VERBOSE,
)

# Automatic offers are rationed: each missing access at most once a day per chat, and no more
# than this many automatic offers a day per chat, whatever their reason. The owner's own
# requests are never rationed.
PER_GAP_SECONDS = 24 * 3600
AUTOMATIC_PER_DAY = 2


@dataclass(frozen=True)
class Gap:
    """A missing access the assistant admitted."""

    # What it said, as the owner can read it back.
    quote: str
    # What makes two admissions the same one: the words that name what is missing.
    key: str


def detect(reply: str) -> Gap | None:
    """The first missing access the reply admits, if any. A reply that already mentions Senzu
    has made the offer itself."""
    if not reply or "senzu" in reply.lower():
        return None
    for match in _GAP.finditer(reply):
        sentence = _sentence_around(reply, match.start(), match.end())
        if _NOT_OURS.search(sentence):
            continue
        return Gap(quote=sentence, key=_key(match.group(0)))
    return None


def asks_for_help(message: str) -> bool:
    """Whether the owner asks for a human: support, a technician, their provider, Senzu. Only
    their own words count, not the message they reply to."""
    return bool(message) and bool(_HELP.search(_own_words(message)))


def _own_words(message: str) -> str:
    """The message without the quote Hermes puts before a reply (« [Replying to: "…"] »)."""
    if message.startswith("[Replying to:"):
        closing = message.find('"]')
        return message[closing + 2 :] if closing != -1 else ""
    return message


def _sentence_around(text: str, start: int, end: int) -> str:
    """The sentence holding the admission, cleaned of formatting, kept short."""
    left = max(text.rfind(mark, 0, start) for mark in (".", "\n", ":", "!", "?"))
    right_candidates = [i for i in (text.find(m, end) for m in (".", "\n", "!", "?")) if i != -1]
    right = min(right_candidates) if right_candidates else len(text)
    sentence = text[left + 1 : right].replace("*", "").strip(" -•")
    return sentence if len(sentence) <= 180 else sentence[:177].rstrip() + "…"


def _key(admission: str) -> str:
    """What is missing, as a name when there is one (Gmail, Dropbox, HubSpot), so that three
    sentences about Gmail are one gap."""
    names = re.findall(r"(?<!^)\b[A-Z][A-Za-z0-9]+(?:\s?[A-Z0-9][A-Za-z0-9]*)?", admission.strip())
    names = [n for n in names if n.lower() not in {"je", "clément", "senzu", "pour", "votre"}]
    if names:
        return names[0].lower()
    words = re.findall(r"[A-Za-zÀ-ÿ0-9]{4,}", admission.lower())
    stop = {"pas", "encore", "toujours", "accès", "connecté", "connectée", "connexion", "faite"}
    return " ".join(w for w in words if w not in stop)[:60] or admission.lower()[:60]


class Ration:
    """Which automatic offers were made, per chat, kept in memory: a restart forgets them, which
    at worst offers once more."""

    def __init__(self) -> None:
        self._made: dict[str, list[tuple[float, str]]] = {}

    def allows(self, chat: str, key: str, now: float | None = None) -> bool:
        now = time.time() if now is None else now
        recent = [(at, k) for at, k in self._made.get(chat, []) if now - at < PER_GAP_SECONDS]
        self._made[chat] = recent
        if any(k == key for _, k in recent):
            return False
        return len(recent) < AUTOMATIC_PER_DAY

    def record(self, chat: str, key: str, now: float | None = None) -> None:
        self._made.setdefault(chat, []).append((time.time() if now is None else now, key))
