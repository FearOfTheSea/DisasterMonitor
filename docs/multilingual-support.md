# Multilingual support

DisasterMonitor treats the user's language as a model-boundary concern and keeps
the trusted disaster workflow language-neutral:

```text
original request
    -> Qwen structured interpretation
    -> bounded canonical draft
    -> deterministic enum/catalog/date validation
    -> canonical provider query and evidence reconciliation
    -> deterministic grounded report
    -> optional bounded response localization
```

`StructuredAgentModel.interpret()` asks Qwen for a strict draft containing only
maintained disaster, information-need, output-modality, geography, scope, date,
and response-language concepts. The application does not accept model-created
metadata: disasters and enum values must be supported domain values, and a
country proposal must resolve through `CountryCatalog` with consistent canonical
identity. Canonical drafts construct `DisasterQuery` directly, so retrieval and
provenance do not depend on the language of the original request.

When no agent model is configured, the existing deterministic parser remains the
safe compatibility fallback. A malformed or failed interpretation cannot expand
scope or bypass catalog and evidence validation.

## Response language and safety

The interpreted response language is carried explicitly through the validated
task. General answers receive a language instruction at the general-model
boundary. Grounded reports are localized only from application-produced report
content, in bounded chunks. Source URLs, event IDs, numbers, dates, source
attribution, uncertainty, and limitations must remain present. If localization
fails or drops protected grounded content, the deterministic grounded report is
returned unchanged and a warning records that fallback.

There is no runtime supported-language allowlist. Any safely bounded language tag
returned by the model may be attempted. The languages below are verified coverage,
not an admission gate or a claim of complete grammar coverage. Actual coverage
remains model-dependent.

## Verification record

Verification date: 2026-08-21  
Configured Qwen model: `qwen3:4b-instruct-2507-q4_K_M`

Deterministic fake-model tests covered equivalent basic current-earthquake
requests in English, Vietnamese, Chinese, Korean, and Japanese; focused
fatalities semantics; general-knowledge delegation; invalid structured output;
invented disaster and geography values; interpreter failure; response-language
override; and grounded-localization fallback.

Real end-to-end requests were sent through the running API for all five languages.
Focused fatalities requests about the latest Indonesia earthquake reached the
source-backed workflow, selected the USGS event `usgs:us6000tkt2`, retained the
ReliefWeb source URLs and the preliminary 69-fatality figure, and produced
user-facing output in English, Vietnamese, Chinese, Korean, and Japanese across
the repeated smoke runs. Full narrative reports may safely remain deterministic
when the local model cannot preserve all grounded content during localization;
the focused localized responses were the verified language behavior.

The smoke run also exercised:

- an unsupported `Atlantis` geography, which failed closed with no event or
  retrieval;
- a United States tropical-cyclone request that returned a source-backed
  verification/no-match degradation rather than inventing an event; and
- a worldwide tropical-cyclone request that selected a GDACS event while clearly
  reporting the configured worldwide coverage boundary.

Independent official-provider checks before the smoke run included GDACS listings
for the August 2026 Indonesia earthquake sequence and ONE-C-26. The assistant's
Indonesia result agreed on the source-backed magnitude-7.7 event family and
retained the provider attribution; the United States country query deliberately
remained a no-match/degraded result when the configured country-scoped provider
did not return a matching event.

This record verifies the request-routing, canonical validation, source-backed
retrieval, response-language, and safe-degradation behaviors exercised above. It
does not claim complete support for every language, script, dialect, query form,
or model version.

Adding another language should not require adding that language's disaster,
current-event, or information-need vocabulary to application regexes or alias
tables. It requires model coverage and a corresponding deterministic smoke check.
