# Disaster Monitor

Disaster Monitor is a local-first disaster-monitoring app. It has a Next.js
map, a FastAPI backend, bounded source-backed reporting, and optional local Qwen
models.

Assistant requests enter a bounded agent runtime. Normalized trusted-source
evidence supplies current facts. Model output cannot create providers, countries,
URLs, or facts.

## Run

For this initialized Windows checkout, see [Windows development](docs/windows-development.md).

Backend:

```powershell
uv run --project apps/api uvicorn disaster_monitor.main:app --reload --host 127.0.0.1 --port 8001
```

Frontend:

```powershell
cd apps/web && npm run dev
```