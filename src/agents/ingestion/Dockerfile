# syntax=docker/dockerfile:1
#
# Ingestion agent — bring-your-own-container image for Azure Container Apps Sandboxes.
#
# Bakes the skill-driven ingestion agent + its dependencies into a root filesystem
# that a sandbox can boot from. The agent is never run on the operator's machine —
# the launcher (scripts/run_ingestion_sandbox.py) converts this image into a private
# disk image, boots a sandbox per URL, and execs:
#
#     python -m src.agents.ingestion.ingestion_agent --url <url>
#
# Build it remotely in Azure Container Registry (no local Docker required):
#
#     python scripts/build_ingestion_image.py
#
FROM python:3.13-slim

WORKDIR /app

# OS packages: git is handy for repo inspection; ca-certificates for HTTPS.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates git \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps first for better layer caching.
COPY ./src/agents/ingestion/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# Copy the whole src tree so the agent can import src.content.* and src.agents.*
# and load the prompt templates under src/prompts/.
COPY ./src /app/src

# Authenticate as the user-assigned managed identity injected at sandbox boot.
# AZURE_CLIENT_ID is provided by the launcher; DefaultAzureCredential picks it up.
ENV PYTHONUNBUFFERED=1

# Default command processes a URL passed via INGESTION_URL; the launcher usually
# execs the module directly with --url, so this is a convenience fallback.
CMD ["sh", "-c", "python -m src.agents.ingestion.ingestion_agent --url \"$INGESTION_URL\""]
