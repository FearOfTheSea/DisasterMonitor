# Current-disaster reporting

This page describes the bounded current-disaster path. See [agent-runtime.md](agent-runtime.md)
for execution limits, [disaster-capabilities.md](disaster-capabilities.md) for coverage,
and [capability-status.md](capability-status.md) for release evidence.

## Flow

1. Normalize one disaster, explicit geographic scope (country or worldwide), information
   need, output mode, and optional event discriminators.
2. Select registry-approved providers. Unsupported combinations return
   `current_disaster_coverage_unavailable` without a factual model response.
3. Discover and select a physical event using deterministic, disaster- and country-safe
   policy. Ambiguous events remain separate and are disclosed.
4. Retrieve eligible situation evidence and preserve provider failures independently.
5. Reconcile observations into canonical temporal evidence. Revisions, conflicts,
   omissions, freshness, and provenance remain explicit; missing is not zero.
6. Render a deterministic report with source metadata, sections, gaps, warnings, and
   retrieval time.

Default tool sequence:

```text
list_sources_for_task
find_disaster_event
retrieve_situation_evidence
reconcile_disaster_evidence
compose_disaster_answer
```

The parser routes recognized current-event questions, including “news” requests, to
this path. Explicit worldwide requests use the same normalized-task and capability
selection path as named-country requests, without inventing a country. Worldwide
ranking and wording are supplied by the selected disaster policy; the result is limited
to event discovery, not global impact coverage.

## Evidence and authority

Provider registrations declare a primary or secondary tier for each role and geographic
scope. The registry rejects multiple configured primaries for one authority key and
queries both tiers in explicit precedence order. When observations resolve to one
physical event, primary metadata is canonical where present; secondary observations,
measurements, corroboration, and conflicts remain retained with provenance. A valid
secondary-only event is still usable when the primary returns no matching observation.
Official and scientific sources outrank supplementary reports. Every fact retains its
source, stable ID, canonical URL, event ID when available, and source/retrieval times.
Same-source corrections supersede the current projection but do not erase history.
Cross-source disagreement remains a conflict. Provider text is bounded and sanitized;
the renderer does not infer damage from magnitude, intensity, or bulletin absence.

Executable registrations are assembled from provider-family builders. The maintained
source catalog remains a separate artifact, so startup consistency checks still detect
source identity, configuration, allowed-host, role, and executable-registration drift
instead of validating one structure against itself.

Hypotheses, triage, decision support, specialist coordination, multimodal observations,
and contextual media are typed artifacts. They cannot create verified facts, expand
source authority, issue public warnings, or select events.

## Providers

- EMSC SeismicPortal and USGS provide bounded named-country and worldwide scientific
  earthquake discovery. EMSC is secondary corroboration and can share an originating
  network with USGS, so agreement is not automatically independent confirmation.
- GDACS provides bounded named-country and worldwide tropical-cyclone discovery.
- NOAA IBTrACS optionally reconciles one active track after a GDACS cyclone is selected.
  It requires a unique non-generic name, onset, and track-proximity match, remains
  provisional, and is not an independent live-event authority because its agency
  inputs can overlap GDACS.
- NOAA NHC/CPHC optionally attaches exact forecast-track and cone-of-uncertainty KMZ
  layers after a GDACS cyclone is selected. It requires one unique active name and
  source-center proximity match and covers only active Atlantic, Eastern North Pacific,
  and Central North Pacific advisories. These layers remain separate from event
  geometry and are not observed footprints, wind fields, warnings, or impact forecasts.
- GDACS also provides secondary named-country and worldwide discovery for floods,
  wildfires, and volcanic eruptions. Flood records retain GloFAS/FloodList lineage and
  overlap the Copernicus/EC-JRC family used by GFM; wildfire records retain GWIS
  lineage and are downstream of FIRMS; volcano records retain their VAAC label and are
  downstream of VAA/Smithsonian reporting. Agreement within those families is not
  treated as independent corroboration. GFM/GDACS floods, EONET/GDACS wildfires, and
  Smithsonian-USGS/GDACS eruptions are reconciled only by exact maintained source-pair
  rules with conservative source-backed time and point-distance gates; uncertain or
  merely nearby observations remain separate.
- CEMS Global Flood Monitoring (GFM) provides primary bounded named-country and
  worldwide flood discovery after country-clipped or bounded-footprint Observed Flood
  Extent class-1 statistics confirm nonzero flood pixels.
- NASA EONET Wildfires provides primary bounded named-country and worldwide wildfire
  event discovery from NASA-curated EONET metadata. It remains secondary evidence
  authority: EONET geometry and temporal extents can be approximate, its curation
  applies a material-size threshold, and it is not an official incident-perimeter
  source.
- NASA FIRMS optionally adds aggregated VIIRS thermal-anomaly observations after a
  wildfire with a source-backed point is selected. It requires `NASA_FIRMS_MAP_KEY`,
  remains possible-correlation satellite evidence, and never discovers events or
  creates one event per hotspot. Antimeridian-crossing circles use two bounded area
  requests with global deduplication and one shared 500-observation ceiling. Because
  GDACS WF is downstream of GWIS/FIRMS, the two do not count as independent
  corroboration.
- NASA COOLR Landslides provides primary bounded named-country and worldwide landslide
  event discovery from the COOLR report catalogue. Runtime evidence remains secondary;
  accepted reports are restricted to the documented GLC and LRC import classes, and
  the catalogue is not complete real-time surveillance.
- Copernicus EMS Rapid Mapping adds sparse secondary landslide map evidence only after
  selection. It requires an EMSR Mass movement activation plus conservative country,
  time, centroid, and delivered feasible DEL/GRA checks. EMSN risk assessments and
  activation-only claims are excluded.
- Smithsonian/GVP provides bounded named-country and worldwide volcanic-eruption
  discovery from explicit WVAR eruptive-activity report types, with source-backed GVP
  identity and point geometry. It does not admit unrest or other observations and is
  not comprehensive global eruption surveillance.
- ReliefWeb is an optional, configured supplementary situation-evidence provider for
  named-country requests; without `RELIEFWEB_APP_NAME`, it remains unavailable and
  reports disclose that gap.

NASA LHASA was evaluated but is not registered. Its semantics fit estimated
`analytical_model` likelihood only, never confirmed occurrence, and the official
machine-readable serving paths were unavailable or explicitly best-effort with frequent
downtime during the 2026-08-24 check. The source playbook records the blocker and the
smallest prerequisite for a future bounded integration.

See [docs/sources](sources/) for source-specific limits and tests. Event-associated
photos are a separate presentation feature documented in [event-media.md](event-media.md).
Event discovery from these providers does not establish casualties, impacts, warnings,
or response status; those claims remain in the separate situation-evidence and
reconciliation workflow.

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

Default tests use deterministic fixtures and do not require network access, Ollama, or
cloud credentials. The optional live smoke test is:

```powershell
uv run --project apps/api python scripts/live_disaster_smoke.py
```
