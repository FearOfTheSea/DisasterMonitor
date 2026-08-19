# NASA COOLR Landslides

DisasterMonitor uses NASA's [COOLR Reports Points FeatureServer
layer](https://gis.earthdata.nasa.gov/gis05/rest/services/Landslides/COOLR_Reports_Points/FeatureServer/0/query)
as the one configured landslide event-discovery provider. The adapter uses the JSON
FeatureServer query interface, a bounded standardized `event_date` predicate,
`event_date DESC`, WGS84 point geometry, and a small result bound below ArcGIS's
2,000-record ceiling. Named-country requests use a WGS84 envelope only for candidate
discovery and validate each returned point against the maintained country polygon.
Worldwide requests omit the country envelope and do not fabricate a country.

COOLR is a global report catalogue rather than complete real-time landslide
surveillance. NASA describes reports from the Global Landslide Catalog (`GLC`) and
Landslide Reporter Catalog (`LRC`); this integration accepts only those two documented
import classes and fails closed for future classes until their provenance is reviewed.
Reports can originate from media, external databases, scientific reports, or reviewed
citizen submissions, so geographic and reporting biases remain. Absence of a COOLR
record is not evidence that no landslide occurred.

The adapter prefers the FeatureServer WGS84 point and cross-checks explicit latitude
and longitude fields when present. Conflicting or invalid coordinates and required
dates are rejected rather than guessed. `event_date` is the event time; the approximate
free-form `event_time` text is not combined with it. Source update time uses
`last_edited_date`, then `submitted_date`, then `event_date` when valid. Qualitative
`landslide_size` is preserved as a severity string without numerical inference.
Casualty and injury columns are deliberately not event-discovery facts; impact and
situation claims belong to the separate evidence/reconciliation workflow.
