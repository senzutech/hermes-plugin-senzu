"""Senzu's maintenance access on this machine, open while a paid handover is in progress.

The access itself is installed once, by an administrator, with the separate senzu-access tool
(https://github.com/senzutech/senzu-access): a `senzu` account reached with Senzu's SSH key,
closed by default, and a request file the Hermes user may write, "open" or "closed". The system
applies the request; this plugin has no elevated rights and needs none. It writes what the desk
says (open while a paid handover is in progress, closed otherwise), reads back what the system
did, and reports each change to the desk and to the owner once.

On a machine where the access was never installed, nothing happens.
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

log = logging.getLogger("hermes_plugins.senzu")

STATE_DIR = Path("/var/lib/senzu-access")
HOST_FILE = Path("/etc/senzu/access.json")
# How long to wait for the system to apply a request before leaving it to the next check.
APPLY_WAIT_SECONDS = 10


def _request_file() -> Path:
    return STATE_DIR / "request"


def _state_file() -> Path:
    return STATE_DIR / "state"


def installed() -> bool:
    """Whether the access is installed here and this user may ask for it to change."""
    return _request_file().is_file() and os.access(_request_file(), os.W_OK)


def status() -> str | None:
    """What the system last applied: "open", "closed", or None when not installed."""
    if not installed():
        return None
    try:
        state = _state_file().read_text().strip()
    except OSError:
        return None
    return state if state in ("open", "closed") else "closed"


def request(wanted: str) -> None:
    """Ask the system for "open" or "closed". Only the content of the file changes."""
    try:
        with _request_file().open("w") as handle:
            handle.write(f"{wanted}\n")
    except OSError as error:
        log.warning("senzu: access request not written: %s", error)


def host() -> dict:
    """Where Senzu connects, as the installation recorded it."""
    try:
        details = json.loads(HOST_FILE.read_text())
    except (OSError, ValueError):
        return {}
    return details if isinstance(details, dict) else {}


def reconcile(required: bool, last_reported: str | None) -> dict | None:
    """Ask for what the desk wants and, once the system has applied it, return the report to
    send, one time per change. None when there is nothing new to report."""
    if not installed():
        return None
    wanted = "open" if required else "closed"
    if status() != wanted:
        request(wanted)
        deadline = time.monotonic() + APPLY_WAIT_SECONDS
        while status() != wanted and time.monotonic() < deadline:
            time.sleep(0.5)
    applied = status()
    if applied != wanted or applied == last_reported:
        return None
    details = host()
    return {
        "etat": "ouvert" if applied == "open" else "ferme",
        "hote": details.get("hostname"),
        "port": details.get("port"),
        "empreinte": details.get("host_key"),
    }


def owner_message(report: dict) -> str:
    """What the owner reads when the access changes: they always know."""
    if report.get("etat") == "ouvert":
        return (
            "🔐 Accès de maintenance Senzu ouvert pour l'intervention en cours. Il se refermera "
            "automatiquement à la fin de l'intervention."
        )
    return "🔒 Accès de maintenance Senzu refermé."
