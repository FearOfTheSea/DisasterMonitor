# Event association acceptance criteria

## Purpose

The event catalog and ReliefWeb are different kinds of sources. USGS (or an
approved event provider) establishes which physical event is selected. ReliefWeb
provides supplementary situation evidence that may describe that event. A
country and hazard filter is a retrieval scope, not proof that every returned
report describes the selected event.

The workflow is accepted only when it keeps those roles separate and makes the
association decision visible.

## Acceptance criteria

### Event geography

- An event inside the country's validated polygon is labelled `in_country`.
- An event outside the polygon is admitted only when all of these are true:
  - the provider has supplied an explicit place containing the requested country
    name, alias, or alpha-3 code;
  - the event is within the bounded near-shore distance threshold (currently
    100 km of the packaged polygon); and
  - the result is labelled `country_associated_offshore`.
- An event outside the polygon without those conditions is excluded with a
  `country_mismatch` issue. A bounding box must not silently override polygon
  validation.
- The API exposes the geography status, and the UI distinguishes a country-
  associated offshore event from an in-country event.

### ReliefWeb retrieval

- The adapter requests country, hazard, date, report identity, publication
  metadata, structured disaster metadata, title, body, source, and report
  classification fields supported by the ReliefWeb API.
- Retrieval is broad enough to find relevant reports for the selected country
  and hazard. Event location words and USGS identifiers are not required query
  terms because ReliefWeb may not index them consistently.
- Publication time is used for freshness and retrieval scope. It is not treated
  as the earthquake occurrence time unless ReliefWeb supplies explicit event
  metadata.
- The adapter preserves ReliefWeb identifiers in the `reliefweb:` namespace and
  never equates them with USGS, JMA, or another provider's identifier.

### Report association

- A report is `matched` when it has either a same-namespace matching event ID,
  or at least two independent explicit event clues. Accepted clue pairs include
  event time plus named location, magnitude plus named location, or event time
  plus matching country when the report has structured disaster metadata.
- A report is `possible` when it has only one useful clue. Possible reports may
  be retained for audit but cannot contribute trusted event facts or narrative.
- A report is `unmatched` when it conflicts with the selected hazard/country,
  has a conflicting same-namespace event ID, or has no event-specific clues.
- Narrative extraction is bounded to explicit patterns such as a numeric
  earthquake magnitude and structured event dates. It must not infer damage,
  casualties, or event identity from a model.
- A ReliefWeb country snapshot, regional report, thematic article, or report
  tagged with an earthquake type but lacking event clues is context only. It
  must not be rendered as event-specific situation evidence.
- A report about a different event in the same country is excluded even if it
  has the same hazard and recent publication date.
- Duplicate URLs or duplicate provider records are deduplicated before facts
  enter the evidence packet.

### User-visible behavior

- A successful event selection with no matched ReliefWeb report says that no
  reliable event-specific situation evidence was found; it does not claim that
  no damage occurred.
- Exclusion reasons remain machine-readable and are rendered as concise
  warnings. Provider failure, empty result, possible correlation, and
  unmatched correlation remain distinguishable.
- The selected event, geography status, source URL, report correlation status,
  and evidence omission are auditable from the response or captured source
  snapshot.

## Required regression scenarios

The acceptance suite must cover these situations for more than one country and
hazard where the provider supports them:

1. An in-country earthquake with a ReliefWeb article naming the event location
   and magnitude is matched and its preliminary facts are included.
2. The Flores/Indonesia case: the USGS event is offshore but near Indonesia,
   the USGS place names Indonesia, and the linked ReliefWeb article is matched.
3. A near-shore event whose place names another country is rejected.
4. A far-away event inside a broad country bounding box is rejected.
5. A same-country, different-event article is excluded.
6. A country snapshot or regional multi-country report is retained only as
   non-event context and contributes no event facts.
7. A report with a ReliefWeb disaster ID is matched only to the same ReliefWeb
   ID; that ID cannot collide with a USGS or JMA identifier.
8. A report with magnitude but no location is possible, not matched.
9. A report with location but no independent time or magnitude is possible,
   not trusted event evidence.
10. Missing, malformed, stale, duplicate, rate-limited, and unavailable
    ReliefWeb responses degrade explicitly without changing the selected event.
11. The same association rules work for a non-earthquake supported hazard and
    do not inherit earthquake-only magnitude logic.
12. The API and frontend preserve the association status and accept older
    responses that omit the new optional display field.

## Operational boundary

This policy improves event association; it does not make ReliefWeb an official
damage total, national authority, or event-discovery source. Promotion of a
candidate source into the trusted catalog remains a separate reviewed action.
