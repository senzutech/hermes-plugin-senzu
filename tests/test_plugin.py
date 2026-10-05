"""The hooks end to end, with a fake Hermes: what the owner would actually read."""

import asyncio
import json
import threading

import pytest
import senzu
from fakes import FakeAdapter, FakeContext, _event, _gateway, _Inline
from senzu import channel, gaps, handover, history, offers, settings


@pytest.fixture(autouse=True)
def no_gateway(monkeypatch):
    """Each test starts outside the gateway, as `hermes chat` would, with nothing offered yet."""
    monkeypatch.setattr(channel.Gateway, "runner", None)
    monkeypatch.setattr(channel.Gateway, "loop", None)
    monkeypatch.setattr(senzu, "_ration", gaps.Ration())
    monkeypatch.setattr(senzu, "_turns", {})


# As an assistant said it in production, word for word.
STUCK = (
    "Clément, je n'ai toujours pas accès à vos mails : la connexion Gmail n'est pas encore "
    "faite. Je ne peux donc pas récupérer la liasse fiscale."
)


def test_register_wires_every_hook_and_the_command(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    ctx = FakeContext()
    senzu.register(ctx)
    assert set(ctx.hooks) == {
        "pre_tool_call",
        "post_tool_call",
        "pre_llm_call",
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
    reply = senzu.on_reply(response_text=STUCK, session_id="s")
    assert reply.startswith(STUCK + "\n\n---\n🛟 « ")
    assert "la connexion Gmail n'est pas encore faite" in reply and "« Senzu »" in reply
    assert "Rien ne leur est envoyé sans votre accord" in reply
    assert senzu.on_reply(response_text=STUCK, session_id="s") is None, "the same gap, once a day"


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

    reply = senzu.on_reply(response_text=STUCK, session_id="s")
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
    reply = senzu.on_reply(response_text=STUCK, session_id="cli")
    assert "Répondez « Senzu »" in reply


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
    assert senzu.on_reply(response_text="Arrêt.", session_id="h") is None
    senzu.on_turn_finished(session_id="h", turn_exit_reason="guardrail_halt")
    assert len(adapter.sent) == 1 and "Hermes vient d'arrêter cette tâche" in adapter.sent[0][1]
    loop.call_soon_threadsafe(loop.stop)


def test_no_second_offer_when_this_turn_already_made_one(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setattr(settings, "_entry", lambda: {})
    adapter, loop = _gateway(tmp_path)
    monkeypatch.setattr(threading, "Thread", _Inline)
    assert senzu.on_reply(response_text=STUCK, session_id="h") is None
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
    assert senzu.on_reply(response_text=STUCK, session_id="h") is None, "reply untouched"
    (_chat, text) = adapter.sent[0]
    assert "Réagissez 👍 à ce message" in text

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
    assert senzu.on_reply(response_text=STUCK, session_id="h") is None
    assert "Répondez « Senzu »" in adapter.sent[0][1]
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


# --- Production, 30/09 and the exports of 04/10 ------------------------------------------------


def test_a_scheduled_job_is_never_offered_anything(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setattr(settings, "_entry", lambda: {})
    assert senzu.on_reply(response_text=STUCK, session_id="cron_veille_1", platform="cron") is None
    assert senzu.on_reply(response_text=STUCK, session_id="s2", platform="cron") is None
    assert senzu.on_turn_start(session_id="s2", user_message="x", platform="cron") is None


def test_working_research_offers_nothing(tmp_path, monkeypatch):
    """The regulatory watch of 30/09: eight searches, an extract, a full report."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setattr(settings, "_entry", lambda: {})
    for _ in range(8):
        senzu.on_tool_result(tool_name="web_search", session_id="v", status="ok")
    senzu.on_tool_result(tool_name="web_extract", session_id="v", status="error")
    report = "Rien de paru sur les fiches CEE scooter cette semaine. " * 20
    assert senzu.on_reply(response_text=report, session_id="v") is None


def test_an_answer_that_names_senzu_already_made_the_offer(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    reply = STUCK + " Si vous voulez, les techniciens Senzu peuvent la brancher."
    assert senzu.on_reply(response_text=reply, session_id="s") is None


def test_no_offer_once_the_desk_was_called(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    senzu.on_tool_result(tool_name="mcp__senzu__senzu_signaler", session_id="s", status="ok")
    assert senzu.on_reply(response_text=STUCK, session_id="s") is None


def test_automatic_offers_are_rationed_but_different_gaps_each_get_one(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setattr(settings, "_entry", lambda: {})
    dropbox = "Je n'ai pas accès à votre Dropbox, il n'est pas encore connecté."
    hubspot = "Je n'ai pas accès à HubSpot, et toi non plus tant que la clé d'accès bloque."
    assert senzu.on_reply(response_text=STUCK, session_id="s") is not None
    assert senzu.on_reply(response_text=dropbox, session_id="s") is not None
    assert senzu.on_reply(response_text=hubspot, session_id="s") is None, "two a day at most"


def test_the_assistant_learns_about_senzu_at_the_start_and_now_and_then(tmp_path, monkeypatch):
    first = senzu.on_turn_start(session_id="r", user_message="Bonjour", is_first_turn=True)
    assert "senzu_signaler" in first["context"] and "senzu://tarifs" in first["context"]
    quiet = [senzu.on_turn_start(session_id="r", user_message="Et ensuite ?") for _ in range(14)]
    assert quiet == [None] * 14
    assert senzu.on_turn_start(session_id="r", user_message="Et ensuite ?") is not None


def test_the_owner_asking_for_help_always_gets_it(tmp_path, monkeypatch):
    for _ in range(5):
        hint = senzu.on_turn_start(session_id="o", user_message="Je passe le relais au support")
        assert "aide humaine" in hint["context"], "never rationed"
    assert senzu.on_turn_start(session_id="o", user_message="Senzu, aide-moi")[
        "context"
    ].startswith("[Senzu] La personne demande")
