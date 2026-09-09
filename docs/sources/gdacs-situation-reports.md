# GDACS observed impact reports

The GDACS event-detail endpoint provides structured `sendai` observations alongside
modelled risk/exposure products. The adapter reads only allowlisted Sendai indicators:
death, injured, missing, displaced, rescued, houses damaged, and houses destroyed.

Primary endpoint: https://www.gdacs.org/gdacsapi/api/events/geteventdata
Contract: https://www.gdacs.org/gdacsapi/swagger/v1/swagger.json

When the JSON detail endpoint transiently times out, returns a server error, or is
missing, the adapter makes one bounded request to the corresponding official GDACS
hazard report page (for example, `Floods/report.aspx`). It parses only the page's
SENDAI Indicator A/B/C tables and requires the explicit assessment date. If the page
identifies the selected episode, its explicit day-precision start/end dates are
retained; otherwise row-level timing remains unspecified. Aggregate summary values
are never used as substitutes for table rows. A `html_fallback` warning is retained
with the report so the degraded acquisition path is visible.

Retrieval requires a unique GDACS hazard/event identifier already linked to the
selected physical event. The returned hazard, event ID, and primary country must
match. This provider cannot discover an event or attach country-wide reports to an
unrelated event. Multi-country details with a different primary country currently
remain unavailable rather than risking incorrect attribution.

Each JSON row requires a supported indicator/type, a nonnegative integer value, a
country match, a region, and valid publication and observation-period timestamps.
Report-page rows require the same indicator/value/country/region checks plus an
explicit assessment date; an explicit episode period is retained when available,
while missing row-level timing remains unknown. Figures retain their local region
and period in the rendered report. Claim identity includes event, indicator, region,
and period; local rows are never summed into a national death toll. All figures are
secondary and preliminary. Modelled `impacts`, exposure, alert scores, and absence
of a row cannot establish casualties or zero loss.

The `latest` flag describes contributions to an episode and does not by itself
invalidate prior local observations. All admitted rows retain their dates. Same-scope
revisions use the existing temporal evidence reconciliation. Raw response snapshots
and GDACS/GloFAS lineage remain available through the existing provenance pipeline.
The adapter makes one bounded JSON request plus at most one bounded report-page
fallback and processes at most 200 rows; omitted rows produce a coverage warning.
This adapter is currently available for named-country reports.

The September 2026 Pakistan fixture comes from event FL 1104136, retrieved September
8, 2026. It includes separate Islamabad, Rawalpindi, and Khyber Pakhtunkhwa impact
observations. Fixture tests exercise the production reconciliation boundary and reject
mismatched events, countries, malformed rows, and modelled exposure.
