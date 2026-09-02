# NASA EONET Wildfires

DisasterMonitor uses NASA’s [Earth Observatory Natural Event Tracker (EONET) v3
events API](https://eonet.gsfc.nasa.gov/api/v3/events) as the configured wildfire
event-discovery provider.

Requests always set `category=wildfires`, `status=all`, a bounded date range, and a
bounded result count.

Named-country requests add EONET’s candidate bounding box. The adapter validates
returned source geometry against the maintained country polygon.

Worldwide requests do not assign a country.

EONET is a curated secondary source, not an official incident-perimeter authority.
Its disclaimer says that spatial and temporal extents are not official.

Records aggregate underlying source metadata. Current wildfire curation applies a
material-size threshold, so small fires and other thermal anomalies can be absent.

Global completeness is not guaranteed.

The adapter admits an event only when valid source geometry includes an observation
inside the bounded query window.

It preserves one physical EONET event across all valid dated geometry observations.

The earliest valid geometry date is event time. The latest valid date is source update
time.

For a named-country query, select the latest query-relevant country-intersecting
geometry.

Copy point geometry directly. Retain one source-supplied polygon ring as an area.
Exclude ambiguous or unrepresentable geometry.

Keep a source-reported `magnitudeValue` with a non-empty `magnitudeUnit` as the generic
magnitude measurement.

Do not convert it to acreage, severity, confidence, or another inferred quantity.

Use the EONET event URL on `eonet.gsfc.nasa.gov` as the source reference.

Do not use nested IRWIN, GDACS, or other upstream URLs as canonical source URLs.

This provider supplies event discovery only. It does not establish impacts, casualties,
warnings, response status, or official fire perimeters.

Those claims require separate situation evidence.
