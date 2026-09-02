# NASA LHASA integration evaluation

NASA’s Landslide Hazard Assessment for Situational Awareness (LHASA) is suitable only
for hazard or likelihood evidence.

It estimates where rainfall-triggered landslide activity is probable. It uses
satellite precipitation, soil moisture, susceptibility, and other model inputs.

A LHASA pixel or administrative exposure class is not an observed landslide. It can
never confirm occurrence or create an event in DisasterMonitor.

No LHASA provider is registered in this release.

The 2026-08-24 evaluation found official access paths but no defensible bounded
runtime interface:

- The documented GPM PMM Publisher API advertises `global_landslide_nowcast` and
  `global_landslide_nowcast_30mn` with a recent rolling window. Its official
  `pmmpublisher.pps.eosdis.nasa.gov` service did not accept a connection during the
  live check.
- The official Earthdata `Landslides/LHASA_Exposure` ArcGIS MapServer describes daily
  global model risk and supports JSON/GeoJSON in its metadata. Service and layer
  metadata requests returned an ArcGIS 503 access-error body, not a usable query schema.
- NASA’s current LHASA repository points to `maps.nccs.nasa.gov/download/landslides`
  for latest predictions. It says best-effort data normally arrive four times daily
  with frequent server downtime. The download path returned a gateway failure during
  evaluation.
- GES DISC provides a long-term archive. It is an authenticated research archive, not
  a small current point-query service for request-time provider use.

The blocked capability is selected-event landslide analytical-model evidence.

No event discovery, occurrence confirmation, or existing six-disaster coverage
depends on LHASA.

NASA COOLR remains landslide discovery. Copernicus Rapid Mapping supplies sparse
secondary map evidence.

The smallest prerequisite is a stable, documented, machine-readable NASA endpoint.
It must support a bounded point or small-area query and expose model version and valid
time.

It must also have an operational availability contract or a locally scheduled
authenticated cache.

When available, run the adapter only after landslide selection.

Emit `analytical_model` facts with `estimated` status. Retain model time, model
version, and source geometry.

Use at most `possible` correlation. State that likelihood neither confirms nor
disproves occurrence.

Never register LHASA for event discovery.

References checked 2026-08-24:

- `https://gpm.nasa.gov/precip-apps/doc`
- `https://gis.earthdata.nasa.gov/gis05/rest/services/Landslides/LHASA_Exposure/MapServer`
- `https://github.com/nasa/LHASA`
- `https://maps.nccs.nasa.gov/download/landslides`
- `https://disc.gsfc.nasa.gov/datasets/Global_Landslide_Nowcast_2.0/summary`
