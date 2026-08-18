# Disaster source capabilities

Disaster Monitor parses a recognized current-disaster request into one typed hazard
and an explicit geographic scope (one canonical country or worldwide), then selects
providers by declared capability. Event
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

| Provider                   | Tier      | Role                             | Hazards            | Countries                     | Additional requirement              |
| -------------------------- | --------- | -------------------------------- | ------------------ | ----------------------------- | ----------------------------------- |
| JMA rolling earthquake     | Primary   | Event discovery                  | Earthquake         | Japan (`JPN`)                 | None                                |
| JMA significant earthquake | Secondary | Event discovery                  | Earthquake         | Japan (`JPN`)                 | None                                |
| USGS                       | Secondary | Event discovery                  | Earthquake         | Named countries and worldwide | Country validation for named scope  |
| FDMA                       | Primary   | Situation evidence               | Earthquake         | Japan (`JPN`)                 | Matching official report            |
| JMA tsunami status         | Secondary | Situation evidence               | Earthquake         | Japan (`JPN`)                 | Selected event has a JMA identifier |
| ReliefWeb                  | Secondary | Supplementary situation evidence | Recognized hazards | Global                        | Approved `RELIEFWEB_APP_NAME`       |

USGS earthquake verification applies to every country admitted by the active catalog;
this is global named-country coverage, with one explicitly named country per request.
Here, `country_codes=None` means all admitted named countries only; it does not grant
countryless worldwide authority. Worldwide authority is an explicit provider scope.
“News” requests are deterministically routed to that evidence path. Country names are
case-insensitive, while short ISO codes are uppercase-only to avoid collisions with
ordinary language in the global alias set.
The packaged fallback initially contains Japan, Vietnam, and Venezuela. The autonomous
catalog updater can promote global Natural Earth country metadata without widening any
provider's declared role or hazard. Japan additionally has configured national
situation providers. Other hazards depend on the executable registrations shown above;
ReliefWeb alone cannot verify an event and is never treated as an official national
total.

Explicit worldwide, global, or across-the-world requests use a bounded worldwide
provider query and the selected hazard policy. Earthquake policy selects the latest
event by default or the strongest event when requested; other hazards use the shared
latest policy unless they register another policy. Worldwide requests do not invent a
country for offshore events. Worldwide scope currently provides scientific event
discovery only; it does not provide globally complete
casualty, damage, warning, or response evidence, and every response states that gap.

The API accepts bounded operator-supplied PNG/JPEG bytes with explicit provenance and
event metadata. Associated images may produce local analytical observations and a
typed vector COP; this request boundary is not a live provider and does not alter the
catalog above. Separately, the assistant can display bounded contextual source photos
associated with the already-selected event. That gallery uses exact registered page and
asset hosts and remains outside the provider/evidence matrix. Analytical or satellite/
aerial image retrieval, live raster products, official-warning overlay providers,
CARTO, TerraLabo, and open-ended source crawling remain unsupported. Structured
source-candidate metadata can be screened into a separate review queue, but it cannot
alter this matrix or contribute evidence. See
[Event-associated source media](event-media.md).

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

The packaged fallback records three preservation countries. The autonomous updater
generates a content-versioned global catalog from a released Natural Earth 1:50m Admin
0 revision and the latest validated IANA tzdata archive. It retains source revisions,
checksums, licenses, canonical names, unambiguous aliases, query bounds, simplified
polygons, and deterministic default timezones. Polygons are query approximations, not
legal borders or maritime claims. See
[Autonomous country catalog updates](country-catalog-automation.md).
