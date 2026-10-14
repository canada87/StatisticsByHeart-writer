# syntax=docker/dockerfile:1.7
#
# StatisticsByHeart writer image. Build context = repository ROOT:
#
#   docker build -f docker/Dockerfile -t statisticsbyheart-writer:0.1.0 .
#
# Stages: (1) frontend SPA build [placeholder, phase 4]  (2) Python deps  (3) slim runtime.

# --------------------------------------------------------------------------- 1. frontend
# Phase 4 (React + Vite dashboard). When the SPA exists, uncomment this stage and the
# `COPY --from=frontend` line in the runtime stage; FastAPI will serve /app/static.
#
# FROM node:22-alpine AS frontend
# WORKDIR /frontend
# COPY frontend/package.json frontend/package-lock.json ./
# RUN npm ci
# COPY frontend/ ./
# RUN npm run build

# --------------------------------------------------------------------------- 2. python deps
FROM python:3.12-slim AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv

RUN pip install --no-cache-dir uv==0.11.23

WORKDIR /app
COPY backend/pyproject.toml backend/uv.lock backend/.python-version ./
RUN uv sync --frozen --no-dev --no-install-project

COPY backend/app ./app
COPY backend/alembic ./alembic
COPY backend/alembic.ini ./

# --------------------------------------------------------------------------- 3. runtime
FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH" \
    TZ=Europe/Rome

RUN groupadd --system --gid 10001 sbh \
 && useradd --system --uid 10001 --gid sbh --no-create-home --shell /usr/sbin/nologin sbh

WORKDIR /app
COPY --from=builder --chown=sbh:sbh /app /app
# COPY --from=frontend --chown=sbh:sbh /frontend/dist /app/static

COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
# Normalise line endings (a Windows checkout would otherwise break the shebang).
RUN sed -i 's/\r$//' /usr/local/bin/entrypoint.sh && chmod 0755 /usr/local/bin/entrypoint.sh

USER sbh
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=3)"]

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
# One worker on purpose: in-process scheduler and login rate limiter (see docs/adr/0003).
CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
