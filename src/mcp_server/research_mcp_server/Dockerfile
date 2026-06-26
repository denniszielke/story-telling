FROM python:3.13-slim

WORKDIR /app

COPY ./src/mcp_server/research_mcp_server/requirements.txt /tmp/requirements.txt
RUN if [ -f /tmp/requirements.txt ]; then \
        pip install --no-cache-dir -r /tmp/requirements.txt; \
    else \
        echo "No requirements.txt found"; \
    fi

COPY ./src /app/src

# Bind to all interfaces inside the container so Container Apps can route traffic.
ENV RESEARCH_MCP_HOST=0.0.0.0
ENV RESEARCH_MCP_PORT=8000
ENV RESEARCH_MCP_PATH=/mcp

EXPOSE 8000

CMD ["python", "-m", "src.mcp_server.research_mcp_server.server"]
