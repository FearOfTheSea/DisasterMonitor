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

| Provider                           | Tier      | Role               | Disasters        | Scope                         | Additional requirement                                      |
| ---------------------------------- | --------- | ------------------ | ---------------- | ----------------------------- | ----------------------------------------------------------- |
| CEMS Global Flood Monitoring (GFM) | Primary   | Event discovery    | Flood            | Named countries and worldwide | Country-clipped class-1 `ensemble_flood_extent` statistics |
| USGS                              | Secondary | Event discovery    | Earthquake       | Named countries and worldwide | Country validation for named scope                         |
| NASA EONET Wildfires              | Primary   | Event discovery    | Wildfire         | Named countries and worldwide | EONET geometry and maintained-country validation            |
| NASA COOLR Landslides             | Primary   | Event discovery    | Landslide        | Named countries and worldwide | COOLR point and maintained-country validation               |
| GDACS tropical cyclones           | Secondary | Event discovery    | Tropical cyclone | Named countries and worldwide | None                                                        |
| Smithsonian / USGS Weekly Volcanic Activity Report | Primary | Event discovery | Volcanic eruption | Named countries and worldwide | Explicit WVAR eruptive-activity classification and day-precise start |
| ReliefWeb                         | Secondary | Situation evidence | Earthquake, flood, wildfire, landslide, tropical cyclone, volcanic eruption | Named countries | `RELIEFWEB_APP_NAME` |

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

GFM provides primary global named-country and bounded countryless worldwide flood
event discovery. USGS and GDACS provide global named-country and countryless worldwide
event discovery for earthquakes and tropical cyclones. NASA EONET is a curated
secondary wildfire registry and NASA COOLR is a secondary landslide report catalogue;
both are bounded event-discovery paths, not complete global surveillance or official
incident/impact authorities. EONET applies material-size curation and can have
approximate spatial and temporal extents. COOLR combines documented report sources,
including GLC and LRC, and retains geographic and reporting biases. A missing record
from either source is not evidence that the disaster did not occur.
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
country for offshore events. Worldwide scope currently provides event
discovery only; it does not provide globally complete
casualty, damage, warning, or response evidence, and every response states that gap.

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
general imagery. Structured
source-candidate metadata can be screened into a separate review queue, but it cannot
alter this matrix or contribute evidence. See
[Event-associated source media](event-media.md).

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
