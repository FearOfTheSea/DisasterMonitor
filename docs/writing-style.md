# Documentation writing style

This guide adapts ASD-STE100 Simplified Technical English (STE), Issue 9
(2025-01-15), for DisasterMonitor software documentation.

## Vocabulary

Use a controlled vocabulary for general English. Prefer common words such as
“use”, “show”, “start”, “stop”, “check”, “keep”, and “remove”. Use one term for
one concept. Do not add stylistic synonyms.

Keep project-specific technical nouns and verbs unchanged when they name a
software concept. Examples include `provider`, `adapter`, `source catalog`,
`event discovery`, `situation evidence`, `physical event`, `coverage state`,
`scope`, `normalize`, `validate`, `reconcile`, `admit`, `reject`, and `render`.
Use established product names, APIs, identifiers, file paths, environment
variables, protocol terms, and software terms as technical terms.

Use these terms consistently:

- “named country” means one canonical country in the catalog.
- “worldwide” means the explicit countryless scope.
- “disaster” means a typed hazard. “Event” means a physical occurrence.
- “source-backed” means supported by retained provider evidence.
- “current” means retrieved through the current provider workflow.
- “preliminary” or “possible” means an observation that is not a verified fact.
- “unavailable” and “degraded” describe different coverage states.

## Sentences and paragraphs

Use active voice. Use passive voice only when the agent is unknown or the active
form would reduce accuracy. Put the main topic first. Use short sentences and
avoid unnecessary nominalizations, phrasal verbs, idioms, vague references, and
parenthetical text.

Keep descriptive sentences to 25 words or fewer where practical. Keep each
descriptive paragraph to one topic and no more than six sentences. Give details
in a gradual order: purpose, behavior, limits, and evidence.

## Procedures and descriptions

Use imperative sentences for procedures. Put one action in each instruction
sentence. Keep each instruction sentence to 20 words or fewer. Separate
prerequisites, conditions, actions, results, notes, warnings, and limitations.

Use descriptive text for architecture, behavior, source limits, and status. Use
tables and short lists when they make technical information easier to scan.

## Compliance boundary

This guide supports ASD-STE100-aligned writing. It does not constitute certified
dictionary-level ASD-STE100 compliance. Technical terminology can require an
intentional exception to the general vocabulary rules.
