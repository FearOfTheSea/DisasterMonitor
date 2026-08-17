# Disaster Monitor

Disaster Monitor is a local-first disaster-monitoring MVP. It combines a Next.js map,
a FastAPI backend, bounded source-backed reporting, and optional local Qwen models.

Assistant requests enter a bounded agent runtime. Current facts come from normalized
trusted-source evidence; model output cannot create providers, countries, URLs, or
facts. See [docs/agent-runtime.md](docs/agent-runtime.md).

## Included

- Next.js/OpenLayers map and assistant UI with session-local conversation state.
- FastAPI health, readiness, assistant, and operations endpoints.
- Optional local Qwen text and vision adapters.
- Deterministic request normalization, event selection, evidence reconciliation, and
  source-attributed reports.
- JMA, USGS, FDMA, ReliefWeb, NCHMF, FIRMS, GFM, and explicitly registered CAP paths.
- Optional PostgreSQL/PostGIS history, snapshots, workers, freshness, reviews, and
  backup tooling.
- Bounded multimodal observations, contextual event media, triage, decision support,
  specialist coordination, and governed analytical ordering.
- Backend, frontend, adapter, integration, evaluation, and Playwright tests.

Unsupported combinations and missing configuration are reported explicitly. See
[current-disaster-reporting.md](docs/current-disaster-reporting.md),
[multimodal-awareness.md](docs/multimodal-awareness.md), and
[capability-status.md](docs/capability-status.md).

## Deferred

Live weather, geocoding, automatic imagery retrieval, broad news aggregation, hosted
models, paid map services, production identity/TLS, cloud deployment, and consequential
analytics remain deferred. External datasets, human evaluations, and pilot evidence
remain release gates.

## Repository layout

```text
apps/api/       FastAPI application and Python tests
apps/web/       Next.js application, OpenLayers map, and frontend tests
docs/           Architecture and other documentation
scripts/        Deterministic system-test server and optional smoke helpers
compose.yaml    Production-like local API/web/scheduler/worker/PostGIS orchestration
```

## Prerequisites

- Python 3.12+
- `uv` 0.6+
- Node.js 24 and npm 11+
- Ollama for real model requests (optional for tests)
- Docker Desktop if using Compose (optional)

## Local Qwen setup

Install Ollama from [ollama.com](https://ollama.com/), start it, and pull the configured model:

```powershell
ollama serve
ollama pull qwen3:1.7b
ollama list
```

The backend defaults to `http://localhost:11434` and `qwen3:1.7b`. Copy `apps/api/.env.example` to `apps/api/.env` to override the model, timeout, or allowed origins. No API key is required.

## Run the applications independently

Start the backend:

```powershell
uv sync --project apps/api
uv run --project apps/api uvicorn disaster_monitor.main:app --reload --host 127.0.0.1 --port 8001
```

Start the frontend:

```powershell
cd apps/web
npm ci
Copy-Item .env.example .env.local
npm run dev
```

Useful checks:

```powershell
Invoke-RestMethod http://localhost:8001/api/v1/health
Invoke-RestMethod http://localhost:8001/api/v1/ready
```

## Run with Compose

With Docker Desktop running and Ollama running on the host:

```powershell
docker compose up --build
```

Then open <http://localhost:3000>. The API container uses `host.docker.internal` to
reach Ollama. Compose also starts PostgreSQL/PostGIS, migration, scheduler, and worker
services with durable volumes. See
[docs/operations/runbook.md](docs/operations/runbook.md).

## Test commands

Backend checks:

```powershell
uv sync --project apps/api
uv run --directory apps/api ruff format --check src tests
uv run --directory apps/api ruff check src tests
uv run --directory apps/api mypy
uv run --directory apps/api pytest -q
```

Frontend checks:

```powershell
cd apps/web
npm ci
npm run format:check
npm run lint
npm run typecheck
npm test
npm run build
```

The deterministic system test starts a fake-model FastAPI server and a Next.js dev server, so it does not need Ollama:

```powershell
cd apps/web
npm run test:system
```

Playwright may need its browser installed once:

```powershell
npx playwright install chromium
```

The optional live-provider smoke test is excluded from normal CI and checks only
structural properties of changing live data:

```powershell
uv run --project apps/api python scripts/live_disaster_smoke.py
```

It was not run during the default offline verification.

## Optional real-Qwen smoke test

After Ollama is running and `ollama pull qwen3:1.7b` completes:

```powershell
uv run --project apps/api python scripts/real_qwen_smoke.py
```

The readiness response must report both `ollama_available: true` and `model_available: true`. This smoke test is manual and excluded from CI because the local model runtime is not guaranteed.

## Troubleshooting

- A `503` assistant response means Ollama is not reachable or the configured model is not installed. Check `ollama serve`, `ollama list`, `OLLAMA_BASE_URL`, and `OLLAMA_MODEL`.
- A frontend network error usually means the API is not running on port 8001 or `NEXT_PUBLIC_API_BASE_URL` is incorrect.
- OpenStreetMap tiles are external map tiles, not a disaster-data provider. If tiles are unavailable, the assistant and API tests still work.
- If Playwright cannot start, install Chromium with the command above and make sure both Node.js and `uv` are on `PATH`.

## Extension guidance

Add future capabilities by introducing a focused application port only when the capability is used. Keep provider calls in infrastructure adapters, translate them into application DTOs, and inject the adapter from `infrastructure/composition.py`. The frontend should receive typed transport data through a feature API client rather than calling providers from React components.

See [docs/architecture.md](docs/architecture.md) for the current dependency direction.
