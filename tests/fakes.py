"""Stand-ins for Hermes: the plugin context, a gateway adapter, inbound events."""

import asyncio
import json
import threading

from senzu import channel, offers


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

    def inject_message(self, content, role="user", session_key=None):
        self.injected = (content, role, session_key)
        return True

    def call_mcp(self, server, tool, arguments, timeout=30):
        self.filed.append((server, tool, arguments))
        return {"ok": True, "result": f"Signalement reçu. Page de validation : {self.link}"}


class FakeAdapter:
    def __init__(self):
        self.sent = []

    async def send(self, chat_id, content, metadata=None):
        self.sent.append((chat_id, content))
        return type("SendResult", (), {"message_id": f"m{len(self.sent)}"})()


def _gateway(tmp_path, platform="telegram"):
    (tmp_path / "sessions").mkdir(exist_ok=True)
    (tmp_path / "sessions" / "sessions.json").write_text(
        json.dumps({"k": {"session_id": "h", "origin": {"platform": platform, "chat_id": "7"}}})
    )
    loop = asyncio.new_event_loop()
    threading.Thread(target=loop.run_forever, daemon=True).start()
    adapter = FakeAdapter()
    channel.Gateway.runner = type("Runner", (), {"adapters": {platform: adapter}})()
    channel.Gateway.loop = loop
    return adapter, loop


class _Inline:
    """Runs the thread's target at once, without the delay, so the test sees the send."""

    def __init__(self, target, args=(), kwargs=None, **_):
        self.target, self.args, self.kwargs = target, args, kwargs or {}

    def start(self):
        if self.target is offers.send_offer_later:
            where, text = self.args[:2]
            offers.remember_offer(where, channel.send(where, text))
        else:
            self.target(*self.args, **self.kwargs)


def _event(text, platform="telegram", chat_id="7"):
    source = type("Source", (), {"platform": platform, "chat_id": chat_id})()
    return type("Event", (), {"text": text, "source": source})()
