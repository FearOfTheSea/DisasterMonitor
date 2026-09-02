# Multilingual support

DisasterMonitor treats the user’s language as a model-boundary concern. The trusted
disaster workflow remains language-neutral.

```text
original request
    -> Qwen structured interpretation
    -> bounded canonical draft
    -> deterministic enum/catalog/date validation
    -> canonical provider query and evidence reconciliation
    -> deterministic grounded report
    -> optional bounded response localization
```

`StructuredAgentModel.interpret()` asks Qwen for a strict draft. The draft contains
only maintained disaster, information-need, output-modality, geography, scope,
date, and response-language concepts.

The application does not accept model-created metadata. Disasters and enum values
must be supported domain values.

A country proposal must resolve through `CountryCatalog` with consistent canonical
identity.

Canonical drafts construct `DisasterQuery` directly. Retrieval and provenance do not
depend on the language of the original request.

When no agent model is configured, the deterministic parser remains the safe
compatibility fallback.

A malformed or failed interpretation cannot expand scope or bypass catalog and
evidence validation.

## Response language and safety

The validated task carries the interpreted response language.

General answers receive a language instruction at the general-model boundary.
Grounded reports are localized only from application-produced report content, in
bounded chunks.

Keep source URLs, event IDs, numbers, dates, source attribution, uncertainty, and
limitations in every localized report.

If localization fails or drops protected grounded content, return the deterministic
grounded report unchanged. Record a warning for the fallback.

There is no runtime supported-language allowlist. The runtime can attempt any safely
bounded language tag returned by the model.

The languages below are verified coverage. They are not an admission gate or a claim
of complete grammar coverage. Actual coverage remains model-dependent.

## Verification record

Verification date: 2026-08-21  
Configured Qwen model: `qwen3:4b-instruct-2507-q4_K_M`

Deterministic fake-model tests covered equivalent basic current-earthquake requests
in English, Vietnamese, Chinese, Korean, and Japanese.

They also covered focused fatalities semantics, general-knowledge delegation,
invalid structured output, invented disaster and geography values, interpreter
failure, response-language override, and grounded-localization fallback.

Real end-to-end requests used the running API for all five languages.

Focused fatalities requests about the latest Indonesia earthquake reached the
source-backed workflow. They selected USGS event `usgs:us6000tkt2`.

The requests retained ReliefWeb source URLs and the preliminary 69-fatality figure.
They produced user-facing output in English, Vietnamese, Chinese, Korean, and
Japanese during repeated smoke runs.

Full narrative reports can remain deterministic when the local model cannot preserve
all grounded content during localization. The focused localized responses verified
the language behavior.

The smoke run also exercised these cases:

- An unsupported `Atlantis` geography failed closed without event or retrieval.
- A United States tropical-cyclone request returned source-backed verification and
  no-match degradation instead of inventing an event.
- A worldwide tropical-cyclone request selected a GDACS event and reported the
  configured worldwide coverage boundary.

Independent official-provider checks preceded the smoke run. They included GDACS
listings for the August 2026 Indonesia earthquake sequence and ONE-C-26.

The Indonesia result agreed on the source-backed magnitude-7.7 event family and kept
provider attribution.

The United States query remained a no-match or degraded result because the configured
country-scoped provider returned no matching event.

This record verifies request routing, canonical validation, source-backed retrieval,
response language, and safe degradation for the cases above.

It does not claim complete support for every language, script, dialect, query form,
or model version.

Adding another language should not require language-specific disaster, current-event,
or information-need vocabulary in application regexes or alias tables.

It requires model coverage and a corresponding deterministic smoke check.
