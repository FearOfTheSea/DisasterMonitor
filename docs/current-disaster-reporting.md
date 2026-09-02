# Current-disaster reporting

This page describes the bounded current-disaster path. See
[agent-runtime.md](agent-runtime.md) for limits,
[disaster-capabilities.md](disaster-capabilities.md) for coverage, and
[capability-status.md](capability-status.md) for release evidence.

## Flow

1. Normalize one disaster, one explicit geographic scope, one information need,
   one output mode, and optional event discriminators.
2. Select registry-approved providers. Return
   `current_disaster_coverage_unavailable` for unsupported combinations without a
   factual model response.
3. Discover and select a physical event with deterministic disaster- and
   country-safe policy. Keep ambiguous events separate and disclose them.
4. Retrieve eligible situation evidence. Preserve provider failures independently.
5. Reconcile observations into canonical temporal evidence. Keep revisions,
   conflicts, omissions, freshness, and provenance explicit. Treat missing as
   unknown, not zero.
6. Render a deterministic report with source metadata, sections, gaps, warnings,
   and retrieval time.

The default tool sequence is:

```text
list_sources_for_task
find_disaster_event
retrieve_situation_evidence
reconcile_disaster_evidence
compose_disaster_answer
```

The parser routes recognized current-event questions, including “news” requests,
to this path.

Explicit worldwide requests use the same normalized-task and capability-selection
path as named-country requests. They do not invent a country.

Worldwide ranking and wording come from the selected disaster policy. The result
provides event discovery, not global impact coverage.

## Evidence and authority

Provider registrations declare a primary or secondary tier for each role and scope.
The registry rejects multiple configured primaries for one authority key.

The runtime queries both tiers in explicit precedence order. When observations resolve
to one physical event, primary metadata is canonical when present.

Secondary observations, measurements, corroboration, and conflicts remain retained
with provenance. A valid secondary-only event remains usable when the primary returns
no matching observation.

Official and scientific sources outrank supplementary reports. Each fact retains its
source, stable ID, canonical URL, event ID when available, and source and retrieval
times.

Same-source corrections supersede the current projection but do not erase history.
Cross-source disagreement remains a conflict.

Provider text is bounded and sanitized. The renderer does not infer damage from
magnitude, intensity, or bulletin absence.

Executable registrations come from provider-family builders. The maintained source
catalog remains a separate artifact.

Startup consistency checks detect source identity, configuration, allowed-host, role,
and executable-registration drift. They do not validate one structure against itself.

Hypotheses, triage, decision support, specialist coordination, multimodal
observations, and contextual media are typed artifacts.

These artifacts cannot create verified facts, expand source authority, issue public
warnings, or select events.

The NOAA/NWS weather-alert layer is another separate typed artifact. Its dedicated
port and endpoint retain official CAP warning semantics, exact supplied polygons,
and explicit United States coverage state.

It is not registered for physical-event discovery or situation evidence. It cannot
become an `ActiveIncident` or enter event reconciliation, selection, or
compound-hazard correlation.

See [noaa-nws-weather-alerts.md](sources/noaa-nws-weather-alerts.md).

## Providers

- EMSC SeismicPortal and USGS provide bounded named-country and worldwide scientific
  earthquake discovery. EMSC is secondary corroboration and can share an originating
  network with USGS. Agreement is not automatically independent confirmation.
- GDACS provides bounded named-country and worldwide tropical-cyclone discovery.
- NOAA IBTrACS can reconcile one active track after GDACS selects a cyclone. It
  requires a unique non-generic name, onset, and track-proximity match. It remains
  provisional and is not an independent live-event authority because agency inputs
  can overlap GDACS.
- NOAA NHC/CPHC can attach exact forecast-track and cone-of-uncertainty KMZ layers
  after GDACS selects a cyclone. It requires one unique active name and source-center
  proximity match. It covers only active Atlantic, Eastern North Pacific, and Central
  North Pacific advisories.
- NHC/CPHC layers remain separate from event geometry. They are not observed
  footprints, wind fields, warnings, or impact forecasts.
- GDACS also provides secondary named-country and worldwide discovery for floods,
  wildfires, and volcanic eruptions. Flood records retain GloFAS/FloodList lineage
  and overlap the Copernicus/EC-JRC family used by GFM. Wildfire records retain GWIS
  lineage and are downstream of FIRMS. Volcano records retain their VAAC label and
  are downstream of VAA/Smithsonian reporting.
- Agreement within those source families is not independent corroboration.
  GFM/GDACS floods, EONET/GDACS wildfires, and Smithsonian-USGS/GDACS eruptions use
  exact maintained source-pair rules with conservative time and point-distance gates.
  Uncertain or nearby observations remain separate.
- CEMS Global Flood Monitoring (GFM) provides primary bounded named-country and
  worldwide flood discovery. Country-clipped or bounded-footprint Observed Flood
  Extent class-1 statistics must confirm nonzero flood pixels.
- NASA EONET Wildfires provides primary bounded named-country and worldwide wildfire
  discovery from NASA-curated EONET metadata. EONET remains secondary evidence
  authority. Its geometry and temporal extents can be approximate, and its curation
  applies a material-size threshold.
- NASA EONET is not an official incident-perimeter source.
- NASA FIRMS can add aggregated VIIRS thermal-anomaly observations after a wildfire
  with a source-backed point is selected. It requires `NASA_FIRMS_MAP_KEY` and remains
  possible-correlation satellite evidence.
- FIRMS never discovers events or creates one event per hotspot. Antimeridian-crossing
  circles use two bounded area requests with global deduplication and one shared
  500-observation ceiling.
- GDACS WF is downstream of GWIS/FIRMS. GDACS and FIRMS therefore do not count as
  independent corroboration.
- NASA COOLR Landslides provides primary bounded named-country and worldwide
  landslide discovery from the COOLR report catalogue. Runtime evidence remains
  secondary. Accepted reports use only the documented GLC and LRC import classes.
  The catalogue is not complete real-time surveillance.
- Copernicus EMS Rapid Mapping adds sparse secondary landslide map evidence after
  selection. It requires an EMSR Mass movement activation plus conservative country,
  time, centroid, and delivered feasible DEL/GRA checks. EMSN risk assessments and
  activation-only claims are excluded.
- Smithsonian/GVP provides bounded named-country and worldwide volcanic-eruption
  discovery from explicit WVAR eruptive-activity report types, with source-backed GVP
  identity and point geometry. It does not admit unrest or other observations and is
  not comprehensive global eruption surveillance.
- ReliefWeb is an optional configured supplementary situation-evidence provider for
  named-country requests. Without `RELIEFWEB_APP_NAME`, it remains unavailable and
  reports disclose that gap.

NASA LHASA was evaluated but is not registered. Its semantics fit estimated
`analytical_model` likelihood only, never confirmed occurrence.

The official machine-readable serving paths were unavailable or explicitly
best-effort with frequent downtime during the 2026-08-24 check. The source playbook
records the blocker and the smallest prerequisite for a future integration.

See [docs/sources](sources/) for source-specific limits and tests. Event-associated
photos are a separate presentation feature documented in [event-media.md](event-media.md).

Event discovery does not establish casualties, impacts, warnings, or response status.
Those claims remain in the situation-evidence and reconciliation workflow.

## Configuration and checks

Adapters use `apps/api/.env` or the process environment:

```text
DISASTER_PROVIDER_TIMEOUT_SECONDS=10
DISASTER_PROVIDER_MAX_RESPONSE_BYTES=1000000
# Optional approved ReliefWeb application name. Leave unset to disable it.
# RELIEFWEB_APP_NAME=
# Optional free NASA FIRMS API map key. Leave unset to disable observations.
# NASA_FIRMS_MAP_KEY=
```

Default tests use deterministic fixtures. They do not require network access,
Ollama, or cloud credentials.

Run the optional live smoke test with:

```powershell
uv run --project apps/api python scripts/live_disaster_smoke.py
```
