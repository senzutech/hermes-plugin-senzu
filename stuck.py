"""What a session's tool calls still say: whether the desk was already called.

Until 0.2.2 the calls were counted to recognise an assistant going nowhere. Measured against
real conversations, that found nothing worth an offer and offered help to scheduled jobs that
were working: the assistant says what it cannot do in its own reply (see ``gaps``). What remains
of the calls is the one thing they tell for sure, that a handover was already filed, so the
owner is never offered twice what they already asked for.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

# Calls kept per session: enough to cover any session where the desk was called.
WINDOW = 40
# Tools that prove the desk was already called. Never offer twice.
ALREADY_ASKED = ("senzu_signaler",)


@dataclass(frozen=True)
class Call:
    """One tool call, reduced to its name and verdict. Never its arguments or output."""

    tool: str
    failed: bool = False


@dataclass(frozen=True)
class Reading:
    """What the recorded calls of a session say."""

    already_asked: bool = False


def read(calls: Iterable[Call]) -> Reading:
    """Read the recorded calls of a session, oldest first."""
    return Reading(
        already_asked=any(needle in call.tool for call in calls for needle in ALREADY_ASKED),
    )


def call_from_hook(tool_name: str, status: str = "", **_: object) -> Call:
    """Build a call from Hermes' ``post_tool_call`` payload."""
    return Call(tool=tool_name or "?", failed=status in ("error", "blocked"))


def calls_from_json(rows: Iterable[Mapping[str, object]]) -> list[Call]:
    """Rebuild calls stored on disk, skipping anything unreadable."""
    return [
        Call(tool=str(row.get("tool") or "?"), failed=bool(row.get("failed")))
        for row in rows
        if isinstance(row, Mapping)
    ]
