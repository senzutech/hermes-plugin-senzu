"""The owner's mood, read by the installation's model: two signs in a row, then the offer."""

import threading

import pytest
import senzu
from fakes import FakeContext, _event, _gateway, _Inline
from senzu import channel, gaps, mood, offers, settings


class MoodContext(FakeContext):
    """A model that finds the owner irritated whenever they are, by the word « encore »."""

    def __init__(self):
        super().__init__()
        self.read = []

    def complete_structured(self, instructions="", input=(), **_):
        text = input[0]["text"].rsplit("[dernier] ", 1)[-1]
        self.read.append(text)
        irritated = "encore" in text
        parsed = {"humeur": "agace" if irritated else "neutre", "contre_l_assistant": irritated}
        return type("Result", (), {"parsed": parsed, "text": ""})()


@pytest.fixture
def owner(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setattr(settings, "_entry", lambda: {})
    for chat in list(mood._recent):
        mood._recent.pop(chat)
    mood._signs.clear()
    mood._due.clear()
    monkeypatch.setattr(senzu, "_ration", gaps.Ration())
    adapter, loop = _gateway(tmp_path)
    ctx = MoodContext()
    senzu.register(ctx)  # before threads run inline: the news checker must stay in the background
    monkeypatch.setattr(threading, "Thread", _Inline)
    yield ctx, adapter
    senzu._offered.clear()  # what a turn's end does in Hermes
    loop.call_soon_threadsafe(loop.stop)


def test_two_signs_in_a_row_bring_the_offer_after_the_next_reply(owner):
    ctx, adapter = owner
    senzu.on_inbound(event=_event("ça plante encore"))
    assert senzu.on_reply(response_text="Je regarde.", session_id="h") is None
    assert adapter.sent == [], "one sign is not enough"
    senzu.on_inbound(event=_event("encore raté, franchement"))
    senzu.on_reply(response_text="Je réessaie.", session_id="h")
    assert len(adapter.sent) == 1
    assert "ça n'avance pas comme vous le voulez" in adapter.sent[0][1]
    assert offers.is_open(offers.chat_key("telegram", "7"))


def test_a_calm_message_in_between_resets_the_count(owner):
    ctx, adapter = owner
    senzu.on_inbound(event=_event("encore une erreur"))
    senzu.on_inbound(event=_event("merci, je vois"))
    senzu.on_inbound(event=_event("et encore"))
    senzu.on_reply(response_text="Voilà.", session_id="h")
    assert adapter.sent == []


def test_no_offer_while_one_is_already_open(owner):
    ctx, adapter = owner
    offers.remember_offer({"platform": "telegram", "chat_id": "7"})
    senzu.on_inbound(event=_event("encore"))
    senzu.on_inbound(event=_event("encore !"))
    senzu.on_reply(response_text="…", session_id="h")
    assert adapter.sent == []


def test_commands_and_single_characters_are_not_read(owner):
    ctx, _ = owner
    senzu.on_inbound(event=_event("/restart"))
    senzu.on_inbound(event=_event("?"))
    assert ctx.read == []


def test_the_owner_can_turn_it_off(owner, monkeypatch):
    ctx, _ = owner
    monkeypatch.setattr(settings, "_entry", lambda: {"mood": "off"})
    senzu.on_inbound(event=_event("encore"))
    assert ctx.read == []


def test_a_model_that_fails_is_no_signal():
    class Broken:
        class llm:
            @staticmethod
            def complete_structured(**_):
                raise TimeoutError("no model")

    assert mood.read(Broken(), "encore", []) is False


def test_the_model_sees_the_owners_previous_messages(owner):
    ctx, _ = owner
    senzu.on_inbound(event=_event("installe ClickUp"))
    senzu.on_inbound(event=_event("alors ?"))
    assert ctx.read == ["installe ClickUp", "alors ?"]
    assert channel.Gateway.ready()


def test_varied_attempts_that_do_not_work_and_an_irritated_owner_bring_the_offer(owner):
    """The calibration case: many different terminal commands, still not installed, and an owner
    who says so. The calls alone no longer speak; the owner does."""
    ctx, adapter = owner
    for i in range(26):
        senzu.on_tool_result(
            tool_name="terminal", session_id="h", status="ok", args={"command": f"essai {i}"}
        )
    senzu.on_inbound(event=_event("ça marche encore pas"))
    senzu.on_reply(response_text="Je réessaie autrement.", session_id="h")
    senzu.on_inbound(event=_event("encore raté"))
    senzu.on_reply(response_text="Encore une piste.", session_id="h")
    assert len(adapter.sent) == 1
    assert "ça n'avance pas comme vous le voulez" in adapter.sent[0][1]
