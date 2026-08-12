# Disaster source capabilities

Disaster Monitor parses a recognized current-disaster request into one typed hazard
and one canonical country, then selects providers by declared capability. Event
verification and situation evidence are separate roles: an event can be verified even
when no impact source supports it. If no event provider supports the combination, the
API returns `current_disaster_coverage_unavailable` and makes no live factual claim.

The provider matrix records implemented live source coverage only. It is separate
from automated and normative promotion status; see
[Capability and promotion status](capability-status.md).

A versioned source-intelligence catalog links every executable provider to a stable
`source_id`, exact HTTPS authorities, and a maintained playbook under `docs/sources/`.
Source listing joins this semantic metadata with capability selection; catalog data
never dynamically imports or constructs providers.

## Current live capability matrix

| Provider                   | Role                             | Hazards            | Countries                                  | Additional requirement              |
| -------------------------- | -------------------------------- | ------------------ | ------------------------------------------ | ----------------------------------- |
| JMA rolling earthquake     | Event discovery                  | Earthquake         | Japan (`JPN`)                              | None                                |
| JMA significant earthquake | Event discovery                  | Earthquake         | Japan (`JPN`)                              | None                                |
| USGS                       | Event discovery                  | Earthquake         | Global within the packaged country catalog | Country coordinate validation       |
| FDMA                       | Situation evidence               | Earthquake         | Japan (`JPN`)                              | Matching official report            |
| JMA tsunami status         | Situation evidence               | Earthquake         | Japan (`JPN`)                              | Selected event has a JMA identifier |
| ReliefWeb                  | Supplementary situation evidence | Recognized hazards | Global                                     | Approved `RELIEFWEB_APP_NAME`       |

Earthquakes can therefore receive real event verification for Japan, Vietnam, and
Venezuela, the countries in catalog version 1.0.0. Japan additionally has configured
national situation providers. Tsunami, flood, wildfire, landslide, and tropical
cyclone requests are recognized but currently return coverage unavailable because no
event-discovery provider for those hazards is registered. ReliefWeb alone cannot verify
an event and is never treated as an official national total.

The API accepts bounded operator-supplied PNG/JPEG bytes with explicit provenance and
event metadata. Associated images may produce local analytical observations and a
typed vector COP; this request boundary is not a live provider and does not alter the
catalog above. Image retrieval, satellite/aerial monitoring, live raster products,
official-warning overlay providers, CARTO, TerraLabo, and online source crawling remain
unsupported. Structured source-candidate metadata can be screened into a separate
review queue, but it cannot alter this matrix or contribute evidence.

Triage, advisory decision support, deterministic specialist coordination, and governed
analytical follow-up ordering are implemented over admitted evidence. They do not add
provider coverage and cannot issue public warnings, evacuation directives, or resource
orders.

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

All hazard policies produce the same generic `PhysicalEventIdentity` contract. They
must preserve normalized observations and deterministic assignment rationale, enforce
hazard/country boundaries, and leave non-transitive or otherwise confusable assignment
sets explicit. Temporal evidence and hypotheses are hazard-neutral artifacts; a
hazard-specific rule may be added only as application policy over canonical evidence,
never inside provider transport.

## Geography metadata

The packaged country metadata records ISO alpha-3 codes, canonical English names,
declared exact aliases, query bounds, simplified polygons, and deterministic calendar
offsets. The initial codes/names follow ISO 3166-1; geographic extents are simplified
from Natural Earth 1:110m Admin 0 data, which is public domain. Polygons are query and
validation approximations, not legal borders or maritime claims. Japan uses UTC+09:00,
Vietnam UTC+07:00, and Venezuela UTC-04:00; none of these defaults has a seasonal
daylight-saving transition.
