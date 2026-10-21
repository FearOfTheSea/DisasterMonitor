# Disaster Monitor

Disaster Monitor is a local-first disaster-monitoring app. It has a Next.js
map, a FastAPI backend, bounded source-backed reporting, and optional local Qwen
models.

Assistant requests enter a bounded agent runtime. Normalized trusted-source
evidence supplies current facts. Model output cannot create providers, countries,
URLs, or facts.

## Run

The backend uses Python 3.12 and `uv` 0.11.32. `apps/api/.python-version` selects
Python 3.12 for local and CI runs, including on Ubuntu releases with a newer system
Python. The frontend uses Node.js 24.19.0 and npm.
The API dependency graph is locked in `apps/api/uv.lock`. The web dependency graph is
locked in `apps/web/package-lock.json`.

Backend:

```bash
uv sync --project apps/api --frozen
uv run --frozen --project apps/api uvicorn disaster_monitor.main:app --reload --host 127.0.0.1 --port 8001
```

Frontend:

```bash
cd apps/web
npm ci
npm run dev
```

The checked-in Docker files provide a repeatable container runtime. Keep local
credentials in ignored environment files. The local Compose file uses local-only
database settings and is not an AWS production deployment configuration.
