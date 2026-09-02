# NOAA NHC/CPHC cyclone forecast layers

NOAA’s National Hurricane Center (NHC) and Central Pacific Hurricane Center (CPHC)
publish first-party operational tropical-cyclone GIS products.

Disaster Monitor uses them only after GDACS selects a tropical cyclone.

The adapter does not discover events, replace selected-event geometry, issue warnings,
or make impact claims.

## Endpoint and admitted products

The adapter performs bounded HTTPS retrieval from official active-basin RSS feeds:

- `https://www.nhc.noaa.gov/gis-at.xml`
- `https://www.nhc.noaa.gov/gis-ep.xml`
- `https://www.nhc.noaa.gov/gis-cp.xml`

Follow only the exact official `Forecast Track [kmz]` and `Cone of Uncertainty [kmz]`
product links on `www.nhc.noaa.gov`.

Exclude shapefiles, preliminary best-track products, watches/warnings, and wind-field
products in v1.

Keep a missing class missing. Do not synthesize a track, cone, wind radius, circle,
landfall, or storm footprint.

The RSS channel currently declares `copyright` as `none`.

NOAA/NWS information is generally public-domain United States Government material,
subject to the NWS disclaimer and expressly identified exceptions.

Captured payloads use rights identifier `noaa-nws-public-domain`.

Preserve the canonical product URL and retain a content snapshot when snapshot storage
is configured.

## Identity and parsing policy

Run the provider only for a GDACS-selected `tropical_cyclone` with one exact
source-backed point.

Read at most 30 feed items and five active storm candidates per feed.

A storm qualifies only when its normalized official name is an exact token in the GDACS
source title.
Its published advisory center must be within 500 km.

Require exactly one candidate.

Report zero matches as `forecast_not_applicable`. Report multiple matches as
`identity_not_reconciled`.

Do not word unsupported basin coverage as “no forecast exists”.

Bound KMZ responses and uncompressed contents by size.

Reject encrypted or multi-KML archives. Exclude XML DTD and entity declarations.

Forecast-track parsing retains only placemarks explicitly labeled as forecast hours,
their exact WGS84 points, and source validity times.

Do not relabel the initial advisory point as a forecast.

Require at least two valid forecast points for a usable track.

Cone parsing retains the exact outer polygon, source ATCF ID, advisory time, and
forecast period.

Exclude malformed records and products. If one product class remains valid, return
only that valid subset.

Each layer retains ATCF storm ID, advisory number, product issue and retrieval times,
validity interval, direct product provenance, limitation, and reconciliation rationale.

Forecast tracks use `forecast_track`. Cones use `uncertainty_area`.

The browser renders tracks with a dashed treatment and cones as areas. It shows labels
and warns that forecast and uncertainty geometry are not observed storm footprints.

## Coverage, cadence, and overlap

Coverage is limited to active NHC/CPHC advisories in the Atlantic, Eastern North
Pacific, and Central North Pacific.

Feeds and products update with operational advisories. Issue and publication latency
is source-dependent.

This is not global tropical-cyclone forecast coverage.

Provider transport or parsing failure remains a non-fatal situation-evidence issue. It
cannot invalidate the already verified GDACS event.

NHC/CPHC products can be upstream inputs to GDACS.

A successful match supplies operational map context. It is not independent event
corroboration.

The cone represents probable track-center uncertainty under the official product
definition.

It does not represent storm size, wind extent, local hazards, impact, evacuation, or an
observed footprint.

The 2026-08-31 bounded live check observed active Eastern North Pacific advisories for
Karina (`EP112026`) and Lowell in the official RSS family.

Karina exposed distinct forecast-track and cone KMZ products. Their timestamps, ATCF
identity, and geometry parsed without creating a wind layer.

This demonstrates current endpoint compatibility. It does not demonstrate future
availability, forecast accuracy, or global completeness.

References checked 2026-08-31:

- `https://www.nhc.noaa.gov/aboutrss.shtml`
- `https://www.nhc.noaa.gov/gis/`
- `https://www.nhc.noaa.gov/aboutcone.shtml`
- `https://www.weather.gov/disclaimer`
