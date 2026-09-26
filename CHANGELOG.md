# Changelog

All notable changes to this plugin are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.1.0] - 2026-09-26

### Added

- Handover offer when the assistant keeps hammering at one tool or keeps failing, on every
  channel through the Hermes gateway.
- Two handover modes: `ask` (default, nothing sent until the owner answers) and `auto` (the
  installation's own model writes the dossier, the plugin files it over MCP and sends the
  approval link).
- Offer after Hermes' own loop guardrail halts a turn, sent through the gateway after Hermes'
  halt message.
- On the gateway the offer follows the reply as its own message; on Telegram it carries a
  one-tap **🛟 Confier à Senzu** keyboard button, whose tap arrives as an ordinary message.
- The owner's one-word « Senzu » to an open offer (24 h) is rewritten into an explicit handover
  request before it reaches the model, which otherwise may not know an offer was made.
- Per-installation settings, `threshold` (default 6) and `handover`, read on every reply;
  changed with `hermes senzu setup` or `hermes config set`.
- Critical-action gate on Hermes' native approval prompt, with per-family `rule_key`s.
- `hermes senzu setup` to connect the Senzu MCP server and pick the mode, `hermes senzu doctor`
  to check the installation.

[Unreleased]: https://github.com/senzutech/hermes-plugin-senzu/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/senzutech/hermes-plugin-senzu/releases/tag/v0.1.0
