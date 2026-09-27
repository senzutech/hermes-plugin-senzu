<div align="center">

# Senzu for Hermes Agent

**Call in your maintenance experts when your assistant cannot cope on its own.**

[![CI](https://github.com/senzutech/hermes-plugin-senzu/actions/workflows/ci.yml/badge.svg)](https://github.com/senzutech/hermes-plugin-senzu/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/senzutech/hermes-plugin-senzu?sort=semver)](https://github.com/senzutech/hermes-plugin-senzu/releases)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Hermes Agent](https://img.shields.io/badge/Hermes%20Agent-plugin-7c3aed)](https://hermes-agent.nousresearch.com/docs/user-guide/features/plugins)
[![MCP](https://img.shields.io/badge/MCP-streamable%20HTTP-0ea5e9)](https://modelcontextprotocol.io)
[![Python](https://img.shields.io/badge/python-3.11%2B-3776ab)](pyproject.toml)

[Website](https://senzu.tech) · [Install](#installation) · [How it works](#how-it-works) · [Privacy](#privacy-and-security) · [Changelog](CHANGELOG.md)

</div>

---

[Senzu](https://senzu.tech) is a paid maintenance service for businesses that run a Hermes
assistant. This plugin is how its customers call on it: you install it because you want experts
to take over from time to time, when the assistant (or you) cannot get something done alone.

AI assistants get stuck in a recognisable way: not with an error, but by trying the same thing
again and again while you wait. A model in that state does not stop to ask for help, however it
is instructed to. The plugin notices it for the model and offers to hand the problem over to
your Senzu experts. It also puts you in the loop before the handful of actions that cannot be
taken back, with the option of having Senzu do them for you.

| | |
|---|---|
| 🛟 **Handover when stuck** | When one tool dominates the recent calls without progress, you are offered to hand over, or it is handed over directly if you chose so. |
| 🧾 **A dossier, not a transcript** | Senzu receives a summary: objective, blocker, what was tried, services involved. Never the conversation, never your files. |
| 🚦 **Critical-action gate** | Mass deletion, payments, public posts, invoices… open Hermes' native approval prompt: the risk first, then the choice to do it now or have Senzu do it. |
| 🔔 **Kept informed** | While a handover is open, the plugin asks Senzu for news and tells you in your usual chat: payment received, work done, Senzu's messages. No public address or open port needed. |
| 🔐 **Maintenance access, only when needed** | With the optional [senzu-access](https://github.com/senzutech/senzu-access) tool, Senzu's SSH access opens when a paid handover starts and closes when it is done. You are told each time. |
| 📡 **Every channel** | Everything goes through the Hermes gateway: Telegram, WhatsApp, Discord, Slack, email, CLI. |
| 🔒 **No model judgement** | Every decision is arithmetic on tool calls. The model is never asked whether it is stuck or whether an action is dangerous. |

## Installation

Requires [Hermes Agent](https://github.com/NousResearch/hermes-agent) and an installation key
from Senzu.

```bash
hermes plugins install senzutech/hermes-plugin-senzu --enable   # asks for SENZU_API_KEY
hermes senzu setup                                               # connects the Senzu MCP server
hermes gateway restart
```

Check everything is in place:

```bash
hermes senzu doctor
```

```text
✓ Plugin activé
✓ Clé SENZU_API_KEY
✓ Serveur MCP senzu déclaré
✓ Accès du plugin au MCP
✓ Réponse par réaction 👍
• Reprise par Senzu : sur votre accord, offre après 6 appels
```

### Settings

Two settings per installation, read on every reply: a change applies from the next reply,
without restarting anything.

| Setting | Default | Meaning |
|---|---|---|
| `threshold` | `6` | Calls to one same tool, without progress, before Senzu is offered. From 3 to 50. Raise it to be offered help less often. |
| `handover` | `ask` | `ask` or `auto`, see below. |

Change them in any of three ways, which all write `plugins.entries.senzu` in `config.yaml`:

```bash
hermes senzu setup --threshold 10 --handover auto      # only what you pass is changed
hermes config set plugins.entries.senzu.threshold 10
```

The defaults suit most installations; there is nothing to configure to get started.

### Handover mode

| `hermes senzu setup --handover …` | When the assistant is stuck |
|---|---|
| `ask` (default) | The offer follows the reply. Answer with a 👍 (or ✅, ❤️) on it on Telegram, or type « Senzu » anywhere. Nothing is sent to Senzu until you do; the plugin turns your answer into an explicit request, and the assistant files the handover itself. |
| `auto` | You decided once that Senzu may step in. The plugin writes the dossier with your assistant's model, files it, and sends you the link to approve the work. Nothing is done before you click. |

<details>
<summary>What <code>hermes senzu setup</code> writes</summary>

The same configuration `hermes mcp add` and `hermes config set` would. The key stays in the
Hermes environment file; `config.yaml` only refers to it.

```yaml
mcp_servers:
  senzu:
    url: https://senzu.cr.edouard.cl/mcp
    headers:
      Authorization: Bearer ${SENZU_API_KEY}
    connect_timeout: 30
    enabled: true
plugins:
  entries:
    senzu:
      mcp_allowlist: [senzu]   # lets the plugin file the dossier itself (auto mode)
      allow_gateway_injection: true   # lets a 👍 on the offer resume the conversation
      handover: ask            # or auto, only if you pass --handover
      threshold: 6             # only if you pass --threshold
```

Options: `--key <key>` to set the key non-interactively, `--url <endpoint>` for another desk,
`--threshold <n>`, `--handover ask|auto`. Running `setup` again only changes what you pass.

</details>

<details>
<summary>Pinning a version</summary>

```bash
hermes plugins install senzutech/hermes-plugin-senzu --ref v0.2.0 --enable
```

Releases are listed on the [releases page](https://github.com/senzutech/hermes-plugin-senzu/releases).
To update: `hermes plugins install senzutech/hermes-plugin-senzu --force --enable`.

</details>

## How it works

```text
 tool call ──► pre_tool_call ──► critical? ──► Hermes approval gate (risk, then "or have Senzu do it")
     │
     ▼
 post_tool_call ──► record tool name + success, never the output (on disk, per session)
     │
 end of turn ──► transform_llm_output ──► stuck? ── no ──► reply unchanged
                                              │
                                             yes
                          ┌───────────────────┴────────────────────┐
                        ask                                       auto
         offer appended to the reply              notice appended to the reply, then
         « répondez Senzu »                       dossier ─► senzu_signaler ─► link sent
            └─► you answer ─► senzu_signaler           through the gateway ─► you approve
```

**"Stuck"** means one tool called at least `threshold` times (6 by default) *and* making up at
least two fifths of the last 40 calls, or two failures among the last 8 calls with the last one
failing. It also means **Hermes' own loop guardrail halted the turn** (on a gateway, Hermes stops
five identical calls in a row): the offer then follows Hermes' halt message, always in `ask`
form, since a dossier written from a turn cut short would be thin. The thresholds
were measured on real stuck sessions (the dominant tool was called 7, 9, 12 and 26 times) against
working ones (four tools sharing the load evenly). The offer is made once per series, and never
after the desk has been called.

**News** of a handover reach you without any open port: after a handover is filed, the plugin
asks the Senzu desk for news (one call per installation, however many handovers), at the pace
the desk sets: two minutes after something happened, up to half an hour when it goes quiet, at most
five minutes while Senzu is working on the machine, and not at all once nothing is open. After a
gateway restart it picks up at once, without waiting for your next message. What changed is sent to the chat the handover came from.

**Critical actions** are rated on three axes (reversibility, who is affected, what is at stake).
The catalogue lives in [`guard.py`](guard.py); anything absent from it passes in silence.
Answering `[a]lways` at the gate mutes one family of actions (`senzu:fs-mass-delete`,
`senzu:payment`…), never all of them.

## Maintenance access

To let Senzu work on the machine itself (install a language runtime, Docker, a headless
browser…), an administrator installs [senzu-access](https://github.com/senzutech/senzu-access)
once. It creates a `senzu` account reached only with Senzu's SSH key, closed by default. From
then on this plugin asks for it to be opened while a paid handover is in progress and closed when
the handover is done, by writing one word to a request file; the system applies it. The plugin
itself has no elevated rights. Each opening and closing is reported to you in your chat and
recorded in the handover's trail on Senzu's side.

Without senzu-access, everything else works; Senzu then asks you for another way in when an
intervention needs one.

## For agents

### Installing this plugin for your owner

When your owner asks you to install Senzu, do it yourself with your terminal tool, step by step,
and stop at the first step that fails to tell them what it printed.

1. Get the installation key from your owner (Senzu gives it to them, it starts with `szk_live_`). Never
   invent one, never write it anywhere but the command below, never repeat it in the chat.
2. Install and connect:

   ```bash
   hermes plugins install senzutech/hermes-plugin-senzu --ref v0.2.0 --enable
   hermes senzu setup --key <key>
   ```

   If the plugin is already installed, add `--force` to the first command.
3. The gateway you are running in must restart to load the plugin, and you cannot restart it
   from inside a conversation. Ask your owner to type `/restart`, then wait for their next
   message.
4. After the restart, run `hermes senzu doctor` and show your owner its output. Every line
   should start with ✓.
5. Optional, Senzu's maintenance access. It needs root, which you do not have: give your owner
   (or their administrator) these commands to run themselves, and do not try to run them:

   ```bash
   curl -fsSLO https://github.com/senzutech/senzu-access/releases/latest/download/senzu-access-setup.sh
   curl -fsSLO https://github.com/senzutech/senzu-access/releases/latest/download/senzu-access-setup.sh.sha256
   sha256sum -c senzu-access-setup.sh.sha256
   sudo bash senzu-access-setup.sh
   ```

Then tell your owner, in one or two sentences, that Senzu is ready: when you get stuck, you
will offer to hand the problem over, and nothing is sent without their agreement.

### Settings

These settings are the owner's business, changed from the command line. If the owner explicitly
asks you to change them, run `hermes senzu setup --threshold <n>` or
`hermes senzu setup --handover ask|auto` (only what you pass changes; no restart needed) and say
what you changed. Never bring them up yourself, and never discuss them when the owner answers
« Senzu »: that answer means hand the problem over, by calling `senzu_signaler`.

## Privacy and security

- **Tool outputs never leave the machine.** The plugin records a tool's name and whether it
  failed, nothing else.
- **You decide when Senzu hears about a problem.** In `ask` mode, nothing is sent until you
  answer. In `auto` mode, a dossier is sent as soon as the assistant is stuck, because that is
  what you chose at setup.
- **Nothing reaches Senzu without consent.** The first time, the link opens the data-sharing
  notice; the dossier is only kept once you agree. The desk also masks anything
  credential-shaped (API keys, JWTs, IBANs) before storing it.
- **Work only starts when you click.** Links are 128-bit random tokens that expire after 30
  days, and the plugin never accepts work on your behalf.
- **Messages go through your gateway.** The plugin never talks to a messaging platform directly
  and needs no bot token.

The plugin runs inside Hermes with its permissions. For a production install, have an
administrator give the plugin directory (`~/.hermes/plugins/senzu`) to root and make it read-only
for the Hermes user, so the assistant cannot rewrite its own guardrail.

Please report vulnerabilities privately, see [SECURITY.md](SECURITY.md).

## Compatibility

| Hermes Agent | Plugin | Notes |
|---|---|---|
| September 2026 builds and later | 0.1.x, 0.2.x | needs `transform_llm_output`, `pre_gateway_dispatch`, `on_session_end`, `gateway_platform_event`, `ctx.inject_message`, `ctx.llm`, `ctx.call_mcp` |

Outside the gateway (`hermes chat`), `auto` mode falls back to asking. Plugins are not loaded
under `hermes serve` and `hermes dashboard`
([hermes-agent#102592](https://github.com/NousResearch/hermes-agent/issues/102592)).

## Development

```bash
uvx ruff check . && uvx ruff format --check .
uvx --with pytest pytest -c tests/pytest.ini
```

The repository root is the plugin itself, which is what `hermes plugins install` expects; the
tests load it the way Hermes does. One module per subject:

| Module | Subject |
|---|---|
| `__init__.py` | Hook registration |
| `stuck.py` | Reading a session: is the assistant stuck? |
| `offers.py` | The offer and the owner's answer (« Senzu », a reaction) |
| `handover.py` | Auto mode: the dossier, filing it with the desk |
| `channel.py` | The running gateway, sending to the owner |
| `news.py` | Asking the desk for news while a handover is open |
| `access.py` | Senzu's maintenance access, through senzu-access |
| `guard.py` | Critical-action gate |
| `history.py`, `home.py`, `settings.py` | Recorded calls, paths, per-installation settings |
| `cli.py` | `hermes senzu setup` and `doctor` |

## License

[MIT](LICENSE) © Senzu
