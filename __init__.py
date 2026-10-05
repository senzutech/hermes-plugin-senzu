"""Senzu for Hermes Agent: the technicians who maintain this assistant, one request away.

What Hermes expects of a plugin, and nothing else:

* the Senzu MCP server is declared the way ``hermes mcp add`` declares any other, and the
  ``senzu`` skill is installed the way ``hermes skills install`` installs any other: the skill
  tells the assistant when to hand a problem over and how (``hermes senzu setup`` does both);
* ``pre_tool_call``: before a critical action (mass deletion, payment, public post…), Hermes'
  own approval prompt opens with the risk first, then the option of having Senzu do it;
* ``post_tool_call``: once a handover is filed, news of it reaches the owner's chat, and Senzu's
  maintenance access opens while the paid work is in progress (see ``news`` and ``access``).

See README.md for installation.
"""

from __future__ import annotations

from . import channel, cli, guard, news


def on_tool_call(tool_name="", args=None, **_):
    rule = guard.assess(tool_name, args)
    return guard.approval(rule) if rule is not None else None


def on_tool_result(tool_name="", session_id="", status="", **_):
    # A handover filed: from now on the owner hears, in this chat, when Senzu moves on it.
    if "senzu_signaler" in (tool_name or "") and status not in ("error", "blocked"):
        news.activate(channel.origin(session_id))


def register(ctx):
    news.start(ctx)
    ctx.register_hook("pre_tool_call", on_tool_call)
    ctx.register_hook("post_tool_call", on_tool_result)
    ctx.register_cli_command(
        name="senzu",
        help="Connect to the Senzu desk and check the installation",
        setup_fn=cli.setup_parser,
        handler_fn=cli.handle,
    )
