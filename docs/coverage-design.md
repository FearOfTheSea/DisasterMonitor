# Worldwide coverage contract

Status: implementation baseline, version `coverage-contract.v1`.

This document defines what the monitoring surface may claim. It is deliberately
separate from the provider catalog: a configured source is an executable option,
not evidence that the source was reachable or that its coverage is complete.

## User concepts

| Concept | Meaning | Default incident view |
| --- | --- | --- |
| Observed hazard | A source-backed observation that a hazard signal or event was detected | Yes, when admitted as a physical-event observation |
| Physical incident | A conservative identity that groups compatible observations of one event | Yes; one row per resolved identity |
| Official warning | A public warning product issued by an authorized warning service | No; separate warnings surface |
| Forecast | A prediction, track, cone, or modeled future state | No; separate forecast/context layer |
| Humanitarian situation | A report about impacts, needs, casualties, damage, or response | No; separate evidence and situation context |
| Recent update | A source publication or edit about an older event | No change to onset; available through the recently-updated view |

An acquisition, tile, thermal anomaly, or mapped footprint is not automatically a
physical incident. The current CEMS GFM worldwide surface exposes these as
`observation_kind=acquisition` and excludes them from incident counts until a
source-backed event assertion is available.

The following states are not interchangeable:

- `unknown`: the system does not have enough source evidence to classify a state;
- `unobserved`: this attempted source/scope returned no admitted observation;
- `inactive`: a source-backed lifecycle says the event is not currently active;
- `resolved`: a source-backed end or resolution statement exists;
- `unsupported`: no executable provider is registered for the requested capability;
- `unavailable`: a registered capability could not be queried or is not configured;
- `degraded`: some usable data exists, but the attempted scan or admission was
  incomplete.

An empty successful scan is not a claim that no disaster occurred. Missing an event
from one response is not evidence that the event ended.

## Incident and evidence contract

Every admitted record retains:

- source ID, canonical URL, provider-specific event IDs, and separate lineage IDs;
- source publication/update/retrieval times without substituting retrieval time for
  an unknown source time;
- source geometry and its meaning (`observed`, `estimated`, or descriptive-only);
- source-backed measurements with measurement-level provenance;
- country association basis, when a trusted association exists;
- a physical-event ID only when an allowlisted identity policy supports it.

Provider names and source-family labels are lineage metadata, not event identity.
Only namespaced, source-validated event IDs participate in reconciliation. When
records do reconcile, the public incident response retains every corroborating
source URL, so a preferred representation never hides secondary evidence.

Worldwide discovery unions configured providers before applying the same hazard-owned
identity policy used by country retrieval. Provider tier selects the preferred
representation inside an identified event; it does not suppress unrelated events.
Countryless offshore observations remain queryable and are never assigned a country
from a model guess. A multi-country association is a future additive projection and
must not multiply the global physical-incident count.

## Current capability matrix

| Hazard | Current worldwide executable sources | Source role and limitation |
| --- | --- | --- |
| Earthquake | USGS, EMSC, GDACS | Scientific/event catalogs; provider overlap is resolved conservatively |
| Flood | CEMS GFM, GDACS | GFM acquisitions are observations; GDACS is a curated secondary event feed |
| Wildfire | NASA EONET, GDACS | EONET is curated; GDACS may include reviewed upstream material |
| Landslide | NASA COOLR Events Points | Global catalog, not complete real-time surveillance; current endpoint availability is monitored |
| Tropical cyclone | GDACS, IBTrACS | Event/track products have different lifecycle and geometry meanings |
| Volcanic eruption | Smithsonian/USGS WVAR, GDACS | WVAR reports and GDACS events can be revised and have distinct publication times |

Separate products include NWS official warnings, NOAA/NHC forecasts, ReliefWeb
situation reports, FIRMS observations when configured, and Copernicus mapping.
They are not silently promoted into the incident count.

## Query contract and migration

The existing `time_window_days` and `limit_per_disaster` parameters remain accepted
for compatibility. Acquisition is now controlled separately by
`acquisition_limit_per_disaster`; the legacy per-disaster value is not used to
discard records from the worldwide inventory. New query fields are additive:

- `view=recent`, `ongoing`, `recently_updated`, or `historical`;
- server-side `hazard`, `country`, and text filters;
- `acquisition_limit_per_disaster` for each bounded provider request;
- `page_size` and an opaque cursor for result pagination;
- per-disaster `scan_complete`, `records_seen`, and `truncated` metadata;
- explicit `observation_kind` so acquisition observations are not mistaken for
  incidents.

The ongoing view requires a source-backed ongoing status. The recent view is an
occurrence/onset window. The recently-updated view uses source publication/update
time and does not rewrite onset. Unknown lifecycle status remains discoverable and
an empty ongoing view carries an explicit coverage limitation. The current
historical view is bounded by the accepted `time_window_days` query; an explicit
wider UTC occurrence interval is a planned additive contract. Boundary comparisons
are inclusive at the start and end of a stated interval unless a provider contract
says otherwise.

GDACS `fromdate`/`todate` values are retained as an occurrence interval, not
converted into an ended/ongoing claim. NASA EONET's explicit `closed` field is
mapped to an ended status only when its documented closure timestamp is valid.
GDACS's official API documentation describes paged event-list results ordered by
`todate`, while its MHEWS documentation distinguishes event start/end fields from
publication/update information; neither supports treating every interval endpoint
as proof of physical cessation. See the [GDACS API documentation](https://www.gdacs.org/gdacsapi/swagger/index.html),
the [GDACS API quickstart](https://www.gdacs.org/Documents/2025/GDACS_API_quickstart_v2.pdf),
and [NASA EONET v3 documentation](https://eonet.gsfc.nasa.gov/docs/v3).

Stored reads use a versioned materialized projection. The browser page size is not
the provider acquisition budget: a source scan may retain the complete bounded
batch before filters and pagination are applied. Provider pagination ceilings and
acquisition limits set `scan_complete=false` and `truncated=true`; `has_more` only
describes continuation of the current snapshot page. Cursors are tied to the
snapshot version and expire when that in-memory snapshot window is evicted. The
durable worker path persists the projection; standalone development mode exposes a
separate degraded monitoring-readiness status and does not claim scheduler/worker
continuity.

## Baseline limitations

The September 8, 2026 audit established process and endpoint symptoms but did not
measure worldwide recall. The versioned case set in
`evaluation/reference_cases.v1.json` records the denominator, source links, expected
behavior, and matching rules. A replayable numerator remains a release prerequisite;
the case set must not be described as a recall score until the adapters and stored
projection are replayed against it.

## Migration strategy

1. Preserve immutable source snapshots and append-only normalized observations.
2. Resolve identities through application-owned hazard policies and persist links,
   assignments, and policy versions.
3. Materialize a query projection with source age, lifecycle state, geometry meaning,
   coverage status, provider-attempt outcomes, and a monotonically versioned snapshot
   token.
4. Serve API/UI reads from that projection; keep upstream calls in scheduler/worker
   processes only.
5. Retain the bounded live path only as an explicit development fallback. It may not
   report durable continuity or hide failed monitoring components.
