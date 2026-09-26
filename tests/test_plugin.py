"""The hooks end to end, with a fake Hermes: what the owner would actually read."""

import asyncio
import json
import threading

import senzu
from senzu import handover


class FakeContext:
    def __init__(self, link="https://desk.example/accepter/0b2c-token"):
        self.hooks, self.commands, self.filed = {}, {}, []
        self.link = link
        self.llm = self

    def register_hook(self, name, callback):
        self.hooks[name] = callback

    def register_cli_command(self, name, **kwargs):
        self.commands[name] = kwargs

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
    }
    assert "senzu" in ctx.commands


def test_by_default_the_owner_is_asked_and_nothing_is_sent(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setattr(handover, "mode", lambda: handover.ASK)
    hammer("s")
    reply = senzu.on_reply(response_text="Je réessaie.", session_id="s")
    assert reply.startswith("Je réessaie.\n\n---\n[Senzu]")
    assert "7 fois" in reply and "« Senzu »" in reply
    assert "Rien ne leur est envoyé sans votre réponse" in reply
    assert senzu.on_reply(response_text="Encore.", session_id="s") is None, "offered once"


def test_auto_mode_files_the_dossier_and_sends_the_link_through_the_gateway(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setattr(handover, "mode", lambda: handover.AUTO)
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
    monkeypatch.setattr(handover, "mode", lambda: handover.AUTO)
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
