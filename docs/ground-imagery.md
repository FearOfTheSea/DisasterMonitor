# Event-focused Ground view

Ground view is the bounded Sentinel-1/Sentinel-2 observation workflow described in
[`plan.md`](../plan.md). It is regional context for an admitted incident. It must not
be read as a building-level damage assessment, a road-passability result, a casualty
count, or proof that an area outside observed coverage was unaffected.

## What is implemented

The current vertical slice provides:

- immutable WGS84 Polygon/MultiPolygon region values with holes, source identity,
  association, semantic roles, versioning, geometry hashes, and derivation inputs;
- a read-only incident-context port and adapter from admitted incident geometry;
- mapped-impact, observation-mask, modeled-hazard, reported-place, verified-point,
  and user-region handling with hazard-specific point fallback radii;
- a default 2 km polygon context margin, configurable from 0 to 20 km, and bounded
  metric grids capped at 2,048 pixels per side;
- explicit exact or interval onset, unknown-onset behavior, pre-event/first-useful/
  latest-useful role windows, age classes, and a versioned temporal policy;
- independent public CDSE STAC searches for Sentinel-1 GRD and Sentinel-2 L2A,
  bounded pagination, deduplication, source-product identity, and per-sensor
  incomplete/failure status;
- deterministic quality-aware selection with separate sensor outcomes, radar
  compatibility metadata, and reason codes for no acquisition, stale/obscured/
  partial coverage, incomplete scans, and missing comparison baselines;
- authenticated CDSE Sentinel Hub Process requests constrained to the selected
  product, metric region grid, fixed S1/S2 recipe identities, and bounded response
  sizes;
- staged, checksummed, atomically published local artifacts; strict GeoTIFF/COG
  validation; transparent XYZ tiles generated only from stored artifacts; and
  credential-free provenance manifests;
- typed HTTP resources under `/api/v1/ground-imagery` and a desktop Ground panel
  with independent radar/optical status, capture dates, roles, quality explanations,
  readiness messaging, refresh/watch controls, artifact download, and manifest links;
- PostgreSQL JSONB request persistence, stale-version protection, and durable
  selection lookup when the operational database is configured. Local development
  uses a deterministic in-process metadata store.

## Provider readiness

Catalog discovery uses the public CDSE STAC endpoint and does not require credentials.
COG preparation requires server-side CDSE OAuth credentials:

```dotenv
CDSE_CLIENT_ID=...
CDSE_CLIENT_SECRET=...
```

The API exposes `GET /api/v1/ground-imagery/readiness`. `credentials_required` is an
expected safe state: the Ground panel can still display the catalog and selection
context, but it does not offer a misleading download action. Credentials are never
returned in request payloads, manifests, logs, or frontend configuration.

## Wire resources

The implementation exposes these bounded resources:

| Method | Resource | Purpose |
| --- | --- | --- |
| `POST` | `/api/v1/ground-imagery/requests` | Resolve a region and search both sensors |
| `GET` | `/api/v1/ground-imagery/requests/{id}` | Read the versioned request and sensor outcomes |
| `GET` | `/api/v1/ground-imagery/requests/{id}/observations` | Page catalog observations |
| `POST` | `/api/v1/ground-imagery/requests/{id}/regions` | Replace the region with a new request version |
| `POST` | `/api/v1/ground-imagery/requests/{id}/selections` | Pin a catalogued observation for a role |
| `POST` | `/api/v1/ground-imagery/requests/{id}/prepare` | Render, validate, and publish one selected artifact |
| `POST` | `/api/v1/ground-imagery/requests/{id}/refresh` | Re-run bounded discovery for the request identity |
| `PUT` | `/api/v1/ground-imagery/requests/{id}/watch` | Store an explicit watch preference |
| `GET` | `/api/v1/ground-imagery/requests/{id}/manifest` | Read credential-free request provenance |
| `GET` | `/api/v1/ground-imagery/selections/{id}/manifest` | Read the manifest for a stable selection |
| `GET` | `/api/v1/ground-imagery/artifacts/{id}/download` | Download a validated COG |
| `GET` | `/api/v1/ground-imagery/artifacts/{id}/tiles/{z}/{x}/{y}.png` | Render a tile from a stored artifact |

Request and selection schemas are included in the generated frontend API contract.
Artifact IDs are allowlisted and provider URLs are never accepted by tile or download
routes. HTTP 200 from a provider is not sufficient for publication: source identity,
CRS, transform, dimensions, usable data, and the selected grid are checked first.

## Provenance and interpretation

The region manifest distinguishes core and inspection geometry. Acquisition footprints
are catalog evidence only; they cannot become an incident point or impact region.
Capture intervals come from sensing metadata, not download time. Sentinel-1 and
Sentinel-2 are searched and selected independently, so a missing optical result does
not hide a usable radar result and vice versa. Partial, cloudy, stale, and incomplete
states remain explicit.

The first Process recipes are intentionally conservative: S1 uses an orthorectified
Gamma-0 terrain request with VV/VH metadata when available, and S2 requests L2A
visible bands plus SCL/data validity. The tile renderer uses the S2 `dataMask` for
opacity rather than treating SCL as alpha. Provider responses are still observational
context; radar brightness and optical visibility do not establish a specific cause of
change.

## Current release boundary

The plan is intentionally not fully complete. The following work remains before a
full release claim:

- GFM mask-to-component extraction, CEMS delivered-impact ingestion, source-backed
  shaking regions, and complete place-boundary caching constrained by administrative
  context;
- leased background imagery jobs, restart/fencing recovery, transactional quota
  reservations and settlement, provider retry/backoff policy, and operational watch
  scheduling;
- complete numeric/display/quality artifact sets, raster chunk assembly and halos,
  comparison manifests, exports, reference-aware cleanup, retention, and restore
  validation;
- richer raster QA for masks, bounds, band order, zero/sub-noise radar values,
  comparison-grid alignment, and all antimeridian/polar/multi-zone partitions;
- end-to-end desktop comparison, coverage overlays, keyboard acceptance, and system
  tests through export for both sensors;
- two recent independently verified provider cases, resource/PU measurements on the
  target machine, and the live acceptance gates specified in `plan.md`.

Until those gates are closed, Ground view should be described as an implemented,
bounded vertical slice with provider readiness and release evidence still pending.
