<div align="center">

# Senzu for Hermes Agent

**When your assistant gets stuck, the people who maintain it take over.**

[![CI](https://github.com/senzutech/hermes-plugin-senzu/actions/workflows/ci.yml/badge.svg)](https://github.com/senzutech/hermes-plugin-senzu/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/senzutech/hermes-plugin-senzu?sort=semver)](https://github.com/senzutech/hermes-plugin-senzu/releases)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Hermes Agent](https://img.shields.io/badge/Hermes%20Agent-plugin-7c3aed)](https://hermes-agent.nousresearch.com/docs/user-guide/features/plugins)
[![MCP](https://img.shields.io/badge/MCP-streamable%20HTTP-0ea5e9)](https://modelcontextprotocol.io)
[![Python](https://img.shields.io/badge/python-3.11%2B-3776ab)](pyproject.toml)

[Website](https://senzu.tech) · [Install](#installation) · [How it works](#how-it-works) · [Privacy](#privacy-and-security) · [Changelog](CHANGELOG.md)

</div>

---

AI assistants fail in a recognisable way: not with an error, but by trying the same thing
again and again while the owner waits. A model in that state does not stop to ask for help,
however it is instructed to. This plugin notices it for the model, and offers the owner a
one-tap handover to [Senzu](https://senzu.tech), the team that installed and maintains the
assistant.

It also puts a human in the loop before the handful of actions that cannot be taken back.

| | |
|---|---|
| 🛟 **Handover offer** | When one tool dominates the recent calls without progress, the owner gets a card with a button (Telegram) or a one-line offer (every other channel). |
| 🧾 **Dossier written for you** | On Telegram, the assistant's own model summarises what was tried, and the Senzu desk receives it only if the owner agrees. |
| 🚦 **Critical-action gate** | Mass deletion, payments, public posts, invoices… open Hermes' native approval prompt, warning first. |
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
✓ Carte Telegram (TELEGRAM_BOT_TOKEN)
```

<details>
<summary>What <code>hermes senzu setup</code> writes</summary>

The same configuration `hermes mcp add` and `hermes config set` would. The key stays in
`~/.hermes/.env`; `config.yaml` only refers to it.

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
      mcp_allowlist: [senzu]   # lets the plugin file the dossier itself
```

Options: `--key <key>` to set the key non-interactively, `--url <endpoint>` for another desk.

</details>

<details>
<summary>Pinning a version</summary>

```bash
hermes plugins install senzutech/hermes-plugin-senzu --ref <commit-sha> --enable
```

Releases are listed on the [releases page](https://github.com/senzutech/hermes-plugin-senzu/releases).
To update: `hermes plugins install senzutech/hermes-plugin-senzu --force --enable`.

</details>

## How it works

```text
 tool call ──► pre_tool_call ──► critical? ──► Hermes approval gate (warning, then offer)
     │
     ▼
 post_tool_call ──► record tool name + success, never the output (on disk, per session)
     │
 end of turn ──► transform_llm_output ──► stuck? ── no ──► reply unchanged
                                              │
                                             yes
                          ┌───────────────────┴────────────────────┐
                     Telegram                                any other channel
             reply unchanged, then a card:              offer appended to the reply:
     dossier ─► senzu_signaler ─► 🛟 [Confier à Senzu]    « répondez Senzu »
                                    (opens in Telegram)     ─► the model calls senzu_signaler
```

**"Stuck"** means one tool called at least 6 times *and* making up at least two fifths of the
last 40 calls, or two failures among the last 8 calls with the last one failing. The thresholds
were measured on real stuck sessions (the dominant tool was called 7, 9, 12 and 26 times) against
working ones (four tools sharing the load evenly). The offer is made once per series, and never
after the desk has been called.

**Critical actions** are rated on three axes (reversibility, who is affected, what is at stake).
The catalogue lives in [`guard.py`](guard.py); anything absent from it passes in silence.
Answering `[a]lways` at the gate mutes one family of actions (`senzu:fs-mass-delete`,
`senzu:payment`…), never all of them.

## Privacy and security

- **Tool outputs never leave the machine.** The plugin records a tool's name and whether it
  failed, nothing else.
- **Nothing reaches Senzu without consent.** The first time, the button opens the data-sharing
  notice; the dossier (objective, blocker, attempts, services involved) is only kept once the
  owner agrees. The desk also masks anything credential-shaped (API keys, JWTs, IBANs) before
  storing it.
- **Links cannot be guessed.** Consent and acceptance pages are reached by 128-bit random tokens
  that expire after 30 days, never by the public reference.
- **Accepting is a human act.** Work is only marked accepted when the owner clicks on the
  Senzu page; the plugin never calls `senzu_accepter`.

The plugin runs inside Hermes with its permissions. For a production install, have an
administrator give the plugin directory (`~/.hermes/plugins/senzu`) to root and make it read-only
for the Hermes user, so the assistant cannot rewrite its own guardrail.

Please report vulnerabilities privately, see [SECURITY.md](SECURITY.md).

## Compatibility

| Hermes Agent | Plugin | Notes |
|---|---|---|
| September 2026 builds and later | 0.1.x | needs `transform_llm_output`, `ctx.llm`, `ctx.call_mcp` |

Telegram cards need the gateway's `TELEGRAM_BOT_TOKEN`. Other channels (Discord, Slack,
WhatsApp, CLI…) get the text offer. Plugins are not loaded under `hermes serve` and
`hermes dashboard` ([hermes-agent#102592](https://github.com/NousResearch/hermes-agent/issues/102592)).

## Development

```bash
uvx ruff check . && uvx ruff format --check .
uvx --with pytest pytest -c tests/pytest.ini
```

The repository root is the plugin itself, which is what `hermes plugins install` expects; the
tests load it the way Hermes does.

## License

[MIT](LICENSE) © Senzu
