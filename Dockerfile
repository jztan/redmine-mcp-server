# Multi-stage Docker build for the Redmine MCP Server
FROM python:3.13-slim@sha256:70729b46c69b4f1e97c4822c1af3df53a1476cf5ddc6c087c0c10bc3a5678c2f AS builder

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_CACHE_DIR=/opt/uv-cache

# Install uv package manager
COPY --from=ghcr.io/astral-sh/uv@sha256:10787c682e4184e4f290de1171fd4703dc63de99221f10fe1c99002ce7fa9acc /uv /usr/local/bin/uv

# Create and set working directory
WORKDIR /app

# Copy dependency files and source code for installation
COPY pyproject.toml uv.lock ./
COPY src/ ./src/
COPY README.md ./

# Install the locked production dependencies and project in a virtual environment
RUN UV_PROJECT_ENVIRONMENT=/opt/venv \
    uv sync --locked --no-dev --no-editable && \
    rm -rf \
        /usr/local/lib/python3.13/site-packages/pip* \
        /usr/local/lib/python3.13/site-packages/setuptools* \
        /usr/local/lib/python3.13/ensurepip \
        /usr/local/bin/pip*

# Production stage
FROM python:3.13-slim@sha256:70729b46c69b4f1e97c4822c1af3df53a1476cf5ddc6c087c0c10bc3a5678c2f AS runtime

ARG VCS_REF=unknown
LABEL org.opencontainers.image.revision="$VCS_REF"

# Set environment variables
# SERVER_HOST/SERVER_PORT default to a reachable binding so ad-hoc
# `docker run` works without a full env file; override via env_file or -e.
# FASTMCP_HOME points at /app/data so oauth-proxy state (client
# registrations, upstream tokens) lands on the mounted volume instead of
# the container filesystem, where a rebuild would discard it.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    SERVER_HOST=0.0.0.0 \
    SERVER_PORT=8000 \
    FASTMCP_HOME=/app/data/fastmcp

# Install system dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        ca-certificates && \
    rm -rf /var/lib/apt/lists/* && \
    rm -rf \
        /usr/local/lib/python3.13/site-packages/pip* \
        /usr/local/lib/python3.13/site-packages/setuptools* \
        /usr/local/lib/python3.13/ensurepip \
        /usr/local/bin/pip*

# Create non-root user
RUN groupadd --gid 1000 appuser && \
    useradd --uid 1000 --gid appuser --shell /bin/bash --create-home appuser

# Copy virtual environment from builder stage
COPY --from=builder --chown=appuser:appuser /opt/venv /opt/venv

# Set working directory
WORKDIR /app

# Copy application code
COPY --chown=appuser:appuser src/ ./src/
COPY --chown=appuser:appuser README.md ./

# Create directories for writable persistent data. The attachment volume is
# mounted over this path in production; creating it in the image lets Docker
# initialize a new named volume with appuser ownership instead of root.
RUN mkdir -p /app/attachments /app/logs /app/data /app/data/fastmcp && \
    chown -R appuser:appuser /app

# Switch to non-root user
USER appuser

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD ["python", "-c", "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.getenv(\"SERVER_PORT\", \"8000\")}/health', timeout=5)"]

STOPSIGNAL SIGTERM

# Expose default port (informational only; override with SERVER_PORT env var)
EXPOSE 8000

# Default command
CMD ["redmine-mcp-server"]
