# Changelog

All notable changes to this plugin are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.1.0] - 2026-09-26

### Added

- Handover offer when the assistant keeps hammering at one tool or keeps failing: a Telegram
  card whose button opens the Senzu page as a Mini App, or a one-line offer on other channels.
- Dossier written by the installation's own model and filed with the Senzu desk over MCP, only
  shown to Senzu once the owner consents.
- Critical-action gate on Hermes' native approval prompt, with per-family `rule_key`s.
- `hermes senzu setup` to connect the Senzu MCP server, `hermes senzu doctor` to check the
  installation.

[Unreleased]: https://github.com/senzutech/hermes-plugin-senzu/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/senzutech/hermes-plugin-senzu/releases/tag/v0.1.0
