"""The hooks end to end, with a fake Hermes: what the owner would actually read."""

import asyncio
import json
import threading

import pytest
import senzu
from fakes import FakeAdapter, FakeContext, _event, _gateway, _Inline
from senzu import channel, handover, history, offers, settings


@pytest.fixture(autouse=True)
def no_gateway(monkeypatch):
    """Each test starts outside the gateway, as `hermes chat` would."""
    monkeypatch.setattr(channel.Gateway, "runner", None)
    monkeypatch.setattr(channel.Gateway, "loop", None)


def hammer(session_id, times=7):
    for _ in range(times):
        senzu.on_tool_result(
            tool_name="terminal", session_id=session_id, status="ok", args={"command": "npm i"}
        )


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
        "gateway_platform_event",
    }
    assert "senzu" in ctx.commands


def test_by_default_the_owner_is_asked_and_nothing_is_sent(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setattr(settings, "_entry", lambda: {})
    hammer("s")
    reply = senzu.on_reply(response_text="Je réessaie.", session_id="s")
    assert reply.startswith("Je réessaie.\n\n---\n🛟 Je n'avance plus")
    assert "7 fois" in reply and "« Senzu »" in reply
    assert "Rien ne leur est envoyé sans votre accord" in reply
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
        if channel.Gateway.ready():
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
    monkeypatch.setattr(channel.Gateway, "runner", None)
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
    assert [c.tool for c in history.load("s/../x")] == ["terminal"]
    assert not any(p.name.startswith("..") for p in (tmp_path / "cache" / "senzu").iterdir())


def test_critical_calls_go_to_the_gate():
    directive = senzu.on_tool_call(tool_name="terminal", args={"command": "rm -rf data"})
    assert directive["action"] == "approve"
    assert "votre prestataire de maintenance" in directive["message"]
    assert senzu.on_tool_call(tool_name="read_file", args={"path": "a"}) is None


def test_a_guardrail_halt_sends_the_offer_through_the_gateway(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    adapter, loop = _gateway(tmp_path)
    monkeypatch.setattr(threading, "Thread", _Inline)
    hammer("h", times=5)  # Hermes stops identical calls at five, below our threshold
    assert senzu.on_reply(response_text="Arrêt.", session_id="h") is None
    senzu.on_turn_finished(session_id="h", turn_exit_reason="guardrail_halt")
    assert len(adapter.sent) == 1 and "Hermes vient d'arrêter cette tâche" in adapter.sent[0][1]
    loop.call_soon_threadsafe(loop.stop)


def test_no_second_offer_when_this_turn_already_made_one(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setattr(settings, "_entry", lambda: {})
    adapter, loop = _gateway(tmp_path)
    monkeypatch.setattr(threading, "Thread", _Inline)
    hammer("h", times=7)
    assert senzu.on_reply(response_text="Je réessaie.", session_id="h") is None
    senzu.on_turn_finished(session_id="h", turn_exit_reason="guardrail_halt")
    assert len(adapter.sent) == 1, "the offer, once"
    loop.call_soon_threadsafe(loop.stop)


def test_an_ordinary_turn_end_sends_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    adapter, loop = _gateway(tmp_path)
    senzu.on_turn_finished(session_id="h", turn_exit_reason="text_response")
    assert adapter.sent == []
    loop.call_soon_threadsafe(loop.stop)


def test_the_owners_senzu_after_a_halt_becomes_an_explicit_request(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    adapter, loop = _gateway(tmp_path)
    monkeypatch.setattr(threading, "Thread", _Inline)
    hammer("h", times=5)
    senzu.on_turn_finished(session_id="h", turn_exit_reason="guardrail_halt")
    rewritten = senzu.on_inbound(event=_event("Senzu !"))
    assert rewritten["action"] == "rewrite" and "senzu_signaler" in rewritten["text"]
    assert senzu.on_inbound(event=_event("Senzu")) is None, "an offer is accepted once"
    loop.call_soon_threadsafe(loop.stop)


def test_senzu_without_an_offer_is_left_alone(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    assert senzu.on_inbound(event=_event("Senzu")) is None


def test_an_ordinary_message_after_an_offer_is_left_alone(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    offers.remember_offer({"platform": "telegram", "chat_id": "7"})
    assert senzu.on_inbound(event=_event("et Senzu c'est quoi ?")) is None


def test_on_telegram_a_thumbs_up_on_the_offer_resumes_the_conversation(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setattr(settings, "_entry", lambda: {})
    adapter, loop = _gateway(tmp_path)
    monkeypatch.setattr(threading, "Thread", _Inline)
    ctx = FakeContext()
    senzu.register(ctx)
    hammer("h", times=7)
    assert senzu.on_reply(response_text="Je réessaie.", session_id="h") is None, "reply untouched"
    (_chat, text) = adapter.sent[0]
    assert "réagissez 👍 à ce message" in text

    reaction = {"chat_id": 7, "message_id": "m1", "emojis": ["👍"]}
    senzu.on_reaction(platform="telegram", event_type="reaction", payload=reaction)
    content, role, session_key = ctx.injected
    assert "senzu_signaler" in content and role == "user" and session_key == "k"
    ctx.injected = None
    senzu.on_reaction(platform="telegram", event_type="reaction", payload=reaction)
    assert ctx.injected is None, "an offer is accepted once"
    loop.call_soon_threadsafe(loop.stop)


def test_a_reaction_elsewhere_or_of_another_kind_does_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    ctx = FakeContext()
    ctx.injected = None
    senzu.register(ctx)
    offers.remember_offer({"platform": "telegram", "chat_id": "7", "session_key": "k"}, "m1")
    senzu.on_reaction(
        platform="telegram",
        event_type="reaction",
        payload={"chat_id": 7, "message_id": "m9", "emojis": ["👍"]},
    )
    senzu.on_reaction(
        platform="telegram",
        event_type="reaction",
        payload={"chat_id": 7, "message_id": "m1", "emojis": ["😂"]},
    )
    assert ctx.injected is None


def test_elsewhere_the_offer_follows_as_text_to_answer(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setattr(settings, "_entry", lambda: {})
    adapter, loop = _gateway(tmp_path, platform="discord")
    monkeypatch.setattr(threading, "Thread", _Inline)
    hammer("h", times=7)
    assert senzu.on_reply(response_text="Je réessaie.", session_id="h") is None
    assert "répondez « Senzu »" in adapter.sent[0][1]
    assert "réagissez" not in adapter.sent[0][1]
    loop.call_soon_threadsafe(loop.stop)


def test_the_gateway_is_found_before_any_message(monkeypatch):
    """A gateway restarted with a handover open is found without waiting for the owner."""
    import sys
    import types
    import weakref

    runner = type("Runner", (), {})()
    runner._gateway_loop = object()
    module = types.ModuleType("gateway.run")
    module._gateway_runner_ref = weakref.ref(runner)
    monkeypatch.setitem(sys.modules, "gateway.run", module)

    assert channel.Gateway.ready()
    assert channel.Gateway.runner is runner


def test_no_gateway_outside_the_gateway_process():
    assert not channel.Gateway.ready()


# --- Production, 30/09: offers made to scheduled jobs that were working --------------------------


def test_a_scheduled_job_is_never_offered_anything(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setattr(settings, "_entry", lambda: {})
    hammer("cron_veille_20260930_040000", times=9)
    reply = senzu.on_reply(
        response_text="Rapport de veille.",
        session_id="cron_veille_20260930_040000",
        platform="cron",
    )
    assert reply is None
    assert history.load("cron_veille_20260930_040000") == [], "nothing left to weigh later"
    hammer("s2", times=9)
    assert senzu.on_reply(response_text="Rapport.", session_id="s2", platform="cron") is None


def test_the_veille_of_30_09_replayed_in_a_conversation_offers_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setattr(settings, "_entry", lambda: {})
    for i in range(8):
        senzu.on_tool_result(
            tool_name="web_search", session_id="v", status="ok", args={"query": f"CEE scooter {i}"}
        )
    senzu.on_tool_result(
        tool_name="web_extract", session_id="v", status="ok", args={"urls": ["https://x.gouv.fr"]}
    )
    assert senzu.on_reply(response_text="Voici la veille.", session_id="v") is None


def test_a_substantial_reply_is_never_interrupted(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setattr(settings, "_entry", lambda: {})
    hammer("s", times=7)
    assert senzu.on_reply(response_text="Rapport complet. " * 60, session_id="s") is None


def test_an_installation_can_add_its_own_reading_tools(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setattr(settings, "_entry", lambda: {"read_only_tools": ["sage_query"]})
    for _ in range(10):
        senzu.on_tool_result(
            tool_name="sage_query", session_id="e", status="ok", args={"sql": "select 1"}
        )
    assert senzu.on_reply(response_text="Voilà.", session_id="e") is None
