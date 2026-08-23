# NOAA IBTrACS track reconciliation

NOAA NCEI’s International Best Track Archive for Climate Stewardship (IBTrACS) is used
only to reconcile a track and identity after GDACS selects a tropical cyclone. It is a
secondary provider registration with scientific-verification and map-layer roles. It
does not discover live events, replace an operational warning centre, or establish
forecast, landfall, impact, casualty, warning, or response claims.

The adapter downloads the official v04r01 `ACTIVE` CSV subset, which covers storms
active in the archive’s recent window. It accepts `MAIN`, `PROVISIONAL`, and
`US-PROVISIONAL` tracks, skips the CSV units row, validates coordinates and timestamps,
groups points by stable IBTrACS SID, and retains contributing agency and ATCF
identifiers. It admits at most 5,000 rows and 500 points per track.

A track is attached only when all of these rules produce exactly one candidate:

- the selected event came from the GDACS tropical-cyclone provider;
- the IBTrACS name is non-generic and exactly matches a token in the GDACS source title;
- the track start is within 36 hours of the GDACS onset; and
- at least one retained track point is within 500 km of the GDACS point.

The proximity bound accommodates update latency between a moving GDACS endpoint and an
archive updated about three times weekly. It is never sufficient on its own. Zero or
multiple candidates fail closed with `identity_not_reconciled`. A unique result is a
`matched` situation report containing SID, interval, point count, agency lineage, and
ATCF IDs. Wind, pressure, category, and landfall columns are not promoted.

IBTrACS merges tracks supplied by WMO Regional Specialized Meteorological Centres,
Tropical Cyclone Warning Centres, JTWC, and other agencies. GDACS can use the same
upstream agency. The report and catalog therefore state that agreement is not
independent corroboration. Active records are provisional and can change when
operational data become best tracks.

The 2026-08-24 live behavior check selected GDACS SAUDEL-26 for Japan and uniquely
matched IBTrACS SID `2026231N08155` by name, exact start, and track proximity. The
assistant rendered the provisional track as qualitative evidence and disclosed its
upstream overlap. An exact 2026-01-01 Japan query returned no verified cyclone rather
than using the active archive as historical discovery.

Payload snapshots use rights identifier `noaa-ncei-data`. Deterministic tests cover the
two-row CSV header, grouping, stable IDs, agency lineage, three-part identity matching,
non-GDACS exclusion, ambiguous/no-match abstention, geometry requirements, routing,
authority, source policy, and snapshot provenance.

References checked 2026-08-24:

- `https://www.ncei.noaa.gov/products/international-best-track-archive`
- `https://www.ncei.noaa.gov/sites/g/files/anmtlf171/files/2025-04/IBTrACS_version4r01_Technical_Details.pdf`
- `https://www.ncei.noaa.gov/data/international-best-track-archive-for-climate-stewardship-ibtracs/v04r01/access/csv/`
- `https://www.ncei.noaa.gov/data/international-best-track-archive-for-climate-stewardship-ibtracs/v04r01/access/csv/ibtracs.ACTIVE.list.v04r01.csv`

