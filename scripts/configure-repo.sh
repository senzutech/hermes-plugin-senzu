#!/usr/bin/env bash
# One-off: repository metadata, so it is discoverable the way Hermes plugins are.
set -euo pipefail
repo=senzutech/hermes-plugin-senzu
gh repo edit "$repo" \
  --description "Hermes Agent plugin: hands a stuck assistant over to the people who maintain it, and gates critical actions." \
  --homepage "https://senzu.tech" \
  --enable-issues --enable-wiki=false --delete-branch-on-merge \
  --add-topic hermes-agent --add-topic hermes-plugin --add-topic nous-research \
  --add-topic mcp --add-topic model-context-protocol --add-topic ai-agents \
  --add-topic human-in-the-loop --add-topic guardrails --add-topic maintenance \
  --add-topic managed-services
gh api -X PUT "repos/$repo/private-vulnerability-reporting" >/dev/null
echo "configured $repo"
