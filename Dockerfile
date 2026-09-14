# syntax=docker/dockerfile:1.7
#
# Two images from one file:
#   --target web   the website: Next.js server, public, talks to the bot over the compose network
#   --target bot   the Discord bot with its internal API, Chromium and the chart database

# ---------------------------------------------------------------- website
# The Next.js build runs once on the runner's own platform: its compiler crashes under
# emulation, and the standalone output it produces is plain JavaScript that runs anywhere.
FROM --platform=$BUILDPLATFORM node:22-alpine AS webbuild
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN --mount=type=cache,target=/root/.npm,sharing=locked \
    npm ci --no-audit --no-fund
COPY web/ ./
RUN --mount=type=cache,target=/web/.next/cache,sharing=locked \
    npm run build

FROM node:22-alpine AS web
WORKDIR /web
ENV NODE_ENV=production \
    HOSTNAME=0.0.0.0 \
    PORT=3000
RUN apk add --no-cache wget
COPY --from=webbuild /web/.next/standalone ./
COPY --from=webbuild /web/.next/static ./.next/static
COPY --from=webbuild /web/public ./public
EXPOSE 3000
HEALTHCHECK --interval=60s --timeout=5s --start-period=20s --retries=3 \
  CMD wget -qO- http://127.0.0.1:3000/api/health >/dev/null || exit 1
USER node
CMD ["node", "server.js"]

# ---------------------------------------------------------------- bot
FROM python:3.12-slim-bookworm AS bot

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    MAIMAI_WEBSERVER_HOST=0.0.0.0 \
    MAIMAI_WEBSERVER_PORT=8765 \
    MAIMAI_DATABASE_PATH=/app/data/maimai.sqlite3

RUN apt-get update \
 && apt-get install -y --no-install-recommends git ca-certificates \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Chromium and its system libraries get their own layer, keyed only on the
# Playwright version, so editing requirements.txt never re-downloads them.
ARG PLAYWRIGHT_VERSION=1.60.0
RUN --mount=type=cache,target=/root/.cache/pip,sharing=locked \
    pip install "playwright==${PLAYWRIGHT_VERSION}" \
 && playwright install --with-deps chromium \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip,sharing=locked \
    pip install -r requirements.txt

COPY rasmai/ ./rasmai/
COPY brand/emoji/png/ ./brand/emoji/png/
# the linking walkthroughs, so /login can play one in Discord rather than sending people away
COPY web/public/walkthrough/ ./walkthrough/

VOLUME ["/app/data", "/app/otoge_cache"]
EXPOSE 8765

HEALTHCHECK --interval=60s --timeout=5s --start-period=90s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/health', timeout=4)" || exit 1

CMD ["python", "-m", "rasmai"]
