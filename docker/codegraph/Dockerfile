# CodeGraph F0 baseline, pinned. Upstream is never modified (CLAUDE.md).
# node:sqlite is unflagged from 22.13; 22.12 fails at init. Multi-arch: node:22 official image ships arm64 (macOS) and amd64 (WSL2/Linux).
# Build:  docker build -t evalh/codegraph:f72c9d2 docker/codegraph
FROM node:22.23-bookworm-slim

ARG CODEGRAPH_SHA=f72c9d2efb14454ff4f9fd7b8460abd82f19a287

RUN apt-get update \
 && apt-get install -y --no-install-recommends git ca-certificates \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/codegraph
RUN git init -q . \
 && git remote add origin https://github.com/colbymchenry/codegraph.git \
 && git fetch -q --depth 1 origin "$CODEGRAPH_SHA" \
 && git checkout -q FETCH_HEAD \
 && test "$(git rev-parse HEAD)" = "$CODEGRAPH_SHA" \
 && npm ci --no-audit --no-fund \
 && npm run build \
 && npm link \
 && rm -rf .git

# No telemetry, no watcher, no update check traffic leaves a --network none container anyway.
ENV CODEGRAPH_TELEMETRY=0 \
    CODEGRAPH_NO_WATCH=1

WORKDIR /repo
ENTRYPOINT ["codegraph"]
