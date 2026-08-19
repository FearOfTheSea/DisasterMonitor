# NASA EONET Wildfires

DisasterMonitor uses NASA's [Earth Observatory Natural Event Tracker (EONET) v3
events API](https://eonet.gsfc.nasa.gov/api/v3/events) as the one configured wildfire
event-discovery provider. Requests always constrain `category=wildfires`,
`status=all`, a bounded date range, and a bounded result count. Named-country
requests add EONET's candidate bounding box and then validate returned source
geometry against the maintained country polygon. Worldwide requests do not assign a
country.

EONET is a curated secondary source, not an official incident-perimeter authority.
Its disclaimer states that spatial and temporal extents should not be treated as
official, and the records aggregate underlying source metadata. The current wildfire
curation applies a material-size threshold, so small fires and other thermal
anomalies may be absent. Global completeness is not guaranteed.

The adapter preserves one physical EONET event across its dated geometry observations.
It uses the earliest valid geometry date as the event time, the latest valid date as
the source update time, and selects the latest country-intersecting geometry for a
named-country query. Point geometry is copied directly. A single source-supplied
polygon ring may be retained as an area; ambiguous or unrepresentable geometry is
excluded. A source-reported `magnitudeValue` and non-empty `magnitudeUnit` are kept as
the generic magnitude measurement without converting them to acreage, severity,
confidence, or another inferred quantity.

The source reference is the EONET event URL on `eonet.gsfc.nasa.gov`, never a nested
IRWIN, GDACS, or other upstream URL. This provider supplies event discovery only. It
does not establish impacts, casualties, warnings, response status, or official fire
perimeters; those claims require separate situation evidence.
