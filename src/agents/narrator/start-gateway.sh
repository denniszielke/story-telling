#!/usr/bin/env bash
#
# Render the OpenClaw gateway config from environment variables and start the
# gateway. This runs ONLY inside the Azure Container Apps Sandbox — OpenClaw is
# never executed on the operator's machine.
#
# The gateway serves the Shopping Claw canvas + A2UI surfaces on
# ${OPENCLAW_GATEWAY_PORT}:
#   /__openclaw__/canvas/   and   /__openclaw__/a2ui/
#
set -euo pipefail

# --- Defaults (overridable via env) -----------------------------------------
export OPENCLAW_GATEWAY_HOST="${OPENCLAW_GATEWAY_HOST:-0.0.0.0}"
export OPENCLAW_GATEWAY_PORT="${OPENCLAW_GATEWAY_PORT:-18789}"
export OPENCLAW_GATEWAY_AUTH_MODE="${OPENCLAW_GATEWAY_AUTH_MODE:-token}"
export OPENCLAW_GATEWAY_TOKEN="${OPENCLAW_GATEWAY_TOKEN:-}"
export OPENCLAW_MODEL="${OPENCLAW_MODEL:-gpt-5.4}"
export OPENCLAW_PROVIDER="${OPENCLAW_PROVIDER:-openai}"
export OPENCLAW_PROVIDER_API_KEY_ENV="${OPENCLAW_PROVIDER_API_KEY_ENV:-OPENAI_API_KEY}"
export OPENCLAW_CONFIG_HOME="${OPENCLAW_CONFIG_HOME:-$HOME/.openclaw}"

TEMPLATE="/opt/shopping-claw/openclaw.template.json"
CONFIG="${OPENCLAW_CONFIG_HOME}/openclaw.json"

mkdir -p "${OPENCLAW_CONFIG_HOME}"

# Render ${VAR} placeholders from the environment using node (always present in
# this image). Avoids relying on envsubst being installed.
node -e '
  const fs = require("fs");
  const src = fs.readFileSync(process.argv[1], "utf8");
  const out = src.replace(/\$\{([A-Z0-9_]+)\}/g, (_, name) => {
    const v = process.env[name];
    if (v === undefined) {
      console.error(`Missing env var for template placeholder: ${name}`);
      process.exit(1);
    }
    return v;
  });
  fs.writeFileSync(process.argv[2], out);
' "${TEMPLATE}" "${CONFIG}"

echo "🦞 Shopping Claw gateway config rendered to ${CONFIG}"
echo "   bind:     ${OPENCLAW_GATEWAY_HOST}:${OPENCLAW_GATEWAY_PORT}"
echo "   auth:     ${OPENCLAW_GATEWAY_AUTH_MODE}"
echo "   provider: ${OPENCLAW_PROVIDER} (key via \$${OPENCLAW_PROVIDER_API_KEY_ENV})"
echo "   canvas:   /__openclaw__/canvas/"
echo "   a2ui:     /__openclaw__/a2ui/"

exec openclaw gateway
