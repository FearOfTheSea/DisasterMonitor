# CEMS Global Flood Monitoring (GFM)

DisasterMonitor uses the Copernicus Emergency Management Service Global Flood
Monitoring product as its primary flood event-discovery source.

Candidate discovery uses the public [EODC STAC API](https://stac.eodc.eu/api/v1),
collection `GFM`.

The adapter evaluates the official `ensemble_flood_extent` COG through the EODC
TiTiler [GeoJSON statistics endpoint](https://titiler.services.eodc.eu/api.html).

The deployed contract is `POST /cog/statistics`. Pass the asset URL as `url`.
Send the country polygon, or the bounded item footprint for worldwide scanning, in
the request body. Request categorical statistics for flood class `1`.

An item or Sentinel-1 acquisition footprint is a candidate only.

DisasterMonitor emits an event only when clipped statistics contain a nonzero class-1
count. Class `1` is the GFM Observed Flood Extent.

Country events retain official STAC provenance and use `IN_COUNTRY`.

Clipped summary statistics do not provide a flood perimeter.

Emitted flood map points are estimated from the center of the retained CEMS GFM
observation tile.

They represent the observation-footprint center. They are not an exact flood location,
flood epicenter, or flood perimeter.

Equi7 tile identifiers remain provider IDs. They are not separate physical floods.
Records with one Sentinel acquisition identity are coalesced.

When several positive tiles share one acquisition, the lexicographically smallest STAC
item ID supplies the representative point. All tile IDs remain provider metadata.

This source provides event discovery only. It does not establish flood severity,
damage, casualties, affected population, warnings, response status, or national totals.

Country searches use the requested recent time window and country polygon.
Worldwide searches use a deterministic bounded recent scan and are not globally complete.

Accept STAC item references and COG URLs only from registered EODC authorities.

Successful STAC and statistics responses can persist through the operational
source-snapshot path.
