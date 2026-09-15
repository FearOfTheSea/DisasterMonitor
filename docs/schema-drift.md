# Provider schema drift

External payload parsers fail closed when a field that controls identity, time,
geography, authority, or semantic role is missing or changes type. Additive metadata
is tolerated only when the fields used by the parser remain valid.

The parser-boundary fixtures (retained files or compact inline payloads) cover every
production disaster parser family: GeoJSON/JSON (USGS, EMSC, GDACS, GFM STAC,
Copernicus EMS, EONET, COOLR, NWS, ReliefWeb and Smithsonian WFS), CAP/Atom and
RSS XML, the NHC KML/KMZ products, IBTrACS and FIRMS CSV, and the
GDACS/Smithsonian HTML fallbacks. Parser integration tests exercise malformed
top-level documents, missing required record fields, invalid discriminators,
coordinates and times, and unknown semantic values.

`tests/fixtures/schema_drift` retains before/after payloads only when a real provider
change is observed. The initial pair records the Smithsonian WVAR page change from a
page-level report link to an additional row-local report link. Both supported shapes
produce the same event identity; a row-local link improves provenance. A materially
different table/header shape remains unavailable instead of being guessed.

For each future drift:

1. retain the smallest unmodified response fragment that reproduces the change;
2. record before and after files without credentials or personal data;
3. add a parser-boundary regression for both accepted versions;
4. add a failure case for the unknown material variant; and
5. update the parser only when source semantics and rights are understood.
