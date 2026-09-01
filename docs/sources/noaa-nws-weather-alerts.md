# NOAA/NWS authoritative weather alerts

NOAA's National Weather Service publishes active Common Alerting Protocol (CAP)
records through the official Weather.gov API. Disaster Monitor uses this interface as
a separate warning-artifact layer. It does not use an alert to discover, confirm,
select, correlate, or enrich a physical disaster event.

## Endpoint and bounded retrieval

The adapter performs one bounded HTTPS request to:

- `https://api.weather.gov/alerts/active`

It requests `Actual` CAP messages of type `Alert` or `Update` for the API's `land`
region type and then admits only meteorological (`Met`) records. The transport accepts
official GeoJSON, enforces a 3,000,000-byte response ceiling and a 500-record parsing
ceiling, and records the request parameters and source payload when snapshot storage is
configured. A record-ceiling or malformed-sibling result is explicitly degraded and
partial. Transport, media-type, and top-level shape failures remain unavailable rather
than becoming successful-empty results.

The client polls this Disaster Monitor endpoint every two minutes while the page is
visible. That is a local retrieval policy, not an NWS publication-frequency or stale
threshold claim. Weather.gov asks API clients not to poll more often than every 30
seconds. The implementation stays above that minimum and retains the distinct source
`sent`, `effective`, `onset`, and `expires` times plus the Disaster Monitor retrieval
time.

## Alert and geometry semantics

Each admitted record retains the provider alert ID, NWS sender/publisher, event,
optional headline, affected-area text, direct CAP severity, urgency, certainty and
timestamps, canonical `api.weather.gov/alerts/...` URL when valid, attribution,
limitations, and exact source geometry. Unknown or unrecognized severity, urgency, and
certainty remain `unknown`.

Only source-supplied GeoJSON `Polygon` rings are drawn. Rings are coordinate-bounded,
must be closed, and are not simplified or replaced. A null geometry stays null and is
listed as such; Disaster Monitor does not geocode area names or reconstruct NWS zone
polygons. Unsupported or malformed geometry excludes that record and degrades the
bounded response when otherwise usable siblings remain.

Expired records are excluded using the source `expires` timestamp. CAP cancellation
messages and non-`Actual` or non-meteorological messages are excluded. The active API
can still return updates and exact alert semantics remain those of the source.

## Authority, coverage, and limitations

Coverage is limited to United States land areas served by NWS and is not global.
Zone-based alerts and watches commonly have no polygon geometry. The API and network
can be delayed or unavailable, and a successful empty pull establishes only that the
bounded request returned no admitted active records. It does not prove an absence of
hazardous weather.

NWS alerts are authoritative public-warning artifacts, but the Disaster Monitor layer
is not a public warning delivery system and is not a replacement for official local
warning channels. It provides no generic forecast, radar, numerical model, impact
prediction, evacuation recommendation, or notification. An alert never becomes an
`ActiveIncident` and never participates in compound-hazard correlation.

NOAA/NWS information is generally United States Government public-domain material,
subject to the NWS disclaimer and expressly identified exceptions. Disaster Monitor
uses the attribution `NOAA/National Weather Service` and snapshot rights identifier
`noaa-nws-public-domain`.

References checked 2026-09-01:

- `https://www.weather.gov/documentation/services-web-api`
- `https://www.weather.gov/documentation/services-web-alerts`
- `https://api.weather.gov/openapi.json`
- `https://www.weather.gov/disclaimer`
