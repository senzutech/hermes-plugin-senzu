"""The hooks end to end, with a fake Hermes: what the owner would actually read."""

import senzu
from senzu import handover


class FakeContext:
    def __init__(self):
        self.hooks, self.commands = {}, {}

    def register_hook(self, name, callback):
        self.hooks[name] = callback

    def register_cli_command(self, name, **kwargs):
        self.commands[name] = kwargs


def test_register_wires_every_hook_and_the_command(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    ctx = FakeContext()
    senzu.register(ctx)
    assert set(ctx.hooks) == {
        "pre_tool_call",
        "post_tool_call",
        "transform_llm_output",
        "post_llm_call",
    }
    assert "senzu" in ctx.commands


def test_a_hammering_session_gets_the_text_offer_once(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    for _ in range(7):
        senzu.on_tool_result(tool_name="terminal", session_id="s", status="ok")
    reply = senzu.on_reply(response_text="Je réessaie.", session_id="s", platform="cli")
    assert reply.startswith("Je réessaie.\n\n---\n[Senzu]")
    assert "7 fois" in reply and "« Senzu »" in reply
    assert senzu.on_reply(response_text="Encore.", session_id="s", platform="cli") is None


def test_honest_work_is_left_alone(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    for tool in ["terminal", "read_file", "terminal", "search_files"]:
        senzu.on_tool_result(tool_name=tool, session_id="s", status="ok")
    assert senzu.on_reply(response_text="Fait.", session_id="s", platform="cli") is None


def test_history_survives_on_disk(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    senzu.on_tool_result(tool_name="terminal", session_id="s/../x", status="error")
    assert [c.tool for c in handover.load("s/../x")] == ["terminal"]
    assert not any(p.name.startswith("..") for p in (tmp_path / "cache" / "senzu").iterdir())


def test_critical_calls_go_to_the_gate():
    assert senzu.on_tool_call(tool_name="terminal", args={"command": "rm -rf /"})["action"] == (
        "approve"
    )
    assert senzu.on_tool_call(tool_name="read_file", args={"path": "a"}) is None
