# USGS earthquakes

USGS provides scientific earthquake discovery for catalog countries and explicit
worldwide queries.

The bounded official GeoJSON query requires no configuration. It translates
identifiers, time, coordinates, depth, magnitude, significance, place, and timestamps.

Normalized dates, limits, country bounds, and simplified packaged polygons constrain
named-country results.

Worldwide requests omit country bounds. They retain time, magnitude, and record limits.

Select latest or strongest deterministically without assigning a synthetic country.

Compare USGS IDs within their namespace. Application policy owns cross-source
equivalence.

Treat transport, content, JSON, and payload failures as diagnostics.

Exclude foreign or out-of-bounds events.

Admit a near-shore event outside the polygon only within the bounded 100 km association
distance.
Require USGS place text to name the requested country.

Label that event `country_associated_offshore`. Do not treat it as land-based.

Packaged boundaries are approximations, not legal borders.

Latency, accuracy, and availability guarantees are unknown.

Tests cover the USGS adapter, geography, event policy, and regression suites.

New countries require maintained geography. They do not require agent branches.
