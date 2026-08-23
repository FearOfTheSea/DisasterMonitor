# EMSC SeismicPortal earthquakes

EMSC SeismicPortal is a secondary global scientific source for earthquake event
discovery and corroboration. The adapter uses the official FDSN Event `query`
interface with `format=json` and the `EMSC-RTS` catalogue. It requires no API key.
The service documentation identifies the catalogue as global earthquake parameters,
supports time and geographic bounds, and licenses this web-service dataset under
CC BY 4.0.

Named-country requests send bounded time, magnitude, result-count, and country-box
constraints, then validate the returned point against maintained country geometry.
A point just offshore can be associated only within 100 km of the maintained boundary
and when the EMSC Flinn-Engdahl region explicitly names the country. Worldwide
requests omit country bounds and preserve the explicit latest/strongest selection
intent. The adapter retains the SeismicPortal `unid`, contributing catalogue and
source identifier, origin time, last update, region, point, depth, and magnitude.

EMSC/CSEM aggregates rapidly contributed seismological parameters. Preferred origins
can be automatic, incomplete, delayed, erroneous, or revised as observations and
analyses change. A matching EMSC and USGS observation is therefore useful scientific
agreement, but it is not automatically independent corroboration: the preferred EMSC
origin may come from a network also represented by USGS. Observation-level source
provenance remains separate during physical-event reconciliation.

This integration does not ingest felt reports, comments, tsunami indications, damage,
casualties, warnings, or emergency-response claims. EMSC is not national or emergency
authority, and its own terms direct critical users to national/local authorities,
seismological services, and emergency services.

Freshness is near-real-time but not guaranteed. Canonical event links use the stable
SeismicPortal `unid`; payload snapshots use rights identifier
`emsc-fdsn-event-cc-by-4.0`. Deterministic coverage is in
`tests/integration/test_emsc_adapter.py`, with registration, tier, routing, source-host,
malformed-record, empty-result, country-exclusion, and bounded-query rules covered by
the affected unit and integration suites.

References checked 2026-08-24:

- `https://www.seismicportal.eu/fdsn-wsevent.html`
- `https://www.seismicportal.eu/fdsnws/event/1/docs`
- `https://www.seismicportal.eu/eventid/`
- `https://www.seismicportal.eu/terms.html`
