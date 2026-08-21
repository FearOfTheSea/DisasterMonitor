# Agent runtime

DisasterMonitor follows one rule:

`LLM-first orchestration, evidence-first truth`

The model may interpret requests and propose plans. Deterministic validation, allowlisted tools, provider capabilities, and normalized evidence establish current facts.

## Request flow

```text
User request
    ↓
Interpret task
    ↓
Validate and safety gate
    ↓
Plan investigation
    ↓
Run allowlisted tools
    ↓
Build evidence workspace
    ↓
Review sufficiency
    ↓
Compose grounded answer
```

`RunDisasterAgent` is the application entry point for assistant requests.

Non-disaster and general-knowledge requests may use the general model path. Disaster investigations use the bounded agent runtime.

## Runtime

- Agent interpretation is validated against exact fields, enums, and known metadata.
- Invalid interpretation falls back to deterministic disaster routing when possible.
- The agent cannot invent trusted countries, providers, authorities, URLs, or evidence.
- The default investigation plan works without Ollama.
- Tools enforce prerequisites and write normalized artifacts to a request-scoped evidence workspace.
- `CurrentDisasterReportService` remains a compatibility facade over the same tool path.

Default disaster flow:

```text
list_sources_for_task
find_disaster_event
retrieve_situation_evidence
reconcile_disaster_evidence
compose_disaster_answer
```

When admitted multimodal assets exist, visual analysis and common-operational-picture steps may be inserted before composition.

## Execution limits

A request is bounded to:

- 8 plan steps
- 12 tool calls
- 4 model operations
- 1 replan decision

The runtime does not allow:

- recursion or autonomous workers
- arbitrary code or command execution
- dynamic imports
- arbitrary filesystem access
- model-selected providers or URLs
- generated SQL
- unrestricted network access

## Evidence

Current answers are composed from normalized evidence, not model memory.

The evidence workspace may contain:

- selected physical-event identity
- provider observations
- reconciled world state
- evidence packets
- gaps and conflicts
- inferred hypotheses
- triage and decision-support artifacts
- admitted multimodal observations

Verified facts, preliminary observations, disputed claims, estimates, and hypotheses remain distinct.

Missing evidence is not treated as zero.

## Authority

The agent may reason about evidence, but deterministic policy controls authority.

- Provider registry determines available sources.
- Source metadata determines authority and scope.
- High-consequence actions remain prohibited or require human review.
- Analytical outputs cannot promote themselves into verified facts.
- Multimodal observations cannot replace source-backed disaster evidence.
- Source candidates cannot become trusted providers at runtime.

## Coordination

Specialist coordination is bounded and request-scoped.

Handoffs require typed artifacts, provenance, declared ownership, and existing permissions. Specialists cannot create new authority or mutate canonical evidence.

Invalid provenance, privilege escalation, policy drift, conflicts, or budget overruns fall back to the existing single-supervisor result.

## State

Agent state is request-scoped.

There is no persistent agent memory, continuous investigation loop, autonomous background monitoring, cross-request evidence recovery, or unrestricted self-modification.

The assistant separately persists a durable textual conversation transcript for UI
history. It stores message IDs, roles, text, and timestamps only. Historical text is
not added to model prompts and does not restore agent state, evidence workspaces,
reports, tool state, or multimodal state; every request still runs from its current
question.
