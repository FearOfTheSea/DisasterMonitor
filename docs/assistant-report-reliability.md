# Assistant report retrieval reliability

## Diagnosis

A natural-language request for a recent Pakistan flood report reproduced
`current_disaster_verification_failed` on September 8, 2026. The existing model
correctly routed it to flood investigation, but GDACS returned no Pakistan events.
An independent lookup verified GDACS FL 1104136 (August 31–September 2).

The GDACS search request omitted `alertlevel`. The live API's default returned only
four flood records; explicitly requesting `Green;Orange;Red` returned 69, including
the Pakistan event. Alert level is a modelled humanitarian-impact classification,
not an occurrence threshold. Discovery now explicitly includes all three levels for
every supported GDACS hazard, retaining existing bounded pagination and admission.
Named-country requests also send the maintained country name to GDACS before
pagination, reducing response size and avoiding unrelated global records consuming
the country query budget. GDACS uses country names, not ISO-3 codes, for this filter.
An empty name-filtered scan falls back once to the bounded global scan because source
and maintained country names can differ. If the scoped request exhausts transient
retries, the same one-scan fallback is attempted and retained as a typed
degradation. Returned ISO-3 country associations are still validated locally.
Snapshot request identity includes the alert and country filters.

A second gap was acquisition: GDACS was registered only for discovery. Its event
list establishes an event but does not fill human-impact or damage sections. The
new event-linked situation provider retrieves observed impacts from the detail API.

## Design

The existing frontend, assistant HTTP contract, application tools, provider registry,
and deterministic report renderer remain the integration path:

1. Normalize user intent into a validated hazard, country, and time scope.
2. Acquire bounded event candidates from every eligible provider, explicitly including
   all alert levels; retain source failures separately.
3. Resolve event identity using existing country/hazard/provenance constraints.
4. Retrieve situation evidence from eligible providers, including GDACS details only
   when an exact GDACS event identifier is already linked to the selected event.
   If GDACS's JSON detail endpoint is transiently unavailable, the situation adapter
   uses one bounded official hazard report-page fallback and retains a typed warning.
5. Reconcile scoped observations, preserving dates, revisions, missing fields, and
   source authority. Do not combine regional counts into unsupported totals.
6. Populate the existing report sections with attributable facts and display precise
   gaps for evidence that remains unavailable.

Infrastructure owns GDACS request/response semantics. Application owns selection,
correlation and report completeness. The domain's existing facts and source references
carry observations to presentation; no new transport contract or frontend policy is
required. The source catalog declares the new executable capability independently of
its registration and remains checked at startup.

## Bounds

Consistent reporting means retrieving available evidence reliably, not guaranteeing
that every section has a figure. Curated catalogs can miss events; external providers
can fail; humanitarian reporting may lag or lack exact event correlation. The system
must continue to disclose these conditions. Worldwide reports retain their existing
event-discovery scope; the new observed-impact path serves named-country reports.

See [GDACS observed impacts](sources/gdacs-situation-reports.md) for admission rules.

## Deterministic validation

Regression coverage includes the GDACS default-alert omission, country-name request
semantics, one bounded fallback for source country-name differences, and rejection
of unrelated ISO-3 associations after fallback. The Sendai adapter is exercised
through the real evidence reconciler with the Pakistan detail fixture, including
snapshot provenance, unsupported/modelled observations, invalid/future timestamps,
foreign-country rows, and distinct sub-day observation intervals.

The existing desktop report renderer now preserves line breaks between observations.
Browser validation reproduced collapsed lines before the CSS correction and confirmed
`pre-line` rendering afterward, with no console errors.
