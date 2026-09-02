# NASA COOLR Landslides

DisasterMonitor uses NASA’s [COOLR Reports Points FeatureServer
layer](https://gis.earthdata.nasa.gov/gis01/rest/services/Landslides/COOLR_Reports_Points/FeatureServer/0/query)
as the configured landslide event-discovery provider.

The adapter uses the JSON FeatureServer query interface and a bounded standardized
`event_date` predicate.
It uses `event_date DESC`, WGS84 point geometry, and a small result limit below
ArcGIS’s 2,000-record ceiling.

Named-country requests use a WGS84 envelope for candidate discovery. The adapter
validates each returned point against the maintained country polygon.

Worldwide requests omit the country envelope. They do not create a country.

COOLR is a global report catalogue, not complete real-time landslide surveillance.

NASA describes reports from the Global Landslide Catalog (`GLC`) and Landslide
Reporter Catalog (`LRC`). This integration accepts only those two documented import
classes.

It fails closed for future classes until their provenance is reviewed.

Reports can come from media, external databases, scientific reports, or reviewed
citizen submissions. Geographic and reporting biases remain.

Absence of a COOLR record does not prove that no landslide occurred.

The adapter prefers FeatureServer WGS84 point geometry. It cross-checks explicit
latitude and longitude fields when present.

Reject conflicting or invalid coordinates and required dates. Do not guess values.

Use `event_date` as event time. Do not combine approximate free-form `event_time` text
with it.

Use `last_edited_date`, then `submitted_date`, then valid `event_date` for source
update time.

Preserve qualitative `landslide_size` as a severity string. Do not infer a number.

Casualty and injury columns are not event-discovery facts. Impact and situation claims
belong to the separate evidence and reconciliation workflow.
