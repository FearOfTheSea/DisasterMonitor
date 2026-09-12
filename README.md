# Disaster Monitor

Disaster Monitor is a local-first disaster-monitoring app. It has a Next.js
map, a FastAPI backend, bounded source-backed reporting, and optional local Qwen
models.

Assistant requests enter a bounded agent runtime. Normalized trusted-source
evidence supplies current facts. Model output cannot create providers, countries,
URLs, or facts.

## Run

Backend:

```powershell
uv run --project apps/api uvicorn disaster_monitor.main:app --reload --host 127.0.0.1 --port 8001
```

Frontend:

```powershell
cd apps/web && npm run dev
```

### Optional protected satellite imagery

NASA VIIRS, MODIS, GOES, and Himawari imagery loads directly from the public NASA
GIBS Web Mercator service. Copernicus and Planet tiles pass through the API.

Sentinel-2: configure a Sentinel Hub WMS instance with the named true
color layer:

```dotenv
COPERNICUS_SENTINEL_HUB_INSTANCE_ID=your-private-instance-id
COPERNICUS_SENTINEL_HUB_LAYER_ID=TRUE_COLOR
```

Planet: configure one mosaic that the account can access:

```dotenv
PLANET_API_KEY=your-private-api-key
PLANET_MOSAIC_NAME=your-accessible-mosaic-name
```

The separate event-focused Ground view searches real Sentinel-1 and Sentinel-2
acquisitions around a selected incident through the public CDSE STAC API. It can
show catalog metadata without credentials; preparing downloadable COGs requires a
CDSE OAuth client:

```dotenv
CDSE_CLIENT_ID=your-cdse-client-id
CDSE_CLIENT_SECRET=your-cdse-client-secret
```

Ground view stores validated artifacts under `GROUND_IMAGERY_STORAGE_ROOT` (20 GiB
by default). It is regional observational context, not a building-level damage or
passability assessment. See [docs/ground-imagery.md](docs/ground-imagery.md) for
the implemented boundary and current release gaps.

## Run with Compose

```powershell
docker compose up --build
```
