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
  bounded GET or POST-token pagination, bounded rate-limit and server-error retry,
  deduplication, source-product identity, and per-sensor incomplete/failure status;
- deterministic quality-aware selection with separate sensor outcomes, radar
  compatibility metadata, and reason codes for no acquisition, stale/obscured/
  partial coverage, incomplete scans, and missing comparison baselines. A
  catalogued renderable product without regional quality assessment is selected
  provisionally, with `quality_unassessed` shown explicitly; its footprint
  overlap with the incident core takes priority over recency;
- rendered-raster core quality assessment when the selected S1/S2 recipe includes
  validity bands. S2 reports usable, obscured, uncertain, and uncovered fractions
  from SCL and `dataMask`; S1 reports source coverage without treating radar
  brightness as damage. Catalog estimates are replaced with measured fractions
  after preparation, and the mask definition remains in provenance;
- authenticated Copernicus Data Space Process requests constrained to the selected
  product by scene filtering and verified response metadata, a metric region grid,
  fixed S1/S2 recipe identities, and bounded response sizes;
- staged, checksummed, atomically published local artifacts; strict GeoTIFF/COG
  validation; transparent XYZ tiles generated only from stored artifacts; and
  credential-free provenance manifests;
- typed HTTP resources under `/api/v1/ground-imagery` and a desktop Ground panel
  with independent radar/optical status, capture dates, roles, quality explanations,
  readiness messaging, a full-artifact preview when one observation is prepared,
  an interactive tile map with incident core, inspection boundary, acquisition
  footprint, OpenStreetMap base, scale, and image opacity,
  a 5/15/30 km operator-selected inspection circle when an incident has no
  defensible impact region,
  a comparison-stage summary for each sensor when no pair is renderable,
  refresh/watch controls, artifact download, and manifest links. Selecting an
  incident opens Ground view; it prepares the latest post-event image automatically
  when available, or a pre-event reference otherwise, and polls queued work;
- PostgreSQL JSONB request persistence, stale-version protection, and durable
  selection lookup when the operational database is configured. Prepared artifacts
  retain their observation snapshot through refreshes;
- PostgreSQL-backed leased preparation jobs with fencing tokens, bounded retry/backoff,
  explicit Copernicus Data Space budget reservations, failure diagnostics, restart
  recovery, scheduled watch claims, and reference-aware artifact retention cleanup.
  Local development keeps a deterministic synchronous fallback.

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

CDSE catalog metadata alone cannot establish image quality or guarantee that a
product is already available to the Process API. A selected product may still fail
rendering or cover only part of the incident region. Ground view preserves those
states and does not claim that every disaster has a post-event image.
Opening an idempotent Ground view refreshes its catalog search when the previous
search time is at least one hour old. Manual refresh and due watch checks use the
current server time, so newly published captures can enter the search window.
Watch preferences survive restart in PostgreSQL and the worker claims due checks
without two workers processing the same due time. A live watch does not guarantee
new imagery: provider availability, catalog lag, source quality, and request limits
still apply. The UI shows both sensing time and the latest search time.
GDACS flood list points are event locators, not verified impact points. Ground view
does not search around them automatically. An operator can provide a known center
and radius; the resulting region is labeled user-selected and is never presented
as a measured flood boundary. Changing the region uses a fresh search window.

## Request limits

Until the API has a trusted user identity and shared rate-limit storage, limits
apply to the whole running API process. It admits at most six new catalog searches
per rolling hour and 24 per rolling day, with one new search per incident per hour.
It admits at most four image preparations per rolling hour and 12 per rolling day.
Reopening an idempotent request, preparing an existing artifact, or observing an
already queued job does not use another slot. Exceeding a limit returns HTTP 429
with `Retry-After`. Counters reset when the API process restarts; multiple API
replicas do not share them. These limits control request frequency, not actual
Copernicus processing units, which also depend on area, resolution, and recipe.
Scheduled watches use the same process-local limiter. If a watch reaches a limit,
its next check remains scheduled but that cycle has no new catalog result. Deployments
with many watched incidents need shared admission and capacity planning before
promising hourly coverage.

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
| `GET` | `/api/v1/ground-imagery/artifacts/{id}/preview.png` | Render a bounded full-artifact preview PNG |

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
An observation footprint shows where the satellite acquired data; it is not a
damage or flood-extent outline. Transparent map pixels mean no source data. Optical
cloud classes and radar ambiguity still limit what visible pixels can establish.
The map and preview do not show ground-level photographs or prove road access,
building safety, or the absence of impact.

The first Process recipes are intentionally conservative: S1 uses an orthorectified
Gamma-0 terrain request with VV/VH metadata when available, and S2 requests L2A
visible bands plus SCL/data validity. The tile renderer uses the S2 `dataMask` for
opacity rather than treating SCL as alpha. Provider responses are still observational
context; radar brightness and optical visibility do not establish a specific cause of
change.

## Current release boundary

### Targeted live smoke, 27 September 2026

An independently checked [GDACS Aichi flood report](https://www.gdacs.org/Floods/report.aspx?detail=true&episodeid=2&eventid=1104140&eventtype=FL)
was used with a small, explicitly selected inspection area near Nagoya. Public CDSE
search returned recent captures from both sensors. Authenticated preparation produced
validated COGs and previews for a 23 September Sentinel-1 capture and a 26 September
Sentinel-2 capture. The optical core measured 100% obscured; the radar core had 100%
valid data coverage. The latter means a usable radar observation, not detected flood
damage. The interface now prefers that usable capture over the newer obscured one.

For an independently checked [GDACS Lam Dong flood report](https://www.gdacs.org/Floods/report.aspx?detail=true&episodeid=7&eventid=1104141&eventtype=FL),
public CDSE search returned 23 September acquisitions from both sensors near Da Lat.
Those acquisitions were catalog checks; no Lam Dong COG was prepared. These smoke
checks supplement the locked four-case deployment acceptance manifest, whose live
case statuses remain pending.

The following bounded capability remains outside a full imagery-analysis claim:

- GFM mask-to-component extraction, CEMS delivered-impact ingestion, source-backed
  shaking regions, and complete place-boundary caching constrained by administrative
  context;
- complete numeric/display/quality artifact sets, raster chunk assembly and halos,
  comparison manifests, exports, and restore-drill evidence;
- all antimeridian/polar/multi-zone raster partitions and scene-specific quality
  interpretation beyond the current validity masks;
- end-to-end comparison manifests, exports, and operational restore drills;
- deployment-specific live acceptance evidence and resource measurements.

Ground view is an implemented, bounded observation-context path. It must not be
described as damage assessment, impact prediction, or guaranteed global imagery
coverage. Live acceptance evidence is maintained separately in
`evaluation/ground_acceptance.v1.json` and is required for deployment-specific
promotion. Run the fail-closed target-host gate with
`uv run --directory apps/api python scripts/check_ground_acceptance.py --require-live`;
ordinary CI validates the locked manifest without representing fixture replay as a
live provider run.
