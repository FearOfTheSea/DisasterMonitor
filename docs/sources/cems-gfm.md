# CEMS Global Flood Monitoring (GFM)

DisasterMonitor uses the Copernicus Emergency Management Service Global Flood
Monitoring product as its primary flood event-discovery source. Candidate discovery
uses the public [EODC STAC API](https://stac.eodc.eu/api/v1), collection `GFM`.

The adapter then evaluates the official `ensemble_flood_extent` COG through the
EODC TiTiler [GeoJSON statistics endpoint](https://titiler.services.eodc.eu/api.html).
The deployed contract is `POST /cog/statistics`: the asset URL is passed as `url`,
the request body is the country polygon (or bounded item footprint for worldwide
scanning), and categorical statistics request flood class `1`.

An item or its Sentinel-1 acquisition footprint is only a candidate. DisasterMonitor
emits an event only when the clipped statistics contain a nonzero count for class 1,
the GFM Observed Flood Extent. Country events retain official STAC provenance and
are marked `IN_COUNTRY`; the event geometry is omitted because clipped summary
statistics do not provide a flood perimeter. Equi7 tile identifiers are retained as
provider IDs but are not treated as separate physical floods; records sharing the
Sentinel acquisition identity are coalesced.

The source is event discovery only. It does not establish flood severity, damage,
casualties, affected population, warnings, response status, or national totals.
Country searches are bounded by the requested recent time window and country polygon.
Worldwide searches use a deterministic bounded recent scan and are not globally
complete. STAC item references and COG URLs are accepted only from the registered
EODC authorities. Successful STAC and statistics responses can be persisted through
the operational source-snapshot path.
