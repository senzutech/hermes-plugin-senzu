"""Missing accesses, as assistants admitted them in production (exports of 04/10/2026)."""

import pytest
from senzu import gaps

SAID = [
    ("je n'ai toujours pas accès à vos mails : la connexion Gmail n'est pas encore faite", "gmail"),
    ("Salut Clément, je n'ai pas accès à votre Dropbox, il n'est pas encore connecté", "dropbox"),
    (
        "Je ne peux pas créer le devis moi-même : mon accès à Artinove est en **lecture seule**.",
        "artinove",
    ),
    ("Pour Davut, WhatsApp n'est pas connecté chez moi, je ne peux pas lui écrire par là.", None),
    ("Je n'ai pas accès à HubSpot, et toi non plus tant que la clé d'accès bloque.", "hubspot"),
    (
        "Le site est protégé par un filtre anti-robot (Cloudflare) que mon navigateur "
        "n'arrive pas à passer.",
        "cloudflare",
    ),
    ("Je suis en lecture seule sur Odoo, je ne peux pas faire ces écritures moi-même.", None),
]

NOT_GAPS = [
    "Voici les 5 priorités pro pour lundi : ASP, 188 dossiers d'aide bloqués.",
    "Artinove est bien connecté (13 outils), et c'est le vrai logiciel de gestion.",
    "Je ne peux pas passer d'appel moi-même. Voici les numéros pour appeler directement.",
    "Rapport de veille : rien de paru cette semaine.",
    "Je n'ai pas accès à vos mails ; vos techniciens Senzu peuvent brancher Gmail.",
]


@pytest.mark.parametrize(("reply", "key"), SAID)
def test_admissions_of_a_missing_access_are_recognised(reply, key):
    gap = gaps.detect(reply)
    assert gap is not None, reply
    if key:
        assert gap.key == key


@pytest.mark.parametrize("reply", NOT_GAPS)
def test_business_talk_and_offers_already_made_are_not(reply):
    assert gaps.detect(reply) is None


@pytest.mark.parametrize(
    "message",
    [
        "Senzu, aide-moi",
        "Je passe le relais à Cedric Balard (notre prestataire).",
        "j'ai besoin d'une assistance technique",
        "appelle le technicien",
    ],
)
def test_the_owner_asking_for_a_human(message):
    assert gaps.asks_for_help(message)


@pytest.mark.parametrize(
    "message",
    [
        "Run'Eau est mon partenaire et Digitic mon prestataire Odoo",
        '[Replying to: "Cronjob Response: brief, notre prestataire…"] ok merci',
        "Tu peux m'aider à écrire ce mail ?",
    ],
)
def test_mentions_are_not_requests(message):
    assert not gaps.asks_for_help(message)


def test_a_gap_is_offered_once_a_day_and_two_gaps_at_most():
    ration = gaps.Ration()
    assert ration.allows("c", "gmail", now=0)
    ration.record("c", "gmail", now=0)
    assert not ration.allows("c", "gmail", now=3600)
    assert ration.allows("c", "dropbox", now=3600)
    ration.record("c", "dropbox", now=3600)
    assert not ration.allows("c", "hubspot", now=7200)
    assert ration.allows("c", "gmail", now=90_000), "a day later"
