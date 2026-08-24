# NASA FIRMS thermal-anomaly observations

NASA FIRMS is optional, event-associated satellite observation evidence for wildfires.
It is deliberately not an event-discovery provider. The adapter runs only after a
wildfire has been selected from EONET or GDACS and only when that event has an exact
source-backed point. It never creates one event per hotspot.

The official FIRMS Area CSV API requires a free `MAP_KEY`. DisasterMonitor queries the
global `VIIRS_SNPP_NRT` product for a three-day window and a bounding box around the
selected point. When the 50 km search circle crosses the antimeridian, the adapter
issues exactly two valid area requests, one on each longitude side. Both successful
payloads are snapshotted, responses are merged in request order, exact duplicate
detections are removed, and the distance check is applied after merging. At most 500
detections are admitted across the complete search. They are aggregated into one
`possible`-correlation situation record with a preliminary count and observation
interval. No individual pixel becomes a physical-event identity, perimeter, ignition
point, or confirmed fact.

FIRMS provides satellite fire and thermal anomaly pixels, generally within hours of
overpass. A detection can represent a small intense source or a larger cooler source
within the sensor pixel, including industrial or other non-wildfire heat sources.
Polar-orbiting coverage is not continuous; clouds, overpass timing, fire intensity,
resolution, and processing can produce gaps. Cumulative detections can overstate a
fire’s area and do not align with official perimeters.

The MAP key is used only in the bounded request path. It is excluded from canonical
source URLs, snapshot request identities, diagnostics, and normalized evidence. Source
links use the public FIRMS map. Payload snapshots use rights identifier
`nasa-earth-science-data-use`.

GDACS WF is downstream of JRC GWIS, which uses NASA FIRMS MODIS/VIIRS detections.
Therefore a GDACS event plus nearby FIRMS pixels is not independent corroboration.
The observations also do not establish impacts, warnings, evacuations, containment,
damage, casualties, or response status.

Configuration:

```text
NASA_FIRMS_MAP_KEY=<free FIRMS map key>
```

Without the key the provider is registered but unavailable, makes no network request,
and is disclosed as a configuration gap. Deterministic tests cover configuration,
secret non-disclosure, bounded geometry, distance filtering, aggregation, possible
correlation, wrong-disaster exclusion, missing geometry, snapshots, and source policy.
The 2026-08-24 validation environment had no `NASA_FIRMS_MAP_KEY`, so a live Area API
behavior check could not be executed without obtaining new external credentials. The
smallest prerequisite is supplying a free NASA FIRMS map key; the fixture-based HTTP
integration and configuration/no-request paths are fully validated.

References checked 2026-08-24:

- `https://firms.modaps.eosdis.nasa.gov/api/area/`
- `https://firms.modaps.eosdis.nasa.gov/content/academy/data_api/firms_api_use.html`
- `https://wiki.earthdata.nasa.gov/spaces/FIRMS/pages/32079892/Fire+Information+for+Resource+Management+System+FIRMS`
- `https://www.earthdata.nasa.gov/faq/firms-faq`
