# Specialist agents

Specialist coordination is a bounded analytical step over already admitted
artifacts. It never selects providers, performs retrieval, changes canonical
evidence, or changes safety policy. The supervisor retains the completed default
investigation result whenever coordination is incomplete or invalid.

## Roles

| Role | Owned task | Readable artifact | Result |
| --- | --- | --- | --- |
| Supervisor | Coordinates handoffs and termination | Event, evidence, decision, multimodal state, and provenance | A sufficient coordinated result or the default-plan fallback |
| Event identity specialist | `verify_event_identity` | Physical event and provenance | Deterministic identity finding |
| Evidence reconciliation specialist | `review_evidence_state` | Evidence state and provenance | Retained event identity, gaps, and conflicts |
| Decision analysis specialist | `assess_decision_options` | Evidence state, decision support, and provenance | Decision-support findings |
| Multimodal analysis specialist | `review_multimodal_state` | Evidence state, multimodal state, and provenance | Multimodal findings |

Each role receives only its declared read permissions plus
`propose_analysis`. No specialist receives provider-I/O, filesystem, network,
recursive-agent, or safety-policy permissions.

## Handoffs and deterministic baseline

`SpecialistHandoffBroker` issues handoffs only when the task type has its exact
owner role, expected artifact type, complete provenance, and permissions inside
that role's allowlist. A handoff carries the canonical state version, evidence
IDs, source IDs, ownership, and granted permissions. A role cannot silently gain
or lose permissions.

`CollaborativeInvestigator` is deterministic by default. It derives findings
from the evidence state, decision-support artifact, and admitted multimodal
state, then rejects findings that escape their state, provenance, role, or safety
fingerprint. Conflicting findings create a visible deadlock and return the
single-supervisor fallback.

The supervisor allows at most four handoffs, 24 findings, and two iterations. It
also checks required finding keys and an approved analytical release before
reporting an autonomous completion. Any invalid handoff, missing artifact,
budget overrun, conflict, or failed sufficiency check leaves the default plan
authoritative.

## Optional model-backed drafts

Model-backed specialist calls are disabled by default. With
`SPECIALIST_LLM_ENABLED=true`, only the evidence-reconciliation and
decision-analysis roles can each request one draft. Calls are sequential and
have a separate request budget of at most two; `SPECIALIST_MODEL_CALL_LIMIT` may
lower that limit to zero, one, or two.

The model sees a compact, read-only projection of a single admitted artifact. It
has no tools. It returns an untrusted `SpecialistFindingDraft`, which must match
the handoff role and task, exact permissions, canonical state version, safety
fingerprint, a projection key/value, and that item's exact evidence and source
identifiers. Historical-memory identifiers cannot satisfy this item-level
lineage check.

If a model call, handoff, projection, or draft validation fails, all model
findings for that request are discarded. Deterministic coordination and the
single-supervisor result remain available.

## Boundaries

Specialist outputs are analytical findings, not verified facts. They cannot
promote observations, create authority, mutate the evidence workspace, alter
prohibited-action policy, or trigger additional agents. Event identity stays
deterministic, and multimodal analysis remains on the visual-analysis path.
