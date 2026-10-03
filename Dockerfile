# One image for both the API server and the workers (different commands in docker-compose.yml).

# GitHub's official MCP server is a static Go binary; copy it out of their image.
FROM ghcr.io/github/github-mcp-server:latest AS github-mcp

FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

COPY --from=github-mcp /server/github-mcp-server /usr/local/bin/github-mcp-server

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .

COPY alembic.ini ./
COPY migrations ./migrations
COPY benchmark ./benchmark
COPY sandbox ./sandbox

ENV REDTOGREEN_ROOT=/app \
    GITHUB_MCP_MODE=binary \
    PYTHONUNBUFFERED=1

EXPOSE 8000
CMD ["redtogreen", "serve"]
