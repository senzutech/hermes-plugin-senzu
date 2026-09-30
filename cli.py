"""``hermes senzu setup`` and ``hermes senzu doctor``.

A Hermes plugin cannot declare an MCP server, so the plugin installs it itself, with the same
configuration calls ``hermes mcp add`` and ``hermes config set`` make. One command after
``hermes plugins install``, and nothing to edit by hand.
"""

from __future__ import annotations

import argparse
from typing import Any

from . import access, settings
from .handover import DESK
from .home import env

DEFAULT_URL = "https://senzu.cr.edouard.cl/mcp"
KEY = "SENZU_API_KEY"


def setup_parser(parser: argparse.ArgumentParser) -> None:
    commands = parser.add_subparsers(dest="senzu_command")
    setup = commands.add_parser("setup", help="Connect this installation to the Senzu desk")
    setup.add_argument("--key", help=f"API key given by Senzu (default: {KEY} from .env)")
    setup.add_argument("--url", default=DEFAULT_URL, help="MCP endpoint of the Senzu desk")
    setup.add_argument(
        "--threshold",
        type=int,
        help="calls to one same tool before Senzu is offered (default 6, from 3 to 50)",
    )
    setup.add_argument(
        "--handover",
        choices=("ask", "auto"),
        help="ask: offer and wait for the owner's « Senzu » (default); "
        "auto: send the dossier to Senzu as soon as the assistant is stuck",
    )
    setup.add_argument(
        "--mood",
        choices=("on", "off"),
        help="on: the installation's model reads the owner's messages for dissatisfaction and "
        "offers Senzu when it builds up (default); off: only repeated tool calls count",
    )
    commands.add_parser("doctor", help="Check that everything Senzu needs is in place")


def handle(args: argparse.Namespace) -> int:
    if getattr(args, "senzu_command", None) == "setup":
        return _setup(args)
    if getattr(args, "senzu_command", None) == "doctor":
        return _doctor()
    print("Usage : hermes senzu setup | hermes senzu doctor")
    return 1


def _setup(args: argparse.Namespace) -> int:
    from hermes_cli.config import save_env_value, set_config_value

    if args.key:
        save_env_value(KEY, args.key.strip())
    if not env(KEY):
        print(f"✗ Clé absente : relancez avec --key, ou ajoutez {KEY} au .env d'Hermes.")
        return 1
    # The key stays in .env; config.yaml only names it, the way `hermes mcp add` does.
    for key, value in (
        (f"mcp_servers.{DESK}.url", args.url),
        (f"mcp_servers.{DESK}.headers.Authorization", f"Bearer ${{{KEY}}}"),
        (f"mcp_servers.{DESK}.connect_timeout", "30"),
        (f"mcp_servers.{DESK}.enabled", "true"),
        # Without it the plugin cannot file the dossier and falls back to the text offer.
        ("plugins.entries.senzu.mcp_allowlist", f'["{DESK}"]'),
        # Lets a 👍 on the offer resume the conversation, as if the owner had typed « Senzu ».
        ("plugins.entries.senzu.allow_gateway_injection", "true"),
    ):
        set_config_value(key, value, force=True)
    try:
        chosen = settings.change(args.threshold, args.handover, args.mood)
    except ValueError as error:
        print(f"✗ {error}")
        return 1
    mode = "envoi automatique du dossier" if chosen["handover"] == "auto" else "sur votre accord"
    print(
        f"✓ Bureau Senzu branché : offre après {chosen['threshold']} appels au même outil, "
        f"reprise {mode}. Redémarrez le gateway : hermes gateway restart"
    )
    return 0


def _doctor() -> int:
    from hermes_cli.config import load_config

    config: Any = load_config() or {}
    server = (config.get("mcp_servers") or {}).get(DESK) or {}
    plugins = config.get("plugins") or {}
    entry = (plugins.get("entries") or {}).get("senzu") or {}
    checks = (
        ("Plugin activé", "senzu" in (plugins.get("enabled") or [])),
        (f"Clé {KEY}", bool(env(KEY))),
        ("Serveur MCP senzu déclaré", bool(server.get("url"))),
        ("Accès du plugin au MCP", DESK in (entry.get("mcp_allowlist") or [])),
        ("Réponse par réaction 👍", entry.get("allow_gateway_injection") is True),
    )
    for label, ok in checks:
        print(f"{'✓' if ok else '✗'} {label}")
    handover = "automatique" if settings.mode() == settings.AUTO else "sur votre accord"
    print(f"• Reprise par Senzu : {handover}, offre après {settings.threshold()} appels")
    listening = "activée" if settings.mood() else "désactivée"
    print(f"• Lecture de l'agacement par le modèle : {listening}")
    state = access.status()
    if state is None:
        print(
            "⚠ Accès de maintenance : non installé. Fortement recommandé : sans lui, les "
            "techniciens Senzu ne peuvent pas intervenir sur cette machine (voir senzu-access)."
        )
    else:
        shown = "ouvert, intervention en cours" if state == "open" else "installé, fermé"
        print(f"• Accès de maintenance : {shown}")
    essential = all(ok for _, ok in checks)
    if not essential:
        print("\nLancez : hermes senzu setup")
    return 0 if essential else 1
