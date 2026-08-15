# USGS earthquakes

USGS scientific earthquake discovery for catalog countries and explicit worldwide
queries. The bounded official GeoJSON query requires no configuration and translates
identifiers, time, coordinates, depth, magnitude, significance, place, and timestamps.
Normalized dates, limits, country bounds, and simplified packaged polygons constrain
named-country results. Worldwide requests omit country bounds, retain the time,
magnitude, and record limits, and select latest or strongest deterministically without
assigning a synthetic country. USGS IDs compare within their namespace; cross-source
equivalence is application-owned. Transport,
content, JSON, and payload failures are diagnostics; foreign/out-of-bounds events are
excluded. Packaged boundaries are approximations, not legal borders; latency, accuracy,
and availability guarantees are unknown. Tests: USGS adapter, geography, event policy,
and regression suites. New countries require maintained geography, not agent branches.
