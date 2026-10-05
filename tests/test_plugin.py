"""The plugin as Hermes loads it: two hooks, a CLI command, and nothing that talks for the model."""

import sys
import types
import weakref

import pytest
import senzu
from senzu import channel, cli, news


class FakeContext:
    def __init__(self):
        self.hooks, self.commands = {}, {}

    def register_hook(self, name, callback):
        self.hooks[name] = callback

    def register_cli_command(self, name, **kwargs):
        self.commands[name] = kwargs


@pytest.fixture(autouse=True)
def no_gateway(monkeypatch):
    """Each test starts outside the gateway, as `hermes chat` would."""
    monkeypatch.setattr(channel.Gateway, "runner", None)
    monkeypatch.setattr(channel.Gateway, "loop", None)


def test_register_wires_the_two_hooks_and_the_command(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setattr(news, "start", lambda ctx: None)
    ctx = FakeContext()
    senzu.register(ctx)
    assert set(ctx.hooks) == {"pre_tool_call", "post_tool_call"}
    assert "senzu" in ctx.commands


def test_critical_calls_go_to_the_gate():
    directive = senzu.on_tool_call(tool_name="terminal", args={"command": "rm -rf data"})
    assert directive["action"] == "approve"
    assert "votre prestataire de maintenance" in directive["message"]
    assert senzu.on_tool_call(tool_name="read_file", args={"path": "a"}) is None


def test_a_filed_handover_starts_the_news(monkeypatch):
    started = []
    monkeypatch.setattr(news, "activate", started.append)
    monkeypatch.setattr(channel, "origin", lambda session_id: {"chat_id": session_id})
    senzu.on_tool_result(tool_name="mcp__senzu__senzu_signaler", session_id="s", status="ok")
    senzu.on_tool_result(tool_name="mcp__senzu__senzu_signaler", session_id="t", status="error")
    senzu.on_tool_result(tool_name="terminal", session_id="u", status="ok")
    assert started == [{"chat_id": "s"}]


def test_the_skill_installed_is_this_versions(monkeypatch):
    version = cli._version()
    assert version[:1].isdigit()
    assert cli.skill_url().endswith(f"/v{version}/skills/senzu/SKILL.md")


def test_the_skill_is_found_in_any_category(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    assert not cli.skill_installed()
    (tmp_path / "skills" / "support" / "senzu").mkdir(parents=True)
    (tmp_path / "skills" / "support" / "senzu" / "SKILL.md").write_text("---\nname: senzu\n---\n")
    assert cli.skill_installed()


def test_the_skill_says_when_and_how():
    from pathlib import Path

    skill = (Path(senzu.__file__).parent / "skills" / "senzu" / "SKILL.md").read_text()
    front, body = skill.split("---", 2)[1:]
    assert "name: senzu" in front and "description:" in front
    assert "requires_tools: [mcp__senzu__senzu_signaler]" in front
    for needed in ("senzu://tarifs", "mcp__senzu__senzu_signaler", "nature", "cause_inconnue"):
        assert needed in body


def test_the_gateway_is_found_before_any_message(monkeypatch):
    """A gateway restarted with a handover open is found without waiting for the owner."""
    runner = type("Runner", (), {})()
    runner._gateway_loop = object()
    module = types.ModuleType("gateway.run")
    module._gateway_runner_ref = weakref.ref(runner)
    monkeypatch.setitem(sys.modules, "gateway.run", module)

    assert channel.Gateway.ready()
    assert channel.Gateway.runner is runner


def test_no_gateway_outside_the_gateway_process():
    assert not channel.Gateway.ready()
