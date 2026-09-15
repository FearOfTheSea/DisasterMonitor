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
GIBS Web Mercator service. The API does not proxy commercial imagery tiles.

The separate event-focused Ground view searches real Sentinel-1 and Sentinel-2
acquisitions around a selected incident through the public CDSE STAC API. It can
show catalog metadata without credentials; preparing downloadable COGs requires a
CDSE OAuth client:

```dotenv
CDSE_CLIENT_ID=your-cdse-client-id
CDSE_CLIENT_SECRET=your-cdse-client-secret
```

Ground view stores validated artifacts under `GROUND_IMAGERY_STORAGE_ROOT` (20 GiB
by default). CDSE OAuth is a documented free-account entitlement, not a paid
imagery dependency. It is regional observational context, not a building-level
damage or passability assessment. See [docs/ground-imagery.md](docs/ground-imagery.md)
and [docs/provider-rights.md](docs/provider-rights.md) for the boundary and rights.

Humanitarian context, durable unverified field reports, reviewed Kobo/ODK and
Ushahidi interchange, operator notes/checklists, evidence packages, and bounded local
OSM access context are described in
[docs/humanitarian-field-operations.md](docs/humanitarian-field-operations.md).

## Run with Compose

```powershell
docker compose up --build
```
