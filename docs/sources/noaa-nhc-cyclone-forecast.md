# NOAA NHC/CPHC cyclone forecast layers

NOAA's National Hurricane Center (NHC) and Central Pacific Hurricane Center (CPHC)
publish first-party operational tropical-cyclone GIS products. Disaster Monitor uses
those products only after GDACS selects a tropical cyclone. The adapter does not
discover events, replace the selected event geometry, issue warnings, or make impact
claims.

## Endpoint and admitted products

The adapter performs bounded HTTPS retrieval from the official active-basin RSS feeds:

- `https://www.nhc.noaa.gov/gis-at.xml`
- `https://www.nhc.noaa.gov/gis-ep.xml`
- `https://www.nhc.noaa.gov/gis-cp.xml`

It follows only the exact official `Forecast Track [kmz]` and
`Cone of Uncertainty [kmz]` product links on `www.nhc.noaa.gov`. Shapefiles, preliminary
best-track products, watches/warnings, and wind-field products are excluded in v1. A
missing class remains missing; the adapter does not synthesize a track, cone, wind
radius, circle, landfall, or storm footprint.

The RSS channel currently declares `copyright` as `none`. NOAA/NWS information is
generally public-domain United States Government material subject to the NWS disclaimer
and any expressly identified exceptions. Captured payloads use rights identifier
`noaa-nws-public-domain`, preserve the canonical product URL, and retain a content
snapshot when snapshot storage is configured.

## Identity and parsing policy

The provider runs only for a GDACS-selected `tropical_cyclone` with one exact
source-backed point. It reads at most 30 feed items and five active storm candidates per
feed. A storm qualifies only when its normalized official name is an exact token in the
GDACS source title and the published advisory center is within 500 km. Exactly one
candidate is required; zero matches report `forecast_not_applicable`, while multiple
matches report `identity_not_reconciled`. Unsupported basin coverage is therefore not
worded as “no forecast exists.”

KMZ responses and uncompressed contents are size-bounded, encrypted/multi-KML archives
are rejected, and XML DTD/entity declarations are excluded. Forecast-track parsing
retains only placemarks explicitly labeled as forecast hours, their exact WGS84 points,
and their source validity times. The initial advisory point is not relabeled as a
forecast. A usable track requires at least two valid forecast points. Cone parsing
retains the exact outer polygon plus the source ATCF ID, advisory time, and forecast
period. Malformed records or products are excluded. If one product class remains valid,
only that valid subset is returned.

Each layer retains the ATCF storm ID, advisory number, product issue and retrieval
times, validity interval, direct product provenance, limitation, and reconciliation
rationale. Forecast tracks use the explicit `forecast_track` role and cones use
`uncertainty_area`. The browser renders tracks with a dashed treatment and cones as
areas, with labels and the warning that forecast and uncertainty geometry are not
observed storm footprints.

## Coverage, cadence, and overlap

Coverage is limited to active NHC/CPHC advisories in the Atlantic, Eastern North
Pacific, and Central North Pacific. Feeds and products update with operational
advisories; exact issue and publication latency is source-dependent. This is not global
tropical-cyclone forecast coverage. Provider transport or parsing failure remains a
non-fatal situation-evidence issue and cannot invalidate the already verified GDACS
event.

NHC/CPHC products can be upstream inputs to GDACS. A successful match supplies
operational map context but is not counted as independent event corroboration. The cone
represents probable track-center uncertainty under the official product definition; it
does not represent storm size, wind extent, local hazards, impact, evacuation, or an
observed footprint.

The 2026-08-31 bounded live check observed active Eastern North Pacific advisories for
Karina (`EP112026`) and Lowell in the official RSS family. Karina exposed distinct
forecast-track and cone KMZ products whose timestamps, ATCF identity, and geometry were
parsed without creating a wind layer. This demonstrates current endpoint compatibility,
not future availability, forecast accuracy, or global completeness.

References checked 2026-08-31:

- `https://www.nhc.noaa.gov/aboutrss.shtml`
- `https://www.nhc.noaa.gov/gis/`
- `https://www.nhc.noaa.gov/aboutcone.shtml`
- `https://www.weather.gov/disclaimer`
