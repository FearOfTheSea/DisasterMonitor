# NOAA IBTrACS track reconciliation

NOAA NCEI’s International Best Track Archive for Climate Stewardship (IBTrACS) only
reconciles a track and identity after GDACS selects a tropical cyclone.

It has secondary provider registration with scientific-verification and map-layer
roles.

It does not discover live events, replace an operational warning centre, or establish
forecast, landfall, impact, casualty, warning, or response claims.

The adapter downloads the official v04r01 `ACTIVE` CSV subset. This subset covers
storms active in the archive’s recent window.

It accepts `MAIN`, `PROVISIONAL`, and `US-PROVISIONAL` tracks. It skips the CSV units
row, validates coordinates and timestamps, groups points by stable IBTrACS SID, and
retains contributing agency and ATCF identifiers.

It admits at most 5,000 rows and 500 points per track.

Attach a track only when all these rules produce exactly one candidate:

- The selected event came from the GDACS tropical-cyclone provider.
- The IBTrACS name is non-generic and exactly matches a token in the GDACS source title.
- The track start is within 36 hours of the GDACS onset.
- At least one retained track point is within 500 km of the GDACS point.

The proximity bound handles update latency between a moving GDACS endpoint and an
archive updated about three times weekly.

Proximity alone is never sufficient.

Zero or multiple candidates fail closed with `identity_not_reconciled`.

A unique result is a `matched` situation report with SID, interval, point count,
agency lineage, and ATCF IDs.

Expose the same exact timestamped points as a separate `provisional_track` supplemental
map layer.

They never replace selected-event occurrence geometry and are never forecasts.

Do not promote wind, pressure, category, or landfall columns.

IBTrACS merges tracks from WMO Regional Specialized Meteorological Centres, Tropical
Cyclone Warning Centres, JTWC, and other agencies.

GDACS can use the same upstream agency. Report and catalog text therefore state that
agreement is not independent corroboration.

Active records are provisional. Operational data can change them into best tracks.

The 2026-08-24 live check selected GDACS SAUDEL-26 for Japan and uniquely matched
IBTrACS SID `2026231N08155` by name, exact start, and track proximity.

The assistant rendered the provisional track as qualitative evidence and disclosed
upstream overlap.

An exact 2026-01-01 Japan query returned no verified cyclone. It did not use the active
archive for historical discovery.

Payload snapshots use rights identifier `noaa-ncei-data`.

Deterministic tests cover the two-row CSV header, grouping, stable IDs, agency lineage,
three-part identity matching, and non-GDACS exclusion.
They also cover ambiguous and no-match abstention, geometry requirements, routing,
authority, source policy, and snapshot provenance.

References checked 2026-08-24:

- `https://www.ncei.noaa.gov/products/international-best-track-archive`
- `https://www.ncei.noaa.gov/sites/g/files/anmtlf171/files/2025-04/IBTrACS_version4r01_Technical_Details.pdf`
- `https://www.ncei.noaa.gov/data/international-best-track-archive-for-climate-stewardship-ibtracs/v04r01/access/csv/`
- `https://www.ncei.noaa.gov/data/international-best-track-archive-for-climate-stewardship-ibtracs/v04r01/access/csv/ibtracs.ACTIVE.list.v04r01.csv`
