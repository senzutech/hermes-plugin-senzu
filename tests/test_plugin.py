"""The hooks end to end, with a fake Hermes: what the owner would actually read."""

import asyncio
import json
import threading

import senzu
from senzu import handover, settings


class FakeContext:
    def __init__(self, link="https://desk.example/accepter/0b2c-token"):
        self.hooks, self.commands, self.filed = {}, {}, []
        self.link = link
        self.llm = self

    def register_hook(self, name, callback):
        self.hooks[name] = callback

    def register_cli_command(self, name, **kwargs):
        self.commands[name] = kwargs

    def register_tool(self, name, **kwargs):
        self.commands[f"tool:{name}"] = kwargs

    def complete_structured(self, **_):
        dossier = {
            "objectif": "installer ClickUp",
            "blocage": "OAuth impossible sans navigateur",
            "tentatives": ["login"],
            "urgence": "genant",
            "climat": "agace",
        }
        return type("Result", (), {"parsed": dossier, "text": ""})()

    def call_mcp(self, server, tool, arguments, timeout=30):
        self.filed.append((server, tool, arguments))
        return {"ok": True, "result": f"Signalement reçu. Page de validation : {self.link}"}


class FakeAdapter:
    def __init__(self):
        self.sent = []

    async def send(self, chat_id, content, metadata=None):
        self.sent.append((chat_id, content))


def hammer(session_id, times=7):
    for _ in range(times):
        senzu.on_tool_result(tool_name="terminal", session_id=session_id, status="ok")


def test_register_wires_every_hook_and_the_command(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    ctx = FakeContext()
    senzu.register(ctx)
    assert set(ctx.hooks) == {
        "pre_tool_call",
        "post_tool_call",
        "pre_gateway_dispatch",
        "transform_llm_output",
        "post_llm_call",
        "on_session_end",
    }
    assert "senzu" in ctx.commands
    assert "tool:senzu_settings" in ctx.commands


def test_by_default_the_owner_is_asked_and_nothing_is_sent(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setattr(settings, "_entry", lambda: {})
    hammer("s")
    reply = senzu.on_reply(response_text="Je réessaie.", session_id="s")
    assert reply.startswith("Je réessaie.\n\n---\n[Senzu]")
    assert "7 fois" in reply and "« Senzu »" in reply
    assert "Rien ne leur est envoyé sans votre réponse" in reply
    assert senzu.on_reply(response_text="Encore.", session_id="s") is None, "offered once"


def test_auto_mode_files_the_dossier_and_sends_the_link_through_the_gateway(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setattr(settings, "_entry", lambda: {"handover": "auto"})
    (tmp_path / "sessions").mkdir()
    (tmp_path / "sessions" / "sessions.json").write_text(
        json.dumps({"k": {"session_id": "s", "origin": {"platform": "discord", "chat_id": "42"}}})
    )
    loop = asyncio.new_event_loop()
    threading.Thread(target=loop.run_forever, daemon=True).start()
    adapter = FakeAdapter()
    gateway = type("Runner", (), {"adapters": {"discord": adapter}})()
    ctx = FakeContext()
    senzu.register(ctx)
    loop.call_soon_threadsafe(lambda: senzu.on_inbound(gateway=gateway))
    for _ in range(50):
        if handover.Gateway.ready():
            break
        threading.Event().wait(0.01)

    hammer("s")
    reply = senzu.on_reply(response_text="Je réessaie.", session_id="s")
    assert "je transmets le dossier" in reply
    handover.auto_handover(ctx, "s", [{"role": "user", "content": "installe ClickUp"}], "x")

    assert ctx.filed and ctx.filed[0][1] == "senzu_signaler"
    assert adapter.sent == [
        (
            "42",
            "[Senzu] Dossier transmis à vos experts Senzu : « installer ClickUp ». "
            "Pour valider leur intervention, sans engagement avant ce clic : "
            "https://desk.example/accepter/0b2c-token",
        ),
    ]
    loop.call_soon_threadsafe(loop.stop)


def test_auto_mode_without_a_gateway_falls_back_to_asking(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setattr(settings, "_entry", lambda: {"handover": "auto"})
    monkeypatch.setattr(handover.Gateway, "runner", None)
    hammer("cli")
    reply = senzu.on_reply(response_text="Je réessaie.", session_id="cli")
    assert "répondez « Senzu »" in reply


def test_honest_work_is_left_alone(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    for tool in ["terminal", "read_file", "terminal", "search_files"]:
        senzu.on_tool_result(tool_name=tool, session_id="s", status="ok")
    assert senzu.on_reply(response_text="Fait.", session_id="s") is None


def test_history_survives_on_disk(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    senzu.on_tool_result(tool_name="terminal", session_id="s/../x", status="error")
    assert [c.tool for c in handover.load("s/../x")] == ["terminal"]
    assert not any(p.name.startswith("..") for p in (tmp_path / "cache" / "senzu").iterdir())


def test_critical_calls_go_to_the_gate():
    directive = senzu.on_tool_call(tool_name="terminal", args={"command": "rm -rf data"})
    assert directive["action"] == "approve"
    assert "votre prestataire de maintenance" in directive["message"]
    assert senzu.on_tool_call(tool_name="read_file", args={"path": "a"}) is None


def _gateway(tmp_path, platform="telegram"):
    (tmp_path / "sessions").mkdir(exist_ok=True)
    (tmp_path / "sessions" / "sessions.json").write_text(
        json.dumps({"k": {"session_id": "h", "origin": {"platform": platform, "chat_id": "7"}}})
    )
    loop = asyncio.new_event_loop()
    threading.Thread(target=loop.run_forever, daemon=True).start()
    adapter = FakeAdapter()
    handover.Gateway.runner = type("Runner", (), {"adapters": {platform: adapter}})()
    handover.Gateway.loop = loop
    return adapter, loop


def test_a_guardrail_halt_sends_the_offer_through_the_gateway(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    adapter, loop = _gateway(tmp_path)
    monkeypatch.setattr(threading, "Thread", _Inline)
    hammer("h", times=5)  # Hermes stops identical calls at five, below our threshold
    assert senzu.on_reply(response_text="Arrêt.", session_id="h") is None
    senzu.on_turn_finished(session_id="h", turn_exit_reason="guardrail_halt")
    assert len(adapter.sent) == 1 and "Hermes vient d'arrêter cette tâche" in adapter.sent[0][1]
    loop.call_soon_threadsafe(loop.stop)


def test_no_second_offer_when_the_reply_already_carried_one(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setattr(settings, "_entry", lambda: {})
    adapter, loop = _gateway(tmp_path)
    monkeypatch.setattr(threading, "Thread", _Inline)
    hammer("h", times=7)
    assert senzu.on_reply(response_text="Je réessaie.", session_id="h")
    senzu.on_turn_finished(session_id="h", turn_exit_reason="guardrail_halt")
    assert adapter.sent == []
    loop.call_soon_threadsafe(loop.stop)


def test_an_ordinary_turn_end_sends_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    adapter, loop = _gateway(tmp_path)
    senzu.on_turn_finished(session_id="h", turn_exit_reason="text_response")
    assert adapter.sent == []
    loop.call_soon_threadsafe(loop.stop)


class _Inline:
    """Runs the thread's target at once, without the delay, so the test sees the send."""

    def __init__(self, target, args=(), **_):
        self.target, self.args = target, args

    def start(self):
        if self.target is handover.send_later:
            handover.send(*self.args[:2])
        else:
            self.target(*self.args)
