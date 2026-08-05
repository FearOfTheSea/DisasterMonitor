# Disaster Monitor

Disaster Monitor is a local-first MVP for exploring a basic interactive map and asking a locally running Qwen model map or disaster-monitoring questions. The model runs locally. A narrowly routed, no-key RSS lookup supplies recent report metadata only for explicit latest/current earthquake requests and latest damage requests about Japan.

## Current MVP

- Next.js and OpenLayers frontend with an OpenStreetMap base layer centered on Hanoi.
- Assistant drawer with typed requests, conversation rendering, loading and error states.
- Browser-session conversation continuity using `sessionStorage`.
- FastAPI health, readiness, and assistant endpoints.
- Ollama adapter for a configurable local Qwen model.
- Deterministic request normalization, prompt preparation, and provider-error translation.
- Deterministic routing for current Japan earthquake-damage questions.
- A focused `DisasterInformationProvider` port backed by Google News RSS report metadata.
- Unit, HTTP integration, component, adapter, and deterministic Playwright system tests.

The assistant still clearly reports that live weather, flood, satellite, and geocoding data are not connected. The RSS adapter supplies source titles, publication times, URLs, and snippets; it does not independently verify damage figures. The model is instructed to attribute all time-sensitive claims, preserve conflicting or preliminary reports, and report lookup unavailability instead of answering from memory.

## Deferred capabilities

Live weather, geocoding, satellite catalogs and imagery, flood providers, general-purpose web search, remote model providers, paid map services, authentication, queues, background workers, cloud deployment, multi-user persistence, and advanced analytics are intentionally deferred. See [docs/migration-report.md](docs/migration-report.md) for the migration decisions.

## Repository layout

```text
apps/api/       FastAPI application and Python tests
apps/web/       Next.js application, OpenLayers map, and frontend tests
docs/           Architecture, migration notes, and scoped implementation prompts
scripts/        Deterministic system-test server and optional smoke helpers
compose.yaml    Optional local two-service orchestration
```

## Prerequisites

- Python 3.12+
- `uv` 0.6+
- Node.js 24 and npm 11+
- Ollama for real model requests (optional for tests)
- Network access for map tiles and current earthquake-report lookup
- Docker Desktop if using Compose (optional)

## Local Qwen setup

Install Ollama from [ollama.com](https://ollama.com/), start it, and pull the configured model:

```powershell
ollama serve
ollama pull qwen3:1.7b
ollama list
```

The backend defaults to `http://localhost:11434` and `qwen3:1.7b`. Copy `apps/api/.env.example` to `apps/api/.env` to override the model, timeout, allowed origins, RSS URL, report limit, or lookback window. No API key is required for the RSS adapter.

## Run the applications independently

Start the backend in one terminal:

```powershell
uv sync --project apps/api
uv run --project apps/api uvicorn disaster_monitor.main:app --reload --host 127.0.0.1 --port 8001
```

Start the frontend in another:

```powershell
cd apps/web
npm ci
Copy-Item .env.example .env.local
npm run dev
```

Open <http://localhost:3000>, click **Open assistant**, and submit a question. The map uses OpenStreetMap tiles. Explicit current earthquake-damage requests also require the configured RSS endpoint to be reachable; other assistant requests use only the local API and Ollama.

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

Then open <http://localhost:3000>. The API container uses `host.docker.internal` to reach Ollama on Docker Desktop. Compose configuration is included for convenience; it is not required for independent development.

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

The deterministic backend and system tests inject fake model and disaster-information providers. They do not require Ollama, cloud credentials, or a live RSS response.

## Optional real-Qwen smoke test

After Ollama is running and `ollama pull qwen3:1.7b` completes:

```powershell
uv run --project apps/api python scripts/real_qwen_smoke.py
```

The readiness response must report both `ollama_available: true` and `model_available: true`. This smoke test is manual and excluded from CI because the local model runtime is not guaranteed.

## Troubleshooting

- A `503` assistant response means Ollama is not reachable or the configured model is not installed. Check `ollama serve`, `ollama list`, `OLLAMA_BASE_URL`, and `OLLAMA_MODEL`.
- A current earthquake-damage answer that says the latest information cannot be verified means the RSS request failed, returned malformed XML, or returned no matching reports. Check network access and the `DISASTER_NEWS_*` settings.
- A frontend network error usually means the API is not running on port 8001 or `NEXT_PUBLIC_API_BASE_URL` is incorrect.
- OpenStreetMap tiles are external map tiles, not a disaster-data provider.
- If Playwright cannot start, install Chromium with `npx playwright install chromium` and make sure both Node.js and `uv` are on `PATH`.

## Extension guidance

Add future capabilities by introducing a focused application port only when the capability is used. Keep provider calls in infrastructure adapters, translate them into application DTOs, and inject the adapter from `infrastructure/composition.py`. The frontend should receive typed transport data through a feature API client rather than calling providers from React components.

See [docs/architecture.md](docs/architecture.md) for the current dependency direction and [docs/current-earthquake-damage-capability.md](docs/current-earthquake-damage-capability.md) for the scoped implementation prompt.
