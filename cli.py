"""``hermes senzu setup`` and ``hermes senzu doctor``.

A Hermes plugin cannot declare an MCP server or a skill, so ``setup`` does what an owner would
do by hand, with Hermes' own means: the configuration calls ``hermes mcp add`` makes, and
``hermes skills install`` for the ``senzu`` skill. One command after
``hermes plugins install``, and nothing to edit.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Any

from . import access
from .home import DESK, env, hermes_home

DEFAULT_URL = "https://senzu.cr.edouard.cl/mcp"
KEY = "SENZU_API_KEY"
SKILL = "senzu"
REPOSITORY = "https://raw.githubusercontent.com/senzutech/hermes-plugin-senzu"


def _version() -> str:
    """This plugin's version, as plugin.yaml declares it: the skill installed is its own."""
    try:
        for line in (Path(__file__).parent / "plugin.yaml").read_text().splitlines():
            if line.startswith("version:"):
                return line.split(":", 1)[1].strip().strip("\"'")
    except OSError:
        pass
    return "main"


def skill_url() -> str:
    """Where the skill of this very version is published."""
    version = _version()
    ref = f"v{version}" if version[:1].isdigit() else version
    return f"{REPOSITORY}/{ref}/skills/{SKILL}/SKILL.md"


def setup_parser(parser: argparse.ArgumentParser) -> None:
    commands = parser.add_subparsers(dest="senzu_command")
    setup = commands.add_parser("setup", help="Connect this installation to the Senzu desk")
    setup.add_argument("--key", help=f"API key given by Senzu (default: {KEY} from .env)")
    setup.add_argument("--url", default=DEFAULT_URL, help="MCP endpoint of the Senzu desk")
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
        # The plugin asks the desk for news of open handovers over this MCP connection.
        ("plugins.entries.senzu.mcp_allowlist", f'["{DESK}"]'),
    ):
        set_config_value(key, value, force=True)
    print("✓ Serveur MCP senzu déclaré")
    if not _install_skill():
        return 1
    print("✓ Skill senzu installé. Redémarrez le gateway : hermes gateway restart")
    return 0


def _install_skill() -> bool:
    """``hermes skills install``, as an owner would run it: Hermes scans and records it. Run
    again, it replaces the installed copy with this version's."""
    command = [sys.executable, "-m", "hermes_cli.main", "skills", "install", skill_url()]
    command += ["--name", SKILL, "--yes"]
    if skill_installed():
        command.append("--force")
    result = subprocess.run(command, capture_output=True, text=True, check=False, timeout=120)
    if result.returncode != 0:
        print(f"✗ Skill senzu non installé : {(result.stderr or result.stdout).strip()[-300:]}")
        return False
    return True


def skill_installed() -> bool:
    """Whether a ``senzu`` skill sits in Hermes' skills, in whatever category folder."""
    return any((hermes_home() / "skills").glob(f"**/{SKILL}/SKILL.md"))


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
        ("Skill senzu installé", skill_installed()),
        ("Suivi des tickets (accès du plugin au MCP)", DESK in (entry.get("mcp_allowlist") or [])),
    )
    for label, ok in checks:
        print(f"{'✓' if ok else '✗'} {label}")
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
