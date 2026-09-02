# Smithsonian / USGS Weekly Volcanic Activity Report

DisasterMonitor uses the Smithsonian Global Volcanism Program / USGS Volcano Hazards
Program Weekly Volcanic Activity Report (WVAR) as its single volcanic-eruption
event-discovery provider.

WVAR is a preliminary weekly summary, not exhaustive real-time global eruption
surveillance.

It can omit routine long-running activity. Rapidly developing events can be fragmentary.
Absence from WVAR does not prove that no eruption is occurring.

Current-window discovery reads Smithsonian’s official
[WVAR RSS feed](https://volcano.si.edu/news/WeeklyVolcanoRSS.xml).

The feed remains a machine-readable first-party resource when the human report page is
protected by its web application firewall.

Dated historical queries use the WVAR archive page because RSS contains only the current
report.

The GVP WFS remains the source of reviewed volcano identity, geography, and day-precise
eruption dates.

If RSS is unavailable or malformed, the adapter can use the human page.

A failure of both paths is reported as degraded source coverage.

## Admission and time

Admit only WVAR rows classified exactly as `New Eruptive Activity` or
`Continuing Eruptive Activity`.

Do not treat `New Unrest`, `Continuing Unrest`, `Other Observations`, unknown
classifications, or legacy pre-2026 categories as eruptions.

Narrative words such as ash, lava, tremor, alert, or eruption do not override the
report-type gate.

Use the physical eruption start as event time. Do not use retrieval time, report week,
or publication time.

Prefer a day-precise WVAR `Eruption Start Date` from a historical page.

The current RSS format omits that field. Require a matching day-precise start from the
GVP Holocene Eruptions WFS.

For continuing activity, use the latest unambiguous exact GVP start no later than the
report week.

For new activity, require a start close enough to the report week to avoid an unrelated
older eruption.

Do not convert qualified, uncertain, month-only, year-only, or ambiguous dates into
exact timestamps.

Normalize a source-backed calendar date to UTC midnight. This is date-granularity
normalization, not an observed eruption clock time.

## Identity and geography

Candidates must carry the source-backed six-digit GVP volcano number from the WVAR
volcano-profile link.

GVP Volcanoes of the World WFS supplies fixed reviewed metadata and source-backed point
coordinates.

Use GVP eruption numbers when a matched eruption record exists. Otherwise combine the
volcano number with the exact start date.

Never geocode volcano names.

For a named-country request, a GVP point inside the maintained country polygon is
`in_country`.

A point outside the polygon can be `country_associated_offshore` only when structured
GVP country affiliation explicitly includes the canonical country.

Exclude a point with neither relationship.

Worldwide results use the countryless event contract. Do not create a `Country` value.

## Evidence boundaries

WVAR is an event-discovery observation. It does not establish confirmed casualties,
evacuations, infrastructure impacts, local warnings, exclusion zones, or response
status.

Volcanic unrest, alert changes, resuspended ash, seismicity, deformation, fumarolic
activity, thermal anomalies alone, and other non-eruptive observations are not
`volcanic_eruption` events.

Situation and impact evidence use a separate workflow.

When configured, ReliefWeb is supplementary humanitarian situation evidence using its
`Volcano` taxonomy. It is never the volcanic event-verification source.

WVAR can cite national observatories, VAACs, or other sources in report text.

DisasterMonitor does not independently ingest those embedded authorities through this
provider. It never uses their URLs as canonical source URLs.
