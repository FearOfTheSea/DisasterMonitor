# Disaster source capabilities

Disaster Monitor parses a recognized current-disaster request into one typed disaster
and an explicit geographic scope (one canonical country or worldwide), then selects
providers by declared capability. Event
verification and situation evidence are separate roles: an event can be verified even
when no impact source supports it. If no event provider supports the combination, the
API returns `current_disaster_coverage_unavailable` and makes no live factual claim.

The provider matrix records implemented live source coverage only. It is separate
from automated and normative promotion status; see
[Capability and promotion status](capability-status.md).

A versioned source-intelligence catalog links every executable provider to a stable
`source_id`, exact HTTPS authorities, and a maintained playbook under `docs/sources/`.
Source listing joins this semantic metadata with capability selection; catalog data
never dynamically imports or constructs providers.

## Current live capability matrix

| Provider                                           | Tier      | Role                                         | Disasters                                                                   | Scope                                           | Additional requirement                                                        |
| -------------------------------------------------- | --------- | -------------------------------------------- | --------------------------------------------------------------------------- | ----------------------------------------------- | ----------------------------------------------------------------------------- |
| CEMS Global Flood Monitoring (GFM)                 | Primary   | Event discovery                              | Flood                                                                       | Named countries and worldwide                   | Country-clipped class-1 `ensemble_flood_extent` statistics                    |
| GDACS floods                                       | Secondary | Event discovery                              | Flood                                                                       | Named countries and worldwide                   | GloFAS/FloodList-derived curated events; centroid only                        |
| EMSC SeismicPortal                                 | Secondary | Event discovery and scientific corroboration | Earthquake                                                                  | Named countries and worldwide                   | Maintained-country validation; CC BY 4.0 FDSN event data                      |
| USGS                                               | Secondary | Event discovery                              | Earthquake                                                                  | Named countries and worldwide                   | Country validation for named scope                                            |
| NASA EONET Wildfires                               | Primary   | Event discovery                              | Wildfire                                                                    | Named countries and worldwide                   | EONET geometry and maintained-country validation                              |
| GDACS wildfires                                    | Secondary | Event discovery                              | Wildfire                                                                    | Named countries and worldwide                   | GWIS-derived event curation; FIRMS-dependent upstream                         |
| NASA FIRMS observations                            | Secondary | Satellite observation                        | Wildfire                                                                    | Selected named-country or worldwide event       | `NASA_FIRMS_MAP_KEY`; exact event point; aggregated possible correlation only |
| NASA COOLR Landslides                              | Primary   | Event discovery                              | Landslide                                                                   | Named countries and worldwide                   | COOLR point and maintained-country validation                                 |
| Copernicus EMS Rapid Mapping landslides            | Secondary | Mapping evidence                             | Landslide                                                                   | Selected named-country or worldwide event       | EMSR Mass movement; time/centroid match; delivered feasible DEL/GRA product   |
| GDACS tropical cyclones                            | Secondary | Event discovery                              | Tropical cyclone                                                            | Named countries and worldwide                   | None                                                                          |
| NOAA IBTrACS track reconciliation                  | Secondary | Scientific verification and map layers       | Tropical cyclone                                                            | Selected GDACS named-country or worldwide event | Unique name/start/track match against v04r01 active subset                    |
| NOAA NHC/CPHC cyclone forecasts                    | Primary   | Operational forecast map layers               | Tropical cyclone                                                            | Selected GDACS named-country or worldwide event | Active Atlantic/Eastern/Central Pacific product; unique name/center match     |
| Smithsonian / USGS Weekly Volcanic Activity Report | Primary   | Event discovery                              | Volcanic eruption                                                           | Named countries and worldwide                   | Explicit WVAR eruptive-activity classification and day-precise start          |
| GDACS volcanic eruptions                           | Secondary | Event discovery                              | Volcanic eruption                                                           | Named countries and worldwide                   | VAA/Smithsonian-derived event records; volcano point only                     |
| ReliefWeb                                          | Secondary | Situation evidence                           | Earthquake, flood, wildfire, landslide, tropical cyclone, volcanic eruption | Named countries                                 | `RELIEFWEB_APP_NAME`                                                          |

## Active Incidents surface

`GET /api/v1/incidents` exposes a non-LLM, provider-backed view across all six
`Disaster` values. The initial page load uses a 7-day window and a limit of 10 records
per disaster; callers may request 1-30 days and 1-20 records per disaster. Retrievals
run concurrently, retain only admissible source evidence from the highest provider tier
that returned usable records for each disaster, and sort the combined result newest
first. The response preserves event and provider identifiers, provider tier, source
authority, timestamps, measurements, canonical source links, and exact source-backed
point, track, or area geometry.

Coverage is reported independently for every disaster as `events_found`,
`no_matching_records`, `degraded`, or `unavailable`. `no_matching_records` means the
configured providers completed successfully without a usable match; it is not evidence
that no event occurred. `degraded` keeps partial usable records while disclosing a
provider or evidence-policy failure. `unavailable` means no configured worldwide event
provider can execute for that disaster. Provider failures therefore do not erase
healthy hazards or turn uncertainty into a factual incident claim.

The sidebar and its permanent OpenLayers Active Incidents layer use only this response.
Records without usable geometry remain visible in the list but are not mapped. The map
does not infer a centroid, bounding box, polygon, severity, casualty count, impact, or
warning. This surface is bounded event discovery, not complete global surveillance,
continuous polling, incident management, or proof of current operational impact; the
assistant and report-selection workflows remain separate.

### Compound Hazard Correlation v1

The Active Incidents response also carries a bounded, deterministic `correlations`
collection after provider evidence admission and per-hazard physical-event resolution.
It never changes event identity, provider precedence, evidence status, event selection,
or coverage. A correlation is only a `spatiotemporal_association` between two already
distinct records:

- earthquake → landslide: source-backed points no more than 150 km apart, with the
  landslide at or after the earthquake and no more than 72 hours later; and
- tropical cyclone ↔ flood: source-backed points no more than 300 km apart and no more
  than 72 hours apart in either temporal direction.

No other pair is admitted in v1. Area, track, descriptive, missing, or inferred
representative geometry is not converted to a point. Stable physical-event IDs are
used when available; otherwise the existing source ID and event ID provide a
source-qualified participant identity. Pair IDs and ordering are input-order
independent, reversed pairs are deduplicated, and no transitive cluster is synthesized.
Spatial and temporal proximity does not establish causation. The absence of a
correlation is not evidence that hazards are unrelated or independent.

## Incident Watches

Incident Watch v1 provides persistent, local, bounded monitoring for exactly one
supported disaster type and either one canonical named country or worldwide scope.
The API supports create, list, enable/disable, delete, newest-first timeline, and
timeline-read operations under `/api/v1/incident-watches`. The Evidence operations
panel shows the scope, enabled state, last check, current coverage, unread count, and
source-backed timeline. A timeline event is mapped only when its retained provider
evidence contains usable point, track, or area geometry.

Enabled watches are refreshed by the existing scheduler and worker queue. Each refresh
uses the same provider registry, event-discovery adapters, provider tiers, provenance
validation, physical-event equivalence, bounded result limits, and coverage semantics
as current disaster reporting and Active Incidents. No model decides whether evidence
changed or whether an in-app alert exists. Deterministic typed-state hashes classify a
new physical event, an observation gap, measurement or geometry changes, event/source
evidence-set changes, and coverage transitions. Replaying the same normalized evidence
does not create duplicate changes or unread alerts.

`no_matching_records` remains a successful bounded lookup with no usable match and is
never rendered as “no disaster.” If a previously observed event is absent from such a
result, the timeline calls this an observation gap and explicitly does not claim the
event ended. Provider failure, stale evidence, degraded coverage, and unavailable
coverage remain distinct. Failed or stale observations may change coverage but do not
replace the last successful comparison baseline.

PostgreSQL operations storage makes watches, normalized observations, changes, and read
state durable. The in-memory operations repository provides matching deterministic
semantics for tests and standalone development but does not survive restart. Incident
Watches are in-app monitoring only: they are not complete global surveillance, public
warnings, browser/OS push, email/SMS delivery, evacuation directives, or resource
orders.

GFM provides primary global named-country and bounded countryless worldwide flood
event discovery. EMSC and USGS provide global named-country and countryless worldwide
earthquake event discovery, while GDACS provides that scope for tropical cyclones.
EMSC is an aggregated scientific catalogue, so a record shared with a contributing
network represented by USGS is not counted as independent corroboration. NASA EONET is a curated
secondary wildfire registry and NASA COOLR is a secondary landslide report catalogue;
both are bounded event-discovery paths, not complete global surveillance or official
incident/impact authorities. EONET applies material-size curation and can have
approximate spatial and temporal extents. COOLR combines documented report sources,
including GLC and LRC, and retains geographic and reporting biases. A missing record
from either source is not evidence that the disaster did not occur.
Copernicus EMS Rapid Mapping can add sparse landslide map evidence after COOLR selects
an event. An EMSR activation must pass country, time, centroid, and delivered feasible
DEL/GRA product checks. EMSN risk/preparedness products are excluded, activation alone
does not confirm occurrence, and an absent activation says nothing about occurrence.
GDACS FL, WF, and VO provide fallback secondary discovery. Their upstream lineage is
material: FL overlaps the Copernicus/EC-JRC family used by GFM, WF is produced by GWIS
from FIRMS detections, and VO summarizes VAA and Smithsonian reporting. These records
remain distinct observations but do not create independent-source counts. Exact
GFM/GDACS, EONET/GDACS, and Smithsonian-USGS/GDACS source pairs may be assigned to one
physical event only when their typed time and point geometry satisfy conservative
hazard-specific gates; nearby observations outside those gates remain separate.
NOAA IBTrACS does not add a second live tropical-cyclone feed. It is queried only after
GDACS selects a cyclone and attaches one active track only when name, onset, and track
proximity uniquely reconcile identity. Its agency inputs can overlap GDACS, so the
matched track is not independent event corroboration and all active points remain
provisional. The selected-event API exposes those exact timestamped points only as a
separate `provisional_track` layer, never as event-occurrence or forecast geometry.
NOAA NHC/CPHC is independently queried for operational map context after selection. It
supports exact KMZ forecast positions and the official cone polygon for active storms
in the Atlantic, Eastern North Pacific, and Central North Pacific. One active advisory
must uniquely match the GDACS source name and have a published center within 500 km.
Zero or multiple matches fail closed. Forecast-track points retain their validity
times; the cone retains its advisory validity interval. Wind-field shapefiles are not
admitted and missing cones or wind radii are never inferred. The cone is forecast
track-center uncertainty, not storm size, wind extent, an impact boundary, or an
observed footprint. NHC/CPHC can also be upstream of GDACS, so this context does not
become independent corroboration.
`country_codes=None` permits every admitted named country only with the explicit country
scope; worldwide requests require the explicit worldwide scope. News requests are
deterministically routed to event discovery. Country names remain case-insensitive,
while short ISO codes are uppercase-only to avoid collisions with ordinary language in
the global alias set. ReliefWeb is supplementary situation evidence only and is selected
for named-country requests when configured; otherwise reports disclose the missing
impact, casualty, warning, and response coverage.

Explicit worldwide, global, or across-the-world requests use a bounded worldwide
provider query and the selected disaster policy. Earthquake policy selects the latest
event by default or the strongest event when requested; other disasters use the shared
latest policy unless they register another policy. Worldwide requests do not invent a
country for offshore events. Worldwide scope provides bounded event discovery plus
narrowly selected-event FIRMS, Copernicus mapping, IBTrACS, or NHC/CPHC forecast
evidence where eligible.
It does not provide globally complete casualty, damage, warning, or response evidence,
and every response states that gap.

Smithsonian/GVP WVAR provides bounded volcanic-eruption discovery from its explicit
`New Eruptive Activity` and `Continuing Eruptive Activity` classifications, enriched
with GVP volcano identity, geography, and eruption metadata. It is preliminary and
not comprehensive; unrest and other observations remain outside the eruption event
definition.

The API accepts bounded operator-supplied PNG/JPEG bytes with explicit provenance and
event metadata. Associated images may produce local analytical observations and a
typed vector COP; this request boundary is not a live provider and does not alter the
catalog above. Separately, the assistant can display bounded contextual source photos
associated with the already-selected event. That gallery uses exact registered page and
asset hosts and remains outside the provider/evidence matrix. Analytical or arbitrary
satellite/aerial image retrieval, official-warning overlay providers, CARTO, TerraLabo,
and open-ended source crawling remain unsupported. GFM uses official server-side
statistics only for flood event discovery and does not expose raster products as
general imagery. Configured NASA FIRMS observations are a narrow, non-imagery
exception: one allowlisted VIIRS product is queried in a bounded area around an
already selected wildfire point, then aggregated as possible observation evidence.
Searches that cross the antimeridian use two area requests, snapshot both responses,
deduplicate before applying one global 500-observation ceiling, and retain the exact
50 km distance filter.
It cannot discover events, expose arbitrary imagery, define a perimeter, or create one
event per hotspot. Structured
source-candidate metadata can be screened into a separate review queue, but it cannot
alter this matrix or contribute evidence. See
[Event-associated source media](event-media.md).

NASA LHASA was evaluated for post-selection `analytical_model` hazard/likelihood
evidence and was not integrated. Its official runtime paths were unavailable or
best-effort with documented frequent downtime during evaluation. A model value would
never be occurrence confirmation. See
[NASA LHASA integration evaluation](sources/nasa-lhasa-evaluation.md).

Triage, advisory decision support, deterministic specialist coordination, and governed
analytical follow-up ordering are implemented over admitted evidence. They do not add
provider coverage and cannot issue public warnings, evacuation directives, or resource
orders.

## Extension procedure

To add a provider, implement the relevant application port in a focused infrastructure
adapter, translate records into domain types with typed source authority, and add one
`ProviderRegistration` in the composition root with role, disasters, country scope,
configuration state, and any selected-event predicate. Add selector, adapter, failure,
and exclusion tests. Generic orchestration should not change.

To add disaster behavior, register a policy implementing ranking, physical-event
equivalence, sequence handling, and ambiguity. Add a report profile only when the
disaster needs sections beyond the generic human impact, physical/infrastructure impact,
emergency response, gaps, sources, and freshness sections.

All disaster policies produce the same generic `PhysicalEventIdentity` contract. They
must preserve normalized observations and deterministic assignment rationale, enforce
disaster/country boundaries, and leave non-transitive or otherwise confusable assignment
sets explicit. Temporal evidence and hypotheses are disaster-neutral artifacts; a
disaster-specific rule may be added only as application policy over canonical evidence,
never inside provider transport.

## Geography metadata

The packaged fallback records three preservation countries. The autonomous updater
generates a content-versioned global catalog from a released Natural Earth 1:50m Admin
0 revision and the latest validated IANA tzdata archive. It retains source revisions,
checksums, licenses, canonical names, unambiguous aliases, query bounds, simplified
polygons, and deterministic default timezones. Polygons are query approximations, not
legal borders or maritime claims. See
[Autonomous country catalog updates](country-catalog-automation.md).
