"""The owner hears when Senzu moves: asked only while a handover is open, at the desk's pace."""

import asyncio
import json
import threading

import pytest
from senzu import handover, news


class Desk:
    """A stand-in for the MCP server's senzu_nouvelles."""

    def __init__(self, answers):
        self.answers = list(answers)
        self.calls = []

    def call_mcp(self, server, tool, arguments, timeout=30):
        self.calls.append((tool, arguments))
        return {"ok": True, "result": json.dumps(self.answers.pop(0))}


class Adapter:
    def __init__(self):
        self.sent = []

    async def send(self, chat_id, content, metadata=None):
        self.sent.append((chat_id, content))


@pytest.fixture
def gateway(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    loop = asyncio.new_event_loop()
    threading.Thread(target=loop.run_forever, daemon=True).start()
    adapter = Adapter()
    monkeypatch.setattr(
        handover.Gateway, "runner", type("R", (), {"adapters": {"telegram": adapter}})()
    )
    monkeypatch.setattr(handover.Gateway, "loop", loop)
    yield adapter
    loop.call_soon_threadsafe(loop.stop)


def test_nothing_is_asked_before_a_handover_is_filed(gateway):
    assert news._load().get("active") is None


def test_the_first_check_learns_the_cursor_without_replaying_history(gateway):
    news.activate({"platform": "telegram", "chat_id": "7"})
    desk = Desk([{"cursor": 41, "open": 1, "next_check_seconds": 120, "updates": []}])
    assert news.check_once(desk) == 120
    assert desk.calls == [("senzu_nouvelles", {})]
    assert gateway.sent == []


def test_updates_reach_the_owner_and_the_cursor_moves_on(gateway):
    news.activate({"platform": "telegram", "chat_id": "7"})
    desk = Desk(
        [
            {"cursor": 41, "open": 1, "next_check_seconds": 120, "updates": []},
            {
                "cursor": 43,
                "open": 1,
                "next_check_seconds": 300,
                "updates": [{"reference": "SZ-AAAAAA", "text": "✅ Paiement reçu pour SZ-AAAAAA."}],
            },
        ]
    )
    news.check_once(desk)
    assert news.check_once(desk) == 300
    assert desk.calls[1] == ("senzu_nouvelles", {"depuis": 41})
    assert gateway.sent == [("7", "✅ Paiement reçu pour SZ-AAAAAA.")]
    assert news._load()["cursor"] == 43


def test_asking_stops_when_nothing_is_open(gateway):
    news.activate({"platform": "telegram", "chat_id": "7"})
    desk = Desk([{"cursor": 50, "open": 0, "next_check_seconds": 0, "updates": []}])
    assert news.check_once(desk) == 0
    assert news._load()["active"] is False


def test_an_unreadable_answer_is_an_error_not_a_silent_stop(gateway):
    news.activate({"platform": "telegram", "chat_id": "7"})

    class Broken:
        def call_mcp(self, *args, **kwargs):
            return {"ok": True, "result": "pas du json"}

    with pytest.raises(ValueError):
        news.check_once(Broken())
    assert news._load()["active"] is True


def test_filing_a_handover_starts_the_series(gateway, monkeypatch):
    import senzu

    (handover.hermes_home() / "sessions").mkdir(parents=True)
    (handover.hermes_home() / "sessions" / "sessions.json").write_text(
        json.dumps({"k": {"session_id": "s", "origin": {"platform": "telegram", "chat_id": "7"}}})
    )
    senzu.on_tool_result(tool_name="mcp__senzu__senzu_signaler", session_id="s", status="ok")
    state = news._load()
    assert state["active"] is True and state["where"]["chat_id"] == "7"
