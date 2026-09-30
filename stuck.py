"""Recognising an assistant that is going nowhere.

The model is never asked whether it is stuck: at the moment it fails, a model is looking for a
workaround, not for someone to ask. So the plugin reads the calls, and two patterns speak:

* **the very same call, again**: one tool with the same arguments, over and over, while it
  makes up a good share of the recent work;
* **failures that keep coming**: two among the last calls, the last one included.

What does not speak, since 0.2.2: many calls to one tool with different arguments. That is what
research looks like (eight web searches, each on another question, then an extract), and it was
read as hammering in production, on scheduled jobs that were working. Reading and searching
tools never count as repetition at all.
"""

from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

# How many recent calls say something about failures. Older ones describe another problem.
FAILURE_WINDOW = 8
# Failures within that window that make a turn worth interrupting, the last one included.
FAILURES_TO_SPEAK = 2
# Identical calls that mean the assistant is hammering, per installation (see settings.py).
HAMMERING = 6
# How far back to look for that repetition. Deliberately not "since the owner last spoke": an
# owner who answers « ça marche toujours pas » every ten calls confirms the past repeats.
HAMMER_WINDOW = 40
# Tools that prove the desk was already called. Never offer twice.
ALREADY_ASKED = ("senzu_signaler",)
# Tools that only read or search. Calling them many times is how work gets done, not a loop.
READ_ONLY_TOOLS = frozenset(
    {
        "web_search",
        "web_extract",
        "session_search",
        "read_file",
        "search_files",
        "read_terminal",
        "browser_snapshot",
        "browser_get_images",
        "browser_console",
        "browser_vision",
        "ha_get_state",
        "ha_list_entities",
        "ha_list_services",
        "kanban_list",
        "kanban_show",
        "kanban_attachments",
        "feishu_doc_read",
        "feishu_drive_list_comments",
        "feishu_drive_list_comment_replies",
    }
)
# The same, recognised by name: a tool whose own name starts with a reading verb.
READ_ONLY_PREFIXES = ("read_", "get_", "list_", "search", "find_", "fetch_", "show_", "lookup")


@dataclass(frozen=True)
class Call:
    """One tool call, reduced to what the reading needs: never its output, never its arguments,
    only a fingerprint of them that tells two identical calls apart from two different ones."""

    tool: str
    failed: bool = False
    signature: str = ""
    read_only: bool = False


@dataclass(frozen=True)
class Reading:
    """What the recent calls say about how the session is going."""

    failures: int = 0
    # The largest number of identical calls (same tool, same arguments) that change something.
    repeats: int = 0
    # Identical calls that count as hammering, per installation (see settings.py).
    threshold: int = HAMMERING
    # Calls that change something, among the recent ones: what the repetition is a share of.
    window: int = 0
    just_failed: bool = False
    already_asked: bool = False

    @property
    def hammering(self) -> bool:
        """The same call, again and again, and a good share of the work: two fifths at least."""
        return self.repeats >= self.threshold and self.repeats * 5 >= self.window * 2

    @property
    def failing(self) -> bool:
        return self.failures >= FAILURES_TO_SPEAK and self.just_failed

    @property
    def deserves_an_offer(self) -> bool:
        return not self.already_asked and (self.hammering or self.failing)

    @property
    def observed(self) -> str:
        """The observation, in the owner's words, so they can weigh it."""
        if self.hammering:
            return f"l'assistant a relancé {self.repeats} fois exactement la même opération"
        return f"{self.failures} des dernières opérations ont échoué"


def read(calls: Iterable[Call], threshold: int = HAMMERING) -> Reading:
    """Read the recorded calls of a session, oldest first."""
    history = list(calls)
    recent = history[-FAILURE_WINDOW:]
    acting = [call for call in history[-HAMMER_WINDOW:] if not call.read_only]
    # Calls recorded before 0.2.2 carry no signature: each counts as different, never as a loop.
    counts = Counter((call.tool, call.signature) for call in acting if call.signature)
    return Reading(
        failures=sum(call.failed for call in recent),
        repeats=max(counts.values(), default=0),
        window=len(acting),
        threshold=threshold,
        just_failed=bool(history) and history[-1].failed,
        already_asked=any(needle in call.tool for call in history for needle in ALREADY_ASKED),
    )


def signature(args: Any) -> str:
    """A short fingerprint of a call's arguments, the same for the same arguments whatever their
    order or spacing. The arguments themselves are never kept: they can hold secrets."""
    try:
        text = json.dumps(args, sort_keys=True, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        text = repr(args)
    normalized = " ".join(text.split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


def _bare_name(tool: str) -> str:
    """An MCP tool's own name, without the server prefix Hermes adds."""
    return tool.rsplit("__", 1)[-1] if "__" in tool else tool


def _mcp_read_only(tool: str) -> bool:
    """Whether an MCP server declared this tool read-only (``readOnlyHint``), as Hermes recorded
    it. Looked up where the gateway already has it; outside Hermes there is nothing to find."""
    hints = getattr(sys.modules.get("tools.mcp_tool"), "_tool_read_only_hints", None)
    if not isinstance(hints, dict):
        return False
    for server, tools in hints.items():
        if not isinstance(tools, dict) or str(server) not in tool:
            continue
        for name, read_only in tools.items():
            if read_only is True and tool.endswith(str(name)):
                return True
    return False


def is_read_only(tool: str, extra: Iterable[str] = ()) -> bool:
    """Whether a tool only reads or searches: listed, named like it, or declared so."""
    bare = _bare_name(tool)
    listed = READ_ONLY_TOOLS | set(extra)
    return (
        tool in listed
        or bare in listed
        or bare.startswith(READ_ONLY_PREFIXES)
        or _mcp_read_only(tool)
    )


def call_from_hook(
    tool_name: str,
    status: str = "",
    args: Any = None,
    extra_read_only: Iterable[str] = (),
    **_: object,
) -> Call:
    """Build a call from Hermes' ``post_tool_call`` payload."""
    tool = tool_name or "?"
    return Call(
        tool=tool,
        failed=status in ("error", "blocked"),
        signature=signature(args) if args is not None else "",
        read_only=is_read_only(tool, extra_read_only),
    )


def calls_from_json(rows: Iterable[Mapping[str, object]]) -> list[Call]:
    """Rebuild calls stored on disk, skipping anything unreadable."""
    return [
        Call(
            tool=str(row.get("tool") or "?"),
            failed=bool(row.get("failed")),
            signature=str(row.get("sig") or ""),
            read_only=bool(row.get("ro")),
        )
        for row in rows
        if isinstance(row, Mapping)
    ]
