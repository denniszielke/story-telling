# syntax=docker/dockerfile:1
#
# Shopping Claw — a custom OpenClaw container (bring-your-own-container).
#
# This image bakes OpenClaw + the shopping-claw skill into a root filesystem
# that an Azure Container Apps Sandbox can boot from. OpenClaw is therefore
# ONLY ever executed *inside the sandbox* — never on the operator's machine.
#
# Build it remotely in Azure Container Registry (no local Docker required):
#
#     python scripts/build_narrator_image.py
#
# then convert + boot it with:
#
#     python src/agents/narrator/shopping_claw.py
#
FROM node:24-bookworm-slim

# OS packages OpenClaw + the gateway HTTP server need at runtime.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        git \
        jq \
        tini \
    && rm -rf /var/lib/apt/lists/*

# Install the OpenClaw gateway + agent runtime globally.
# Pinned via build arg so image builds are reproducible.
ARG OPENCLAW_VERSION=latest
RUN npm install -g "openclaw@${OPENCLAW_VERSION}" \
    && npm cache clean --force \
    && openclaw --version

# Bake the shopping-claw persona, default gateway config template, and the
# start script. Runtime secrets (provider key, gateway token) are injected by
# the orchestrator at boot time — never baked into the image.
WORKDIR /opt/shopping-claw
COPY skills/ /opt/shopping-claw/skills/
COPY openclaw.json /opt/shopping-claw/openclaw.template.json
COPY start-gateway.sh /usr/local/bin/start-shopping-claw
RUN chmod +x /usr/local/bin/start-shopping-claw

# The OpenClaw gateway HTTP server (canvas + A2UI host) listens here.
ENV OPENCLAW_GATEWAY_HOST=0.0.0.0 \
    OPENCLAW_GATEWAY_PORT=18789 \
    OPENCLAW_CONFIG_HOME=/root/.openclaw
EXPOSE 18789

# tini reaps zombies so the long-lived gateway behaves under a sandbox shell.
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["start-shopping-claw"]
