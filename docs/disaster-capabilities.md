# Disaster source capabilities

Disaster Monitor parses a recognized current-disaster request into one typed hazard
and one canonical country, then selects providers by declared capability. Event
verification and situation evidence are separate roles: an event can be verified even
when no impact source supports it. If no event provider supports the combination, the
API returns `current_disaster_coverage_unavailable` and makes no live factual claim.

## Current live capability matrix

| Provider | Role | Hazards | Countries | Additional requirement |
| --- | --- | --- | --- | --- |
| JMA rolling earthquake | Event discovery | Earthquake | Japan (`JPN`) | None |
| JMA significant earthquake | Event discovery | Earthquake | Japan (`JPN`) | None |
| USGS | Event discovery | Earthquake | Global within the packaged country catalog | Country coordinate validation |
| FDMA | Situation evidence | Earthquake | Japan (`JPN`) | Matching official report |
| JMA tsunami status | Situation evidence | Earthquake | Japan (`JPN`) | Selected event has a JMA identifier |
| ReliefWeb | Supplementary situation evidence | Recognized hazards | Global | Approved `RELIEFWEB_APP_NAME` |

Earthquakes can therefore receive real event verification for Japan, Vietnam, and
Venezuela, the countries in catalog version 1.0.0. Japan additionally has configured
national situation providers. Tsunami, flood, wildfire, landslide, and tropical
cyclone requests are recognized but currently return coverage unavailable because no
event-discovery provider for those hazards is registered. ReliefWeb alone cannot verify
an event and is never treated as an official national total.

## Extension procedure

To add a provider, implement the relevant application port in a focused infrastructure
adapter, translate records into domain types with typed source authority, and add one
`ProviderRegistration` in the composition root with role, hazards, country scope,
configuration state, and any selected-event predicate. Add selector, adapter, failure,
and exclusion tests. Generic orchestration should not change.

To add hazard behavior, register a policy implementing ranking, physical-event
equivalence, sequence handling, and ambiguity. Add a report profile only when the
hazard needs sections beyond the generic human impact, physical/infrastructure impact,
emergency response, gaps, sources, and freshness sections.

## Geography metadata

The packaged country metadata records ISO alpha-3 codes, canonical English names,
declared exact aliases, query bounds, simplified polygons, and deterministic calendar
offsets. The initial codes/names follow ISO 3166-1; geographic extents are simplified
from Natural Earth 1:110m Admin 0 data, which is public domain. Polygons are query and
validation approximations, not legal borders or maritime claims. Japan uses UTC+09:00,
Vietnam UTC+07:00, and Venezuela UTC-04:00; none of these defaults has a seasonal
daylight-saving transition.
