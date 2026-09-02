# Disaster source capabilities

Disaster Monitor parses a recognized current-disaster request into one typed
disaster and one explicit scope: a canonical country or worldwide.

It selects providers by declared capability. Event verification and situation
evidence are separate roles. An event can be verified without an impact source.

If no event provider supports the combination, the API returns
`current_disaster_coverage_unavailable` and makes no live factual claim.

The provider matrix records implemented live source coverage. It is separate from
automated and normative promotion status. See
[Capability and promotion status](capability-status.md).

A versioned source-intelligence catalog links each executable provider to a stable
`source_id`, exact HTTPS authorities, and a playbook under `docs/sources/`.

Source listing joins this metadata with capability selection. Catalog data never
dynamically imports or constructs providers.

## Current live capability matrix

| Provider | Tier | Role | Disasters | Scope | Additional requirement |
| -------- | ---- | ---- | --------- | ----- | ---------------------- |
| CEMS Global Flood Monitoring (GFM) | Primary | Event discovery | Flood | Named countries and worldwide | Country-clipped class-1 `ensemble_flood_extent` statistics |
| GDACS floods | Secondary | Event discovery | Flood | Named countries and worldwide | GloFAS/FloodList-derived curated events; centroid only |
| EMSC SeismicPortal | Secondary | Event discovery and scientific corroboration | Earthquake | Named countries and worldwide | Maintained-country validation; CC BY 4.0 FDSN event data |
| USGS | Secondary | Event discovery | Earthquake | Named countries and worldwide | Country validation for named scope |
| NASA EONET Wildfires | Primary | Event discovery | Wildfire | Named countries and worldwide | EONET geometry and maintained-country validation |
| GDACS wildfires | Secondary | Event discovery | Wildfire | Named countries and worldwide | GWIS-derived event curation; FIRMS-dependent upstream |
| NASA FIRMS observations | Secondary | Satellite observation | Wildfire | Selected named-country or worldwide event | `NASA_FIRMS_MAP_KEY`; exact event point; aggregated possible correlation only |
| NASA COOLR Landslides | Primary | Event discovery | Landslide | Named countries and worldwide | COOLR point and maintained-country validation |
| Copernicus EMS Rapid Mapping landslides | Secondary | Mapping evidence | Landslide | Selected named-country or worldwide event | EMSR Mass movement; time/centroid match; delivered feasible DEL/GRA product |
| GDACS tropical cyclones | Secondary | Event discovery | Tropical cyclone | Named countries and worldwide | None |
| NOAA IBTrACS track reconciliation | Secondary | Scientific verification and map layers | Tropical cyclone | Selected GDACS named-country or worldwide event | Unique name/start/track match against v04r01 active subset |
| NOAA NHC/CPHC cyclone forecasts | Primary | Operational forecast map layers | Tropical cyclone | Selected GDACS named-country or worldwide event | Active Atlantic/Eastern/Central Pacific product; unique name/center match |
| Smithsonian / USGS Weekly Volcanic Activity Report | Primary | Event discovery | Volcanic eruption | Named countries and worldwide | Explicit WVAR eruptive-activity classification and day-precise start |
| GDACS volcanic eruptions | Secondary | Event discovery | Volcanic eruption | Named countries and worldwide | VAA/Smithsonian-derived event records; volcano point only |
| ReliefWeb | Secondary | Situation evidence | Earthquake, flood, wildfire, landslide, tropical cyclone, volcanic eruption | Named countries | `RELIEFWEB_APP_NAME` |

## Active Incidents surface

`GET /api/v1/incidents` exposes a non-LLM, provider-backed view across all six
`Disaster` values.

The initial page uses a seven-day window and ten records per disaster. Callers can
request one to 30 days and one to 20 records per disaster.

Retrievals run concurrently. The service retains admissible evidence from the
highest provider tier that returned usable records for each disaster.

The service sorts the combined result newest first. The response preserves event and
provider identifiers, provider tier, source authority, timestamps, measurements,
canonical source links, and exact source-backed point, track, or area geometry.

Coverage is reported for each disaster as `events_found`, `no_matching_records`,
`degraded`, or `unavailable`.

`no_matching_records` means configured providers completed without a usable match. It
does not prove that no event occurred.

`degraded` retains partial usable records and discloses a provider or evidence-policy
failure.

`unavailable` means no configured worldwide event provider can execute for that
disaster.

Provider failures do not erase healthy hazards or convert uncertainty into a factual
incident claim.

The sidebar and permanent OpenLayers Active Incidents layer use only this response.
Records without usable geometry remain in the list but are not mapped.

The map does not infer a centroid, bounding box, polygon, severity, casualty count,
impact, or warning.

This surface provides bounded event discovery. It is not complete global surveillance,
continuous polling, or incident management.

Assistant and report-selection workflows remain separate.

### Compound Hazard Correlation v1

The Active Incidents response includes a bounded deterministic `correlations`
collection. It runs after provider admission and per-hazard physical-event resolution.

Correlation does not change event identity, provider precedence, evidence status, event
selection, or coverage.

A correlation is a `spatiotemporal_association` between two distinct records:

- earthquake → landslide: source-backed points are no more than 150 km apart. The
  landslide occurs at or after the earthquake and no more than 72 hours later.
- tropical cyclone ↔ flood: source-backed points are no more than 300 km apart and
  no more than 72 hours apart in either temporal direction.

No other pair is admitted in v1. Area, track, descriptive, missing, or inferred
representative geometry is not converted to a point.

Use stable physical-event IDs when available. Otherwise use the existing source ID
and event ID as a source-qualified participant identity.

Pair IDs and ordering do not depend on input order. Reversed pairs are deduplicated.
The service does not synthesize a transitive cluster.

Spatial and temporal proximity does not establish causation. The absence of a
correlation does not prove that hazards are unrelated or independent.

## Incident Watches

Incident Watch v1 provides persistent, local, bounded monitoring for one supported
disaster type and one canonical country or worldwide scope.

The API supports create, list, enable/disable, delete, newest-first timeline, and
timeline-read operations under `/api/v1/incident-watches`.

The Evidence operations panel shows scope, enabled state, last check, current
coverage, unread count, and source-backed timeline.

Map a timeline event only when retained provider evidence contains usable point,
track, or area geometry.

The existing scheduler and worker refresh enabled watches. Each refresh uses the same
provider registry, event-discovery adapters, provider tiers, and provenance validation
as current reporting and Active Incidents.
It also uses the same physical-event equivalence, result limits, and coverage semantics.

No model decides whether evidence changed or whether an in-app alert exists.

Deterministic typed-state hashes classify a new physical event, an observation gap,
measurement or geometry changes, event or source evidence-set changes, and coverage
transitions.

Replaying identical normalized evidence does not create duplicate changes or unread
alerts.

`no_matching_records` is a successful bounded lookup without a usable match. Never
render it as “no disaster”.

If a previously observed event is absent, the timeline calls this an observation gap.
It does not claim that the event ended.

Provider failure, stale evidence, degraded coverage, and unavailable coverage remain
distinct.

Failed or stale observations can change coverage. They do not replace the last
successful comparison baseline.

PostgreSQL operations storage makes watches, normalized observations, changes, and
read state durable.

The in-memory operations repository has matching deterministic semantics for tests and
standalone development. It does not survive restart.

Incident Watches are in-app monitoring only. They are not complete global
surveillance, public warnings, browser/OS push, email/SMS delivery, evacuation
directives, or resource orders.

GFM provides primary global named-country and bounded countryless worldwide flood
event discovery.

EMSC and USGS provide global named-country and countryless worldwide earthquake event
discovery. GDACS provides that scope for tropical cyclones.

EMSC is an aggregated scientific catalogue. A record shared with a contributing
network represented by USGS is not independent corroboration.

NASA EONET is a curated secondary wildfire registry. NASA COOLR is a secondary
landslide report catalogue. Both are bounded event-discovery paths, not complete
global surveillance or official incident and impact authorities.

EONET applies material-size curation and can have approximate spatial and temporal
extents. COOLR combines documented report sources, including GLC and LRC, and retains
geographic and reporting biases.

A missing record from either source does not prove that the disaster did not occur.

Copernicus EMS Rapid Mapping can add sparse landslide map evidence after COOLR selects
an event.

An EMSR activation must pass country, time, centroid, and delivered feasible DEL/GRA
product checks.

EMSN risk and preparedness products are excluded. Activation alone does not confirm
occurrence. An absent activation says nothing about occurrence.

GDACS FL, WF, and VO provide fallback secondary discovery.

Their upstream lineage matters. FL overlaps the Copernicus/EC-JRC family used by GFM.
WF is produced by GWIS from FIRMS detections. VO summarizes VAA and Smithsonian
reporting.

These records remain distinct observations. They do not create independent-source
counts.

Match exact GFM/GDACS, EONET/GDACS, and Smithsonian-USGS/GDACS source pairs only when
the source pair is maintained.
Assign one physical event only when typed time and point geometry satisfy the relevant
gates.
Those gates are conservative and hazard-specific.

Nearby observations outside those gates remain separate.

NOAA IBTrACS does not add a second live tropical-cyclone feed. Query it only after
GDACS selects a cyclone.

Attach one active track only when name, onset, and track proximity uniquely reconcile
identity.

Agency inputs can overlap GDACS. The matched track is not independent corroboration.
All active points remain provisional.

Expose selected timestamped points only as a separate `provisional_track` layer. Do
not expose them as event-occurrence or forecast geometry.

NOAA NHC/CPHC provides operational map context after selection. It supports exact KMZ
forecast positions and the official cone polygon for active storms in the Atlantic,
Eastern North Pacific, and Central North Pacific.

One active advisory must uniquely match the GDACS source name. Its published center
must be within 500 km.

Zero or multiple matches fail closed.

Forecast-track points retain validity times. The cone retains its advisory validity
interval.

Do not admit wind-field shapefiles. Never infer missing cones or wind radii.

The cone is forecast track-center uncertainty. It is not storm size, wind extent, an
impact boundary, or an observed footprint.

NHC/CPHC can also be upstream of GDACS. This context is not independent corroboration.

`country_codes=None` permits every admitted named country only with explicit country
scope. Worldwide requests require explicit worldwide scope.

Route news requests deterministically to event discovery.

Country names are case-insensitive. Short ISO codes are uppercase-only to avoid
collisions with ordinary language in the global alias set.

ReliefWeb is supplementary situation evidence for named-country requests when
configured. Otherwise reports disclose missing impact, casualty, warning, and response
coverage.

Explicit worldwide, global, or across-the-world requests use a bounded worldwide
provider query and the selected disaster policy.

Earthquake policy selects the latest event by default or the strongest event when
requested. Other disasters use the shared latest policy unless another policy is
registered.

Worldwide requests do not invent a country for offshore events.

Worldwide scope provides bounded event discovery plus narrowly selected-event FIRMS,
Copernicus mapping, IBTrACS, or NHC/CPHC forecast evidence when eligible.

It does not provide globally complete casualty, damage, warning, or response evidence.
Every response states that gap.

Smithsonian/GVP WVAR provides bounded volcanic-eruption discovery from its explicit
`New Eruptive Activity` and `Continuing Eruptive Activity` classifications.

It enriches records with GVP volcano identity, geography, and eruption metadata.
WVAR is preliminary and not comprehensive.

Unrest and other observations remain outside the eruption event definition.

The API accepts bounded operator-supplied PNG/JPEG bytes with explicit provenance and
event metadata.

Associated images can produce local analytical observations and a typed vector COP.
This request boundary is not a live provider and does not change the catalog.

The assistant can separately display bounded contextual source photos for a selected
event.

The gallery uses exact registered page and asset hosts. It remains outside the
provider and evidence matrix.

Analytical or arbitrary satellite and aerial image retrieval, official-warning overlay
providers, CARTO, TerraLabo, and open-ended source crawling remain unsupported.

GFM uses official server-side statistics only for flood event discovery. It does not
expose raster products as general imagery.

Configured NASA FIRMS observations are a narrow, non-imagery exception. They query
one allowlisted VIIRS product in a bounded area around a selected wildfire point.

Antimeridian searches use two area requests. Snapshot both responses, deduplicate
before one global 500-observation ceiling, and retain the exact 50 km distance filter.

FIRMS cannot discover events, expose arbitrary imagery, define a perimeter, or create
one event per hotspot.

Structured source-candidate metadata can enter a separate review queue. It cannot
change this matrix or contribute evidence.

See [Event-associated source media](event-media.md).

NASA LHASA was evaluated for post-selection `analytical_model` hazard and likelihood
evidence. It was not integrated.

Its official runtime paths were unavailable or best-effort with documented frequent
downtime during evaluation. See
[NASA LHASA integration evaluation](sources/nasa-lhasa-evaluation.md).

Triage, advisory decision support, deterministic specialist coordination, and
governed analytical follow-up ordering operate over admitted evidence.

They do not add provider coverage. They cannot issue public warnings, evacuation
directives, or resource orders.

## Extension procedure

To add a provider, implement the relevant application port in a focused infrastructure
adapter.

Translate records into domain types with typed source authority.

Add one `ProviderRegistration` in the composition root with role, disasters, country
scope, configuration state, and any selected-event predicate.

Add selector, adapter, failure, and exclusion tests. Do not change generic
orchestration.

To add disaster behavior, register a policy that implements ranking, physical-event
equivalence, sequence handling, and ambiguity.

Add a report profile only when the disaster needs extra sections.
The default sections cover human impact, physical or infrastructure impact, emergency
response, gaps, sources, and freshness.

All disaster policies produce the same generic `PhysicalEventIdentity` contract.

Preserve normalized observations and deterministic assignment rationale. Enforce
disaster and country boundaries. Keep non-transitive or confusable assignment sets
explicit.

Keep temporal evidence and hypotheses disaster-neutral. Add disaster-specific rules
only as application policy over canonical evidence, never inside provider transport.

## Geography metadata

The packaged fallback records three preservation countries.

The autonomous updater generates a content-versioned global catalog from a released
Natural Earth 1:50m Admin 0 revision and the latest validated IANA tzdata archive.

It retains source revisions, checksums, licenses, canonical names, unambiguous aliases,
query bounds, simplified polygons, and deterministic default timezones.

Polygons are query approximations. They are not legal borders or maritime claims. See
[Autonomous country catalog updates](country-catalog-automation.md).
