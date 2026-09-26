"""Recognising an assistant that is going nowhere.

Calibrated on real sessions rather than on guesses. What "stuck" looks like is not failure (one
failure for 42 successes in the session this was measured on) and not repeated results either,
they were all different. It is **the same tool, again and again, while the thing the owner asked
for still is not done**: 26 calls to ``terminal``, and ClickUp still not installed.

The model is never asked whether it is stuck. At the moment it fails, a model is looking for a
workaround, not for someone to ask; every attempt to make it notice by itself was measured, and
none of them ever fired.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

# How many recent calls say something about failures. Older ones describe another problem.
FAILURE_WINDOW = 8
# Failures within that window that make a turn worth interrupting, the last one included.
FAILURES_TO_SPEAK = 2
# Calls to one same tool that mean the assistant is hammering. Across the stuck sessions
# observed, the dominant tool was called 7, 9, 12 and 26 times.
HAMMERING = 6
# How far back to look for that repetition. Deliberately not "since the owner last spoke":
# an owner who answers « ça marche toujours pas » every ten calls is confirming that the past
# repeats, not starting afresh, and resetting on it meant the threshold was never reached.
HAMMER_WINDOW = 40
# Tools that prove the desk was already called. Never offer twice.
ALREADY_ASKED = ("senzu_signaler",)


@dataclass(frozen=True)
class Call:
    """One tool call, reduced to what the reading needs. Never its output."""

    tool: str
    failed: bool = False


@dataclass(frozen=True)
class Reading:
    """What the recent calls say about how the session is going."""

    failures: int = 0
    repeats: int = 0
    window: int = 0
    just_failed: bool = False
    already_asked: bool = False

    @property
    def deserves_an_offer(self) -> bool:
        """Two independent reasons, because the two ways of being stuck do not look alike.

        Hammering is a share, not a count: a session that works spreads itself over several
        tools (ten calls each out of forty, a quarter) while a stuck one is dominated by one,
        between 48 and 60 per cent in the sessions measured. The line sits at two fifths.
        """
        if self.already_asked:
            return False
        dominates = self.repeats * 5 >= self.window * 2
        hammering = self.repeats >= HAMMERING and dominates
        failing = self.failures >= FAILURES_TO_SPEAK and self.just_failed
        return hammering or failing

    @property
    def observed(self) -> str:
        """The observation, in the owner's words, so they can weigh it."""
        if self.repeats >= HAMMERING:
            return f"l'assistant a relancé {self.repeats} fois le même outil sans aboutir"
        return f"{self.failures} des dernières opérations ont échoué"


def read(calls: Iterable[Call]) -> Reading:
    """Read the recorded calls of a session, oldest first."""
    history = list(calls)
    recent = history[-FAILURE_WINDOW:]
    hammer = history[-HAMMER_WINDOW:]
    counts = Counter(call.tool for call in hammer)
    return Reading(
        failures=sum(call.failed for call in recent),
        repeats=max(counts.values(), default=0),
        window=len(hammer),
        just_failed=bool(history) and history[-1].failed,
        already_asked=any(needle in call.tool for call in history for needle in ALREADY_ASKED),
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
