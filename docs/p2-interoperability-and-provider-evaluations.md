# P2 interoperability and provider evaluations

Reviewed 2026-09-15. This record distinguishes implemented interfaces from sources
that were evaluated but deliberately not admitted.

## OGC API Features

Decision: implement a narrow, read-only OGC API Features-style projection for the
`incidents` and `observations` collections. It supports WGS84 `bbox`, explicit
occurrence bounds, and a hard result limit. It does not advertise transactions,
filtering conformance classes, CRS negotiation, or a standards conformance claim.
The canonical event model remains the owner; OGC output is only a projection.

## Volcanic ash advisories

Decision: do not admit a VAAC feed in P2. ICAO's International Airways Volcano Watch
defines nine VAACs and aviation-specific operational responsibilities. WMO's IWXXM
2025-2 model has a versioned Volcanic Ash Advisory representation, while WMO reported
in June 2026 that common quantitative-volcanic-ash APIs and NetCDF delivery are still
being harmonized. A safe integration therefore needs:

- an authoritative global VAAC-centre registry and responsibility polygons;
- complete IWXXM schema plus Schematron validation;
- separate observed/estimated ash and forecast polygons, flight levels, issue time,
  validity time, advisory sequence, cancellation, and issuing centre;
- deduplication across bulletin transport paths without merging volcano events; and
- a source-by-source access, redistribution, retention, and availability review.

Treating an advisory as confirmation of an eruption or surface impact is prohibited.

Primary references: WMO IWXXM (`https://public.wmo.int/iwxxm`), ICAO IAVW Handbook
Doc 9766, and the WMO Services for Aviation Newsletter 1/2026.

## Tropical-cyclone forecast sources beyond NHC

Decision: retain NHC plus source-backed IBTrACS historical tracks; do not add another
live forecast adapter in P2. WMO's Severe Weather Information Centre aggregates
advisories from RSMCs, TCWCs, and NMHSs, and explicitly warns that products can differ
because of observations, cut-off times, models, and professional judgement. Admission
needs stable machine-readable endpoints, centre/region ownership, wind-averaging and
intensity normalization, advisory identity, forecast-hour semantics, cancellation,
and rights/availability review for every centre. Forecast tracks must remain
acquisition/forecast observations and never become observed physical-event geometry.

Primary reference: WMO SWIC 3.0 Tropical Cyclone Warnings and Advisories
(`https://severeweather.wmo.int/tc.html`).

## Cyclone-to-flood association

Decision: keep the rule as descriptive context with a 300 km / 72 hour gate. Only
physical-event observations are eligible. Forecast/acquisition records are rejected
by the rule registry. The output always states that proximity is not causation and
does not merge event identities.

## Publisher-feed rights review

NASA Earth Observatory Natural Events is admitted as a single bounded RSS publisher
path. Its feed is fetched only from `science.nasa.gov`, at most once per 15 minutes,
with one request, a 1 MB response limit, conditional headers, full attribution, and a
2027-03-15 review expiry. NASA's media guidance permits factual informational use with
acknowledgement; logos are not imported and third-party-marked material is not
republished. The application retains titles, canonical links, publisher, and times as
news metadata rather than treating the feed as physical-event authority.

The Guardian was rejected: its current terms prohibit automated collection and
AI/text-data aggregation without prior approval. BBC was not admitted because its
terms distinguish personal feed display from business metadata use. These rejected
sources remain outside configuration.

Primary references: NASA Images and Media Usage Guidelines
(`https://www.nasa.gov/nasa-brand-center/images-and-media/`), Guardian RSS help and
terms, and BBC Terms of Use section 15.
