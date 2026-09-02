# NASA FIRMS thermal-anomaly observations

NASA FIRMS is optional, event-associated satellite observation evidence for wildfires.
It is not an event-discovery provider.

Run the adapter only after EONET or GDACS selects a wildfire with an exact
source-backed point.

Never create one event per hotspot.

The official FIRMS Area CSV API requires a free `MAP_KEY`.

DisasterMonitor queries the global `VIIRS_SNPP_NRT` product for three days in a
bounding box around the selected point.

When the 50 km search circle crosses the antimeridian, issue exactly two valid area
requests, one on each longitude side.

Snapshot both successful payloads. Merge them in request order. Remove exact duplicate
detections. Apply the distance check after merging.

Admit at most 500 detections across the complete search.

Aggregate them into one `possible`-correlation situation record with a preliminary
count and observation interval.

No individual pixel becomes a physical-event identity, perimeter, ignition point, or
confirmed fact.

FIRMS provides satellite fire and thermal-anomaly pixels, generally within hours of
overpass.

A detection can represent a small intense source or a larger cooler source within the
sensor pixel. It can also represent industrial or other non-wildfire heat.

Polar-orbiting coverage is not continuous. Clouds, overpass timing, fire intensity,
resolution, and processing can produce gaps.

Cumulative detections can overstate fire area. They do not align with official
perimeters.

Use the MAP key only in the bounded request path. Exclude it from canonical source
URLs, snapshot request identities, diagnostics, and normalized evidence.

Use the public FIRMS map for source links. Payload snapshots use rights identifier
`nasa-earth-science-data-use`.

GDACS WF is downstream of JRC GWIS, which uses NASA FIRMS MODIS/VIIRS detections.
GDACS plus nearby FIRMS pixels are therefore not independent corroboration.

The observations do not establish impacts, warnings, evacuations, containment, damage,
casualties, or response status.

Configuration:

```text
NASA_FIRMS_MAP_KEY=<free FIRMS map key>
```

Without the key, the provider remains registered but unavailable. It makes no network
request and reports a configuration gap.

The smallest prerequisite is a free NASA FIRMS map key.

Fixture-based HTTP integration and configuration or no-request paths are fully
validated.

Deterministic tests cover configuration, secret non-disclosure, bounded geometry,
distance filtering, aggregation, possible correlation, wrong-disaster exclusion,
missing geometry, snapshots, and source policy.

The 2026-08-24 validation environment had no `NASA_FIRMS_MAP_KEY`. A live Area API
behavior check therefore could not run without new external credentials.

References checked 2026-08-24:

- `https://firms.modaps.eosdis.nasa.gov/api/area/`
- `https://firms.modaps.eosdis.nasa.gov/content/academy/data_api/firms_api_use.html`
- `https://wiki.earthdata.nasa.gov/spaces/FIRMS/pages/32079892/Fire+Information+for+Resource+Management+System+FIRMS`
- `https://www.earthdata.nasa.gov/faq/firms-faq`
