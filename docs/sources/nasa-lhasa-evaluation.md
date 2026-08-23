# NASA LHASA integration evaluation

NASA’s Landslide Hazard Assessment for Situational Awareness (LHASA) is suitable only
for hazard or likelihood evidence. It estimates where rainfall-triggered landslide
activity is probable using satellite precipitation, soil moisture, susceptibility, and
other model inputs. A LHASA pixel or administrative exposure class is not an observed
landslide and can never confirm occurrence or create an event in DisasterMonitor.

No LHASA provider is registered in this release. The evaluation on 2026-08-24 found the
following official access paths but no defensible bounded runtime interface:

- The documented GPM PMM Publisher API advertises
  `global_landslide_nowcast` and `global_landslide_nowcast_30mn`, with only a recent
  rolling window. Its official `pmmpublisher.pps.eosdis.nasa.gov` service did not accept
  a connection during the live check.
- The official Earthdata `Landslides/LHASA_Exposure` ArcGIS MapServer describes daily
  global model risk and supports JSON/GeoJSON in its metadata. Both the service and
  layer metadata requests returned an ArcGIS 503 access error body instead of a usable
  query schema.
- NASA’s current LHASA repository points to
  `maps.nccs.nasa.gov/download/landslides` for latest predictions and explicitly says
  the best-effort data normally arrive four times daily with frequent server downtime.
  The download path returned a gateway failure during evaluation.
- GES DISC provides a long-term archive, but that is an authenticated research archive,
  not a small current point-query service suitable for the request-time provider path.

The blocked capability is selected-event landslide analytical-model evidence. No event
discovery, occurrence confirmation, or existing six-disaster coverage depends on it;
NASA COOLR remains landslide discovery and Copernicus Rapid Mapping supplies sparse
secondary map evidence.

The smallest prerequisite that would unlock LHASA is a stable, documented,
machine-readable NASA endpoint that supports a bounded point or small-area query,
exposes model/version and valid time, and has an operational availability contract or a
locally scheduled authenticated cache. Once available, the adapter should run only
after a landslide is selected, emit `analytical_model` facts with `estimated` status,
retain model time/version and source geometry, use at most `possible` correlation, and
state that likelihood neither confirms nor disproves occurrence. It must never register
for event discovery.

References checked 2026-08-24:

- `https://gpm.nasa.gov/precip-apps/doc`
- `https://gis.earthdata.nasa.gov/gis05/rest/services/Landslides/LHASA_Exposure/MapServer`
- `https://github.com/nasa/LHASA`
- `https://maps.nccs.nasa.gov/download/landslides`
- `https://disc.gsfc.nasa.gov/datasets/Global_Landslide_Nowcast_2.0/summary`

