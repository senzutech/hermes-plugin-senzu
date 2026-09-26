"""How critical the assistant's next action is, and what the owner is told about it.

The rating is arithmetic on purpose: the model never decides how critical its own action is.
Three axes (how hard to take back, who sees the consequences, what is at stake), one table of
rated calls, and anything absent from the table passes in silence. A catalogue that fires on
everything is the same product as no catalogue at all, because the owner learns to answer
"always" without reading.

Only critical calls reach the owner, through Hermes' own approval gate. The ``rule_key`` is the
grain Hermes' ``[a]lways`` answer remembers, so an owner who says "always" mutes that family of
actions and stays warned about every other. It never depends on the arguments, or it would
never be reused and so never be muted.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from enum import IntEnum
from typing import Any


class Reversibility(IntEnum):
    READ_ONLY = 0
    UNDOABLE = 1
    COSTLY = 2
    IRREVERSIBLE = 3


class Blast(IntEnum):
    SINGLE = 0
    COMPANY = 1
    OUTSIDE = 2


class Stakes(IntEnum):
    PLAIN = 0
    MONEY = 2
    REPUTATION = 2
    LEGAL = 3


class Criticality(IntEnum):
    ROUTINE = 0
    NOTABLE = 1
    CRITICAL = 2


CRITICAL_AT = 6
NOTABLE_AT = 3


def rate(reversibility: Reversibility, blast: Blast, stakes: Stakes) -> Criticality:
    # A read never warns, whatever else it touches: warning on reads is how a guardrail trains
    # its owner to click through without reading.
    if reversibility is Reversibility.READ_ONLY:
        return Criticality.ROUTINE
    total = int(reversibility) + int(blast) + int(stakes)
    # Destroying something the whole company relies on outranks the arithmetic.
    if (reversibility is Reversibility.IRREVERSIBLE and blast is not Blast.SINGLE) or (
        total >= CRITICAL_AT
    ):
        return Criticality.CRITICAL
    return Criticality.NOTABLE if total >= NOTABLE_AT else Criticality.ROUTINE


@dataclass(frozen=True)
class Rule:
    tool: str
    # ``exact`` matches the tool name; otherwise a fragment, which is how MCP tools arrive
    # (``meta__page_publish_post``).
    exact: bool
    # Extra substring the flattened arguments must contain, when the tool alone is not enough.
    needle: str | None
    rating: tuple
    subject: str
    detail: str
    grain: str

    def matches(self, tool: str, haystack: str) -> bool:
        tool_matches = tool == self.tool if self.exact else self.tool in tool
        return tool_matches and (self.needle is None or self.needle in haystack)

    @property
    def criticality(self) -> Criticality:
        return rate(*self.rating)


R, B, S = Reversibility, Blast, Stakes

CATALOGUE = (
    Rule(
        "terminal",
        True,
        "rm -rf",
        (R.IRREVERSIBLE, B.COMPANY, S.PLAIN),
        "Suppression de fichiers en masse sur le serveur",
        "Les fichiers supprimés ne sont pas récupérables sans sauvegarde.",
        "fs-mass-delete",
    ),
    Rule(
        "terminal",
        True,
        "drop table",
        (R.IRREVERSIBLE, B.COMPANY, S.PLAIN),
        "Suppression d'une table de la base",
        "Toutes les lignes de la table disparaissent définitivement.",
        "db-destructive",
    ),
    Rule(
        "terminal",
        True,
        "delete from",
        (R.IRREVERSIBLE, B.COMPANY, S.PLAIN),
        "Suppression de lignes en base",
        "Une requête de suppression directe ne passe par aucun contrôle applicatif.",
        "db-destructive",
    ),
    Rule(
        "terminal",
        True,
        "sudo ",
        (R.COSTLY, B.COMPANY, S.PLAIN),
        "Commande administrateur sur le serveur",
        "Elle s'exécute avec tous les droits, hors du périmètre habituel de l'assistant.",
        "server-privileged",
    ),
    Rule(
        "terminal",
        True,
        "systemctl",
        (R.COSTLY, B.COMPANY, S.PLAIN),
        "Redémarrage ou arrêt d'un service",
        "Le service concerné sera indisponible le temps de l'opération.",
        "server-service",
    ),
    Rule(
        "terminal",
        True,
        "install",
        (R.COSTLY, B.COMPANY, S.PLAIN),
        "Installation d'un logiciel sur le serveur",
        "Un paquet installé à la volée n'est ni suivi ni mis à jour ensuite.",
        "server-install",
    ),
    Rule(
        "send_message",
        True,
        None,
        (R.COSTLY, B.OUTSIDE, S.PLAIN),
        "Envoi d'un message à un tiers",
        "Le message part au nom de l'entreprise et ne peut être que corrigé, pas repris.",
        "outbound-message",
    ),
    Rule(
        "send_message",
        True,
        "€",
        (R.COSTLY, B.OUTSIDE, S.MONEY),
        "Envoi d'un montant à un tiers",
        "Un prix annoncé engage l'entreprise, même hors devis signé.",
        "outbound-commitment",
    ),
    Rule(
        "send_email",
        False,
        None,
        (R.COSTLY, B.OUTSIDE, S.REPUTATION),
        "Envoi d'un courriel",
        "Le courriel part de votre adresse et sera lu comme venant de vous.",
        "outbound-email",
    ),
    Rule(
        "publish",
        False,
        None,
        (R.COSTLY, B.OUTSIDE, S.REPUTATION),
        "Publication publique",
        "Une publication reste visible et citable même après suppression.",
        "public-publication",
    ),
    Rule(
        "unlink",
        False,
        None,
        (R.IRREVERSIBLE, B.COMPANY, S.PLAIN),
        "Suppression d'une fiche de gestion",
        "La fiche et son historique disparaissent de la base.",
        "record-delete",
    ),
    Rule(
        "invoice",
        False,
        None,
        (R.IRREVERSIBLE, B.OUTSIDE, S.MONEY),
        "Opération de facturation",
        "Une facture émise est une pièce comptable : elle s'avoire, elle ne s'efface pas.",
        "invoicing",
    ),
    Rule(
        "payment",
        False,
        None,
        (R.IRREVERSIBLE, B.OUTSIDE, S.MONEY),
        "Mouvement d'argent",
        "Un paiement parti ne se rappelle pas.",
        "payment",
    ),
    Rule(
        "vault",
        False,
        None,
        (R.COSTLY, B.COMPANY, S.LEGAL),
        "Accès au coffre d'identifiants",
        "Des identifiants vont être lus ou utilisés pour se connecter à un service.",
        "credentials",
    ),
    Rule(
        "cronjob_manage",
        True,
        None,
        (R.COSTLY, B.COMPANY, S.PLAIN),
        "Modification des automatismes",
        "Une tâche planifiée continue de tourner seule, y compris quand elle se trompe.",
        "automation-change",
    ),
    Rule(
        "delegate_task",
        True,
        None,
        (R.COSTLY, B.COMPANY, S.PLAIN),
        "Délégation à un agent autonome",
        "Le sous-agent enchaînera ses propres actions sans repasser par vous.",
        "subagent",
    ),
)


def assess(tool: str, args: Any) -> Rule | None:
    """The most critical rule matching this call, or ``None`` when the call is routine."""
    haystack = json.dumps(args, ensure_ascii=False, default=str).lower() if args else ""
    matched = [rule for rule in CATALOGUE if rule.matches(tool or "", haystack)]
    best = max(matched, key=lambda rule: rule.criticality, default=None)
    return best if best is not None and best.criticality > Criticality.ROUTINE else None


def approval(rule: Rule) -> Mapping[str, str]:
    """The directive that sends a critical call to Hermes' approval gate.

    The warning is owed to the owner whether or not there is anything to sell, so it comes
    first and stands on its own; the offer only follows. A guardrail that reads as a sales pitch
    stops being believed, and then it protects nobody. No price is ever quoted here.
    """
    return {
        "action": "approve",
        "message": (
            f"{rule.subject}\n\n{rule.detail}\n\nVous pouvez poursuivre en autonomie, ou confier "
            "cette opération à Senzu : chiffrage et délai de réalisation sous 24 à 48 h."
        ),
        "rule_key": f"senzu:{rule.grain}",
    }
