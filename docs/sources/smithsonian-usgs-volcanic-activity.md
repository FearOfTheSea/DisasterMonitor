# Smithsonian / USGS Weekly Volcanic Activity Report

DisasterMonitor uses the Smithsonian Global Volcanism Program / USGS Volcano Hazards
Program Weekly Volcanic Activity Report (WVAR) as its single volcanic-eruption event
discovery provider. WVAR is a preliminary weekly summary, not exhaustive real-time
global eruption surveillance. It can omit routine long-running activity, and rapidly
developing events can be fragmentary. Absence from WVAR does not prove that no
eruption is occurring.

## Admission and time

Only WVAR rows classified exactly as `New Eruptive Activity` or `Continuing Eruptive
Activity` are admitted. `New Unrest`, `Continuing Unrest`, `Other Observations`,
unknown classifications, and legacy pre-2026 activity categories are not silently
treated as eruptions. Narrative words such as ash, lava, tremor, alert, or eruption do
not override the report-type gate.

The event time is the physical eruption start, not the retrieval time, weekly report
week, or publication time. A day-precise WVAR `Eruption Start Date` is preferred. If
that is unavailable or qualified, a matching day-precise start from the GVP Holocene
Eruptions WFS may be used. Qualified, uncertain, month-only, year-only, and otherwise
ambiguous dates are not converted into exact timestamps. A source-backed calendar
date is normalized to UTC midnight; that is date-granularity normalization, not an
observed eruption clock time.

## Identity and geography

Candidates must carry the source-backed six-digit GVP volcano number from the WVAR
volcano-profile link. GVP Volcanoes of the World WFS supplies the fixed reviewed
metadata fields and source-backed point coordinates. GVP eruption numbers are used
when a matched eruption record is available; otherwise the identity combines the
volcano number with the exact start date. Volcano names are never geocoded.

For a named-country request, a GVP point inside the maintained country polygon is
`in_country`. A point outside the polygon can be `country_associated_offshore` only
when the structured GVP country affiliation explicitly includes that canonical
country. A point with neither relationship is excluded. Worldwide results use the
countryless event contract and do not invent a `Country` value.

## Evidence boundaries

WVAR is an event-discovery observation. It does not establish confirmed casualties,
evacuations, infrastructure impacts, local warnings, exclusion zones, or response
status. Volcanic unrest, alert changes, resuspended ash, seismicity, deformation,
fumarolic activity, thermal anomalies alone, and other non-eruptive observations are
not promoted to `volcanic_eruption` events. Situation or impact evidence is a separate
workflow; when configured, ReliefWeb is supplementary humanitarian situation evidence
using its `Volcano` taxonomy, never the volcanic event-verification source.

WVAR may cite national observatories, VAACs, or other sources in its report text.
DisasterMonitor does not independently ingest those embedded authorities through this
provider and never uses their URLs as canonical source URLs.
