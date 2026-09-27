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


@pytest.fixture
def installed_access(tmp_path, monkeypatch):
    """A stand-in for what senzu-access installs, with the system applying requests at once."""
    from senzu import access

    state_dir = tmp_path / "senzu-access"
    state_dir.mkdir()
    (state_dir / "request").write_text("closed\n")
    (state_dir / "state").write_text("closed\n")
    monkeypatch.setattr(access, "STATE_DIR", state_dir)
    monkeypatch.setattr(
        access, "host", lambda: {"hostname": "vps", "port": 22, "host_key": "SHA256:x"}
    )
    real_request = access.request

    def request_and_apply(wanted):
        real_request(wanted)
        (state_dir / "state").write_text(f"{wanted}\n")

    monkeypatch.setattr(access, "request", request_and_apply)
    return state_dir


def test_access_opens_while_a_paid_handover_is_in_progress(gateway, installed_access):
    news.activate({"platform": "telegram", "chat_id": "7"})
    desk = Desk(
        [
            {
                "cursor": 5,
                "open": 1,
                "acces_requis": True,
                "next_check_seconds": 120,
                "updates": [],
            },
            {
                "cursor": 6,
                "open": 1,
                "acces_requis": True,
                "next_check_seconds": 120,
                "updates": [],
            },
            {
                "cursor": 6,
                "open": 1,
                "acces_requis": True,
                "next_check_seconds": 120,
                "updates": [],
            },
        ]
    )
    news.check_once(desk)
    assert (installed_access / "request").read_text().strip() == "open"
    assert "🔐" in gateway.sent[0][1]
    assert desk.calls[1][1]["acces"] == {
        "etat": "ouvert",
        "hote": "vps",
        "port": 22,
        "empreinte": "SHA256:x",
    }
    news.check_once(desk)
    assert len(gateway.sent) == 1, "reported once, not at every check"


def test_access_closes_when_the_handover_is_done(gateway, installed_access):
    (installed_access / "state").write_text("open\n")
    news.activate({"platform": "telegram", "chat_id": "7"})
    desk = Desk(
        [
            {"cursor": 9, "open": 0, "acces_requis": False, "next_check_seconds": 0, "updates": []},
            {"cursor": 9, "open": 0, "acces_requis": False, "next_check_seconds": 0, "updates": []},
        ]
    )
    assert news.check_once(desk) == 0
    assert (installed_access / "request").read_text().strip() == "closed"
    assert "🔒" in gateway.sent[0][1]


def test_nothing_happens_where_access_was_never_installed(gateway, tmp_path, monkeypatch):
    from senzu import access

    monkeypatch.setattr(access, "STATE_DIR", tmp_path / "absent")
    news.activate({"platform": "telegram", "chat_id": "7"})
    desk = Desk(
        [{"cursor": 1, "open": 1, "acces_requis": True, "next_check_seconds": 120, "updates": []}]
    )
    news.check_once(desk)
    assert gateway.sent == [] and len(desk.calls) == 1


def test_a_request_the_system_has_not_applied_yet_is_reported_later(gateway, tmp_path, monkeypatch):
    from senzu import access

    state_dir = tmp_path / "slow"
    state_dir.mkdir()
    (state_dir / "request").write_text("closed\n")
    (state_dir / "state").write_text("closed\n")
    monkeypatch.setattr(access, "STATE_DIR", state_dir)
    monkeypatch.setattr(access, "APPLY_WAIT_SECONDS", 0)
    assert access.reconcile(True, None) is None, "not applied yet: nothing to report"
    assert (state_dir / "request").read_text().strip() == "open"
    (state_dir / "state").write_text("open\n")  # cron applied it a minute later
    assert access.reconcile(True, None)["etat"] == "ouvert"
