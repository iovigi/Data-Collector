# Multi-stage non-root Dockerfile for Data Collector 2.0
# The Admin UI is a static SPA built here with Node and served by the Python app
# (same composition as the IIS deployment: data_collector.hosting.iis_app).
FROM node:22-alpine AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

FROM python:3.13-slim AS builder

WORKDIR /build
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY pyproject.toml README.md ./
COPY data_collector ./data_collector

RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir --upgrade pip \
    && /opt/venv/bin/pip install --no-cache-dir .

FROM python:3.13-slim AS runtime

WORKDIR /app
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    APP_HOST=0.0.0.0 \
    APP_PORT=8000 \
    WEB_DIST_DIR=/app/web-dist

RUN groupadd --system dc && useradd --system --gid dc --create-home dc \
    && mkdir -p /app/var/storage && chown -R dc:dc /app

COPY --from=builder /opt/venv /opt/venv
COPY --chown=dc:dc data_collector ./data_collector
COPY --from=web /web/dist /app/web-dist

USER dc
EXPOSE 8000 8001

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/live', timeout=3)" || exit 1

CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "2", "--threads", "4", "data_collector.hosting.iis_app:build_application()"]
