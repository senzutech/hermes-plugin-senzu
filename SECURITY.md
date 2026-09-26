# Security policy

## Supported versions

Only the latest release receives security fixes.

## Reporting a vulnerability

Please do not open a public issue. Use GitHub's
[private vulnerability reporting](https://github.com/senzutech/hermes-plugin-senzu/security/advisories/new)
or write to security@senzu.tech. We acknowledge reports within two working days and aim to ship
a fix within fourteen.

## Scope

In scope: this plugin, and how it handles tool results, the dossier, the Telegram bot token and
the Senzu API key. The Senzu desk itself (MCP server and pages) is in scope too; report it here.

Out of scope: Hermes Agent itself (report to
[NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent/security)), and an
assistant that already has shell access disabling the plugin through its own configuration,
which the README documents as a known limit.
