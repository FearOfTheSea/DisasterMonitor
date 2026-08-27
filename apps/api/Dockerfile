FROM ghcr.io/astral-sh/uv:0.11.32 AS uv

FROM python:3.12.11-slim-bookworm AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy
WORKDIR /app
COPY --from=uv /uv /uvx /bin/
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN uv sync --frozen --no-dev

FROM python:3.12.11-slim-bookworm AS runtime

ENV PATH=/app/.venv/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
WORKDIR /app
RUN groupadd --gid 10001 disastermonitor \
    && useradd --uid 10001 --gid disastermonitor --create-home disastermonitor \
    && mkdir -p /var/lib/disaster-monitor/blobs \
        /var/lib/disaster-monitor/event-media \
        /var/lib/disaster-monitor/geography \
    && chown -R disastermonitor:disastermonitor /var/lib/disaster-monitor
COPY --from=builder --chown=disastermonitor:disastermonitor /app/.venv /app/.venv
USER disastermonitor

EXPOSE 8001
CMD ["uvicorn", "disaster_monitor.main:app", "--host", "0.0.0.0", "--port", "8001"]
