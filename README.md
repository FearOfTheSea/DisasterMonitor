# Disaster Monitor

Disaster Monitor is a local-first disaster-monitoring MVP. It combines a Next.js map,
a FastAPI backend, bounded source-backed reporting, and optional local Qwen models.

Assistant requests enter a bounded agent runtime. Current facts come from normalized
trusted-source evidence; model output cannot create providers, countries, URLs, or
facts. See [docs/agent-runtime.md](docs/agent-runtime.md).

## Included

- Next.js/OpenLayers map with a typed layer registry, operator presets and display-time
  filters, source-backed Active Incidents, dense point clustering, layer provenance,
  and an assistant UI with session-local conversation state.
- Persistent local Incident Watches with bounded scheduled refresh, deterministic
  source-backed change timelines, unread/read state, exact-evidence map focus, and a
  deterministic Findings view shared with coverage and compound-hazard context.
- Selectable NASA GIBS satellite imagery plus optional server-proxied Copernicus
  Sentinel-2 and one configured Planet mosaic.
- FastAPI health, readiness, active-incidents, incident-watch, assistant, and operations
  endpoints.
- Optional local Qwen text and vision adapters.
- Deterministic request normalization, event selection, evidence reconciliation, and
  source-attributed reports.
- USGS, GDACS, NASA EONET wildfire, NASA COOLR landslide, CEMS GFM, and
  Smithsonian/USGS volcanic-eruption event adapters.
- Optional ReliefWeb supplementary situation reports when configured.
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

Live weather, geocoding, dynamic satellite scene discovery, broad news aggregation,
hosted models, production identity/TLS, cloud deployment, and consequential analytics
remain deferred. External datasets, human evaluations, and pilot evidence remain
release gates.

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
ollama pull qwen3:4b-instruct-2507-q4_K_M
ollama list
```

The backend defaults to `http://localhost:11434` and `qwen3:4b-instruct-2507-q4_K_M`. Copy `apps/api/.env.example` to `apps/api/.env` to override the model, timeout, or allowed origins. No API key is required.

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
Invoke-RestMethod 'http://localhost:8001/api/v1/incidents?time_window_days=7&limit_per_disaster=10'
Invoke-RestMethod http://localhost:8001/api/v1/incident-watches
Invoke-RestMethod http://localhost:8001/api/v1/satellite-imagery
```

The incidents endpoint queries the registered worldwide event-discovery providers
directly; it does not call Qwen. Its defaults are a 7-day window and at most 10
records per disaster. Each of the six hazards has a separate coverage state so an
upstream failure, unavailable provider, or successful empty result cannot be mistaken
for proof that no disaster occurred. Map features are drawn only from source-backed
point, track, or area geometry returned by the endpoint. The map control surface keeps
Active Incidents, satellite imagery, Common Operational Picture evidence, cyclone
supplemental geometry, and descriptive compound-hazard correlations in one typed
registry with inspectable provenance and limitations. Its 1-hour through 7-day filters
change displayed incident and correlation records only; they do not rewrite backend
coverage or turn a filtered view into an absence claim. Dense point records cluster at
lower zoom while source-backed area and track geometry stays unclustered.

Incident Watches monitor one disaster type in one canonical country or worldwide at a
bounded 5-minute to 24-hour interval. The existing scheduler/worker uses the registered
provider path and deterministic typed-state hashes; Qwen does not decide changes or
alerts. With Compose, watches and timelines are durable in PostgreSQL. A standalone API
uses the non-durable in-memory fallback. Open Evidence operations to create watches,
inspect coverage and source-attributed timelines, focus retained geometry on the map,
and mark changes read. The Findings center is a deterministic frontend aggregation of
unread watch changes, watch and Active Incidents coverage limitations, retrieval
warnings, and returned compound-hazard correlations. It does not use Qwen to generate,
rank, or rewrite findings, and watch read state still uses the Incident Watch API. This
is bounded monitoring, not complete global surveillance or an external
warning/notification system.

### Optional protected satellite imagery

NASA VIIRS, MODIS, GOES, and Himawari imagery loads directly from the public NASA
GIBS Web Mercator service. Copernicus and Planet tiles always pass through the API so
their credentials never enter browser configuration or returned tile URLs.

To enable Sentinel-2, configure a Sentinel Hub WMS instance containing the named true
color layer:

```dotenv
COPERNICUS_SENTINEL_HUB_INSTANCE_ID=your-private-instance-id
COPERNICUS_SENTINEL_HUB_LAYER_ID=TRUE_COLOR
```

To enable Planet, configure one mosaic already accessible to the account:

```dotenv
PLANET_API_KEY=your-private-api-key
PLANET_MOSAIC_NAME=your-accessible-mosaic-name
```

Keep these values in `apps/api/.env` or the server environment. Do not place them in
`NEXT_PUBLIC_*` variables. When either provider is not configured, its map option is
shown disabled. Planet support is intentionally limited to the configured mosaic; it
does not discover PlanetScope scenes dynamically.

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

The optional live-provider smoke test is excluded from normal CI. It submits two
natural-language named-country examples for every supported hazard, one worldwide
question per hazard, and an all-hazard Active Incidents request while printing provider
failures and coverage states:

```powershell
uv run --project apps/api python scripts/live_disaster_smoke.py
```

It was not run during the default offline verification.

## Optional real-Qwen smoke test

After Ollama is running and `ollama pull qwen3:4b-instruct-2507-q4_K_M` completes:

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
