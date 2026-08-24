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
- 2 specialist-model calls when the specialist rollout is enabled
- 1 replan decision

Specialist-model calls have separate accounting from interpretation, planning,
review, localization, and visual-model calls. The two supported model-backed roles
run sequentially through the configured text model; no additional text model or
parallel Ollama worker is constructed. The remaining specialist budget is carried in
request state and checked on every execution, so repeated composition cannot reset the
two-call ceiling. Trusted built-in workflow tools may appear only once in a validated
plan.

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

The deterministic collaboration remains the baseline and is the default. When
`SPECIALIST_LLM_ENABLED=true`, only evidence reconciliation and decision analysis
may request one model draft each. Event identity remains deterministic and
multimodal analysis remains on the visual-analysis path. Each model-backed
specialist receives a compact read-only projection of already-admitted artifacts,
has no tools, provider/network/filesystem access, or recursive-agent authority, and
returns an untrusted `SpecialistFindingDraft`. Application policy validates role and
task ownership, granted permissions, state lineage, evidence/source membership,
provenance, safety fingerprint, contradictions, and budgets before constructing a
trusted finding. The returned key/value must select one exact projection item and its
evidence/source identifiers must exactly equal that item's current-evidence lineage;
projection-wide or historical-memory identifiers cannot substitute for item lineage.
Any model or validation failure discards all model findings for the request and retains
the deterministic result without changing canonical evidence.

## State

DisasterMonitor keeps five state categories deliberately separate:

1. **Durable conversation transcripts.** `ConversationStore` retains message IDs,
   roles, text, timestamps, and versioned assistant response payloads for the UI and
   conversation lifecycle. Deleting a conversation atomically and physically removes
   its cascade-owned transcript and derived memory. PostgreSQL performs one
   conversation delete in a transaction and relies on the maintained `ON DELETE
   CASCADE` ownership invariant; the in-memory implementation applies the same
   all-or-nothing semantics. Conversation deletion does not retain memory tombstones.
2. **Bounded conversational history.** For applicable general-model requests, the
   newest whole transcript messages are selected deterministically, capped at eight
   messages and 6,000 characters, and included as non-authoritative prompt context.
   User turns may also resolve a narrowly referential disaster follow-up. Assistant
   text never establishes a disaster anchor or current fact.
3. **Typed long-term historical memory.** When
   `LONG_TERM_MEMORY_ENABLED=true`, `MemoryStore` separately retains validated,
   high-confidence conversation/physical-event references with lifecycle states
   `active`, `superseded`, `expired`, and `deleted`. Recall is deterministic,
   conversation-isolated, capped at five records and 1,500 characters, and may use
   an already-resolved physical event plus disaster/country identifiers. It stores
   references such as physical-event ID, evidence IDs, and prior state version rather
   than volatile current claims. Models and specialists cannot write or search the
   store; policy alone admits candidates, and specialists receive only a supervisor-
   created frozen `MemoryContextArtifact`.
4. **Request-scoped agent/evidence state.** Plans, tool state, workspaces, handoffs,
   analytical findings, multimodal state, and recalled memory context exist only for
   the current request. They are not restored as an autonomous investigation.
5. **Canonical operational evidence.** Provider snapshots, normalized observations,
   physical-event identity, and versioned world state retain their existing source,
   provenance, and authority rules. This persistence is distinct from transcripts
   and memory.

Conversation history and typed long-term memory are both historical,
non-authoritative context. Neither can become a verified fact, provider observation,
trusted source, or current world-state claim. Questions about current disaster
conditions always run the normal provider retrieval and deterministic reconciliation
flow before historical references are recalled or exposed to specialists.

There is no continuous investigation loop, autonomous background monitoring,
cross-request evidence recovery from memory, global personal memory, cross-user
preference memory, semantic/vector retrieval, or unrestricted self-modification.
