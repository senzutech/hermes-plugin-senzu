# Changelog

All notable changes to this plugin are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.3.1] - 2026-10-05

### Changed

- The assistant is told to announce an estimate by the rule published in `senzu://tarifs`, to
  fill the facts it prices (`nature`, `serveur`, `cause_inconnue`, `irreversible`, `tiers`) when
  filing, and not to offer Senzu for a one-off personal errand (a flight, a room).

## [0.3.0] - 2026-10-05

### Changed

- Senzu is offered when the assistant cannot do something, as it says in its own reply, no
  longer from counting tool calls. Measured on two installations' real conversations (22
  sessions, 374 turns): counting found nothing worth an offer, while every moment Senzu was
  needed was an admission of a missing access (« la connexion Gmail n'est pas encore faite »,
  « mon accès à Artinove est en lecture seule », « un filtre anti-robot »).
- `threshold` and `read_only_tools` are gone, with the counting they tuned; a config that still
  has them reads fine.

### Added

- `pre_llm_call`: the assistant is told Senzu exists, how much it costs (`senzu://tarifs`) and
  when to offer it, at the start of a session and every 15 turns.
- The owner asking for a human (« Senzu », support, a technician, « je passe le relais ») is
  taken at their word every time, never rationed.
- Automatic offers are rationed: once a day per missing access, two a day at most per chat,
  shared with the offers on irritation and on Hermes' loop guardrail.
- The installation steps tell the owner they can ask for Senzu at any time.

## [0.2.2] - 2026-09-30

### Fixed

- False offers in production, on scheduled jobs that were working (a morning brief of 15 varied
  calls; a regulatory watch of 8 web searches on different questions and an extract):
  - scheduled jobs (cron) and webhooks are never evaluated nor offered anything;
  - only identical calls (same tool, same arguments, compared by a fingerprint, the arguments
    themselves never kept) count as repetition; different arguments are research;
  - tools that only read or search never count: a built-in list, MCP tools declared
    `readOnlyHint`, names starting with a reading verb, and the installation's own
    `read_only_tools`;
  - a turn that ends on a substantial answer is never interrupted.

### Changed

- senzu-access is presented as strongly recommended, not optional: without it Senzu's
  technicians cannot work on the machine. The agent's installation steps say not to skip it,
  and `hermes senzu doctor` warns when it is missing.

### Added

- Handover when the owner has had enough: the installation's own model reads each message the
  owner writes for irritation or discouragement aimed at the assistant (one short structured
  call, on the owner's tokens). Two in a row within two hours, and the offer follows the next
  reply. Setting `mood` (`on` by default), `hermes senzu setup --mood on|off`, shown by `doctor`.

### Changed

- When the owner accepts an offer, the assistant first shows what it is about to send and asks
  whether to add anything, then files the handover with the owner's own words in it.

## [0.2.1] - 2026-09-27

### Added

- `hermes senzu doctor` shows whether Senzu's maintenance access is installed, and open or
  closed.
- README: installation steps an agent can follow on its own, maintenance access included, with
  the owner's explicit agreement.

## [0.2.0] - 2026-09-27

### Added

- News of open handovers (payment received, validation, Senzu's messages, refunds) relayed to
  the owner's chat, by asking the desk at the pace it sets, only while a handover is open.
- Maintenance access: where [senzu-access](https://github.com/senzutech/senzu-access) is
  installed, the plugin asks for Senzu's SSH access to open while a paid handover is in
  progress and to close when it is done, reports each change to the desk (host, port, host key
  fingerprint) and tells the owner. The plugin needs no elevated rights.

### Changed

- After a gateway restart, news and the maintenance access are followed right away, without
  waiting for the owner's next message: the running gateway is found the way Hermes' own
  `send_message` tool finds it.
- `handover.py` split into `home`, `history`, `channel`, `offers` and `handover`, one subject
  each. No behaviour change.

## [0.1.0] - 2026-09-26

### Added

- Handover offer when the assistant keeps hammering at one tool or keeps failing, on every
  channel through the Hermes gateway.
- Two handover modes: `ask` (default, nothing sent until the owner answers) and `auto` (the
  installation's own model writes the dossier, the plugin files it over MCP and sends the
  approval link).
- Offer after Hermes' own loop guardrail halts a turn, sent through the gateway after Hermes'
  halt message.
- On the gateway the offer follows the reply as its own message. On Telegram the owner accepts
  it with a 👍 (or ✅, ❤️…) on that message, which resumes the conversation through
  `ctx.inject_message`; typing « Senzu » works everywhere.
- The owner's one-word « Senzu » to an open offer (24 h) is rewritten into an explicit handover
  request before it reaches the model, which otherwise may not know an offer was made.
- Per-installation settings, `threshold` (default 6) and `handover`, read on every reply;
  changed with `hermes senzu setup` or `hermes config set`.
- Critical-action gate on Hermes' native approval prompt, with per-family `rule_key`s.
- `hermes senzu setup` to connect the Senzu MCP server and pick the mode, `hermes senzu doctor`
  to check the installation.

[Unreleased]: https://github.com/senzutech/hermes-plugin-senzu/compare/v0.3.1...HEAD
[0.3.1]: https://github.com/senzutech/hermes-plugin-senzu/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/senzutech/hermes-plugin-senzu/compare/v0.2.2...v0.3.0
[0.2.2]: https://github.com/senzutech/hermes-plugin-senzu/compare/v0.2.1...v0.2.2
[0.2.1]: https://github.com/senzutech/hermes-plugin-senzu/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/senzutech/hermes-plugin-senzu/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/senzutech/hermes-plugin-senzu/releases/tag/v0.1.0
