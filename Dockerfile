# Single-port Reflex image: one process serves the compiled frontend, the
# websocket and /_upload on $PORT. This matches Cloud Run (one port per
# container) and `reflex run --env prod --single-port` locally.
#
# Single stage on purpose: `reflex run --env prod` always recompiles and
# rebuilds the frontend at startup, so node/bun must exist at runtime. The
# build-time export below pre-installs frontend dependencies so that startup
# rebuild only takes a few seconds.
FROM python:3.14-slim

# unzip/curl are needed by Reflex to install bun
RUN apt-get update && apt-get install -y --no-install-recommends \
    unzip \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy pre-built Node 22 LTS directly from the official Node image
COPY --from=node:22-slim /usr/local/bin/node /usr/local/bin/
COPY --from=node:22-slim /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -s /usr/local/lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PORT=8080 \
    PATH="/app/.venv/bin:$PATH"

# Install Python requirements (cached unless requirements.txt changes)
RUN python -m venv /app/.venv
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && pip install --no-cache-dir -r requirements.txt

# Copy the application
COPY rxconfig.py .
COPY assets/ ./assets/
COPY pinion_reflex_agent/ ./pinion_reflex_agent/
COPY pinionai_extensions.py .
COPY mcp_server/ ./mcp_server/

# Initialize .web, install bun + node_modules and do one production build now,
# so container startup reuses them instead of downloading anything.
RUN reflex export --frontend-only --no-zip --env prod

EXPOSE 8080

# Do NOT set REDIS_URL: the PinionAI client lives in process memory and cannot
# be pickled, so the app must run as a single backend worker (Reflex uses one
# worker when Redis is absent). Scale with Cloud Run instances + session affinity.
CMD ["sh", "-c", "reflex run --env prod --single-port --frontend-port ${PORT}"]
