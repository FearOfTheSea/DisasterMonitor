# Disaster Monitor

Disaster Monitor is a local-first disaster-monitoring MVP. It combines a Next.js
map, a FastAPI backend, bounded source-backed reporting, and optional local Qwen
models.

Assistant requests enter a bounded agent runtime. Normalized trusted-source
evidence supplies current facts. Model output cannot create providers, countries,
URLs, or facts. See [docs/agent-runtime.md](docs/agent-runtime.md).

## Included

- Next.js and OpenLayers map with a typed layer registry, operator presets,
  display-time filters, regional navigation, shareable bounded URL state, and
  source-backed Active Incidents.
- The map adds dense point clustering, layer provenance, and session-local assistant
  conversation state.
- Read-only Source Catalog, dataset-specific hidden-tab-aware refresh, and a
  deterministic keyboard command palette for existing operator controls.
- Bounded authoritative NOAA/NWS active weather-alert context for United States
  land areas. This context stays separate from physical incident discovery and
  correlation.
- Persistent local Incident Watches with bounded scheduled refresh, deterministic
  source-backed change timelines, unread/read state, exact-evidence map focus, and
  a deterministic Findings view.
- Selectable NASA GIBS satellite imagery, optional server-proxied Copernicus
  Sentinel-2, and one configured Planet mosaic.
- FastAPI health, readiness, active-incidents, weather-alert, source-catalog,
  incident-watch, assistant, and operations endpoints.
- Optional local Qwen text and vision adapters.
- Deterministic request normalization, event selection, evidence reconciliation,
  and source-attributed reports.
- USGS, GDACS, NASA EONET wildfire, NASA COOLR landslide, CEMS GFM, and
  Smithsonian/USGS volcanic-eruption event adapters.
- Optional ReliefWeb supplementary situation reports when configured.
- Optional PostgreSQL/PostGIS history, snapshots, workers, freshness, reviews,
  and backup tooling.
- Bounded multimodal observations, contextual event media, triage, decision
  support, specialist coordination, and governed analytical ordering.
- Backend, frontend, adapter, integration, evaluation, and Playwright tests.

Unsupported combinations and missing configuration are reported explicitly. See
[current-disaster-reporting.md](docs/current-disaster-reporting.md),
[multimodal-awareness.md](docs/multimodal-awareness.md), and
[capability-status.md](docs/capability-status.md).

## Deferred

Generic live weather, forecasts, radar, geocoding, dynamic satellite scene
discovery, broad news aggregation, hosted models, production identity/TLS, cloud
deployment, and consequential analytics remain deferred. External datasets,
human evaluations, and pilot evidence remain release gates.

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

Install Ollama from [ollama.com](https://ollama.com/). Start Ollama and pull the
configured model:

```powershell
ollama serve
ollama pull qwen3:4b-instruct-2507-q4_K_M
ollama list
```

The backend defaults to `http://localhost:11434` and
`qwen3:4b-instruct-2507-q4_K_M`. Copy `apps/api/.env.example` to `apps/api/.env`
to override the model, timeout, or allowed origins. No API key is required.

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

Run these checks:

```powershell
Invoke-RestMethod http://localhost:8001/api/v1/health
Invoke-RestMethod http://localhost:8001/api/v1/ready
Invoke-RestMethod 'http://localhost:8001/api/v1/incidents?time_window_days=7&limit_per_disaster=10'
Invoke-RestMethod http://localhost:8001/api/v1/weather-alerts
Invoke-RestMethod http://localhost:8001/api/v1/sources
Invoke-RestMethod http://localhost:8001/api/v1/incident-watches
Invoke-RestMethod http://localhost:8001/api/v1/satellite-imagery
```

The incidents endpoint queries registered worldwide event-discovery providers
directly. It does not call Qwen. Its default window is seven days, with ten
records per disaster.

Each of the six hazards has a separate coverage state. An upstream failure,
unavailable provider, or successful empty result cannot prove that no disaster
occurred.

The map draws features only from source-backed point, track, or area geometry.
The typed layer registry includes Active Incidents, satellite imagery, Common
Operational Picture evidence, cyclone supplemental geometry, and descriptive
compound-hazard correlations.

The one-hour through seven-day filters change displayed incident and correlation
records only. They do not change backend coverage or create an absence claim.
Dense point records cluster at lower zoom. Source-backed area and track geometry
remains unclustered.

The weather-alert endpoint makes one bounded request to the official NOAA/NWS
active-alert GeoJSON API. Alerts retain CAP authority, timestamps, coverage,
attribution, and exact source polygons. Missing geometry remains missing.

Weather alerts are warning artifacts. They are not Active Incidents or
compound-hazard inputs. The frontend keeps maintained Source Catalog metadata
separate from separately labelled runtime registration and configuration state.
Neither the catalog nor the command palette can change provider authority.

Incident Watches monitor one disaster type in one canonical country or worldwide,
with a five-minute to 24-hour interval. The scheduler and worker use the registered
provider path and deterministic typed-state hashes. Qwen does not decide changes or
alerts.

With Compose, watches and timelines persist in PostgreSQL. A standalone API uses
the non-durable in-memory fallback. Evidence operations can create watches, inspect
coverage and source-attributed timelines, focus retained geometry on the map, and
mark changes read.

The Findings center aggregates unread watch changes, watch and Active Incidents
coverage limits, retrieval warnings, and returned compound-hazard correlations.
It does not use Qwen to generate, rank, or rewrite findings. Watch read state still
uses the Incident Watch API.

This is bounded monitoring. It is not complete global surveillance or an external
warning or notification system.

### Optional protected satellite imagery

NASA VIIRS, MODIS, GOES, and Himawari imagery loads directly from the public NASA
GIBS Web Mercator service. Copernicus and Planet tiles pass through the API. Their
credentials never enter browser configuration or returned tile URLs.

To enable Sentinel-2, configure a Sentinel Hub WMS instance with the named true
color layer:

```dotenv
COPERNICUS_SENTINEL_HUB_INSTANCE_ID=your-private-instance-id
COPERNICUS_SENTINEL_HUB_LAYER_ID=TRUE_COLOR
```

To enable Planet, configure one mosaic that the account can access:

```dotenv
PLANET_API_KEY=your-private-api-key
PLANET_MOSAIC_NAME=your-accessible-mosaic-name
```

Keep these values in `apps/api/.env` or the server environment. Do not place them
in `NEXT_PUBLIC_*` variables. An unconfigured provider appears disabled on the map.
Planet support is limited to the configured mosaic. It does not discover
PlanetScope scenes dynamically.

## Run with Compose

Start Docker Desktop and Ollama on the host. Then run:

```powershell
docker compose up --build
```

Open <http://localhost:3000>. The API container uses `host.docker.internal` to
reach Ollama. Compose also starts PostgreSQL/PostGIS, migration, scheduler, and
worker services with durable volumes. See
[docs/operations/runbook.md](docs/operations/runbook.md).

## Test commands

Run the backend checks:

```powershell
uv sync --project apps/api
uv run --directory apps/api ruff format --check src tests
uv run --directory apps/api ruff check src tests
uv run --directory apps/api mypy
uv run --directory apps/api pytest -q
```

Run the frontend checks:

```powershell
cd apps/web
npm ci
npm run format:check
npm run lint
npm run typecheck
npm test
npm run build
```

The deterministic system test starts a fake-model FastAPI server and a Next.js
development server. It does not need Ollama:

```powershell
cd apps/web
npm run test:system
```

Install the Playwright browser once when needed:

```powershell
npx playwright install chromium
```

The optional live-provider smoke test is excluded from normal CI. It sends two
natural-language named-country examples for every supported hazard, one worldwide
question per hazard, and one all-hazard Active Incidents request. It prints provider
failures and coverage states:

```powershell
uv run --project apps/api python scripts/live_disaster_smoke.py
```

The default offline verification did not run this test.

## Optional real-Qwen smoke test

Start Ollama and pull `qwen3:4b-instruct-2507-q4_K_M`. Then run:

```powershell
uv run --project apps/api python scripts/real_qwen_smoke.py
```

The readiness response must report `ollama_available: true` and
`model_available: true`. This manual smoke test is excluded from CI because the
local model runtime is not guaranteed.

## Troubleshooting

- For a `503` assistant response, check `ollama serve` and `ollama list`.
- Check `OLLAMA_BASE_URL` and `OLLAMA_MODEL`.
- For a frontend network error, check that the API runs on port 8001 and that
  `NEXT_PUBLIC_API_BASE_URL` is correct.
- OpenStreetMap tiles are external map tiles, not a disaster-data provider.
  Assistant and API tests still work when those tiles are unavailable.
- If Playwright cannot start, install Chromium and check that Node.js and `uv` are
  on `PATH`.

## Extension guidance

Add a focused application port only when a future capability uses it. Keep provider
calls in infrastructure adapters. Translate provider records into application DTOs.
Inject each adapter from `infrastructure/composition.py`.

Send typed transport data to the frontend through a feature API client. Do not call
providers from React components.

See [docs/architecture.md](docs/architecture.md) for the dependency direction.
