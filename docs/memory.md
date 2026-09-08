# Historical memory

DisasterMonitor's memory is typed historical context. It is not a source of
current disaster truth and cannot satisfy an evidence requirement. Current
disaster questions always retrieve provider evidence and reconcile it before
historical memory is recalled.

Memory is disabled by default. Set `LONG_TERM_MEMORY_ENABLED=true` to enable
both persistence after an eligible conversation turn and recall during a
disaster investigation.

## Scope and authority

Memory is scoped to one conversation. The current implementation admits only
`physical_event_reference` records; the `conversation_context` type is defined
in the domain model but is not admitted by the policy. A record contains a
bounded historical summary and references to its conversation messages,
physical event, disaster and country identifiers, evidence IDs, and world-state
version. It does not store volatile claims or replace provider observations.

Every record and recalled context artifact has the sole authority
`historical_context` and explicitly cannot satisfy current evidence. Models and
specialists cannot write to or search the memory store.

## Admission and lifecycle

`RunConversationTurn` attempts persistence after it has stored the user and
assistant messages. It only proposes memory for an investigation that has a
physical-event ID, evidence-state version, disaster, and country.

`MemoryPolicy` is the sole admission decision point. It accepts only schema
`agent-memory.v1`, physical-event references with at least `0.9` confidence,
valid lineage, and a non-authoritative historical summary. The generated
candidates use confidence `1.0`, retain for 30 days, and state that current
conditions require newly admitted evidence.

The lifecycle states are `active`, `superseded`, `expired`, and `deleted`.
Saving a new active reference atomically replaces any active reference for the
same conversation and physical event. The policy merges records for the same
world-state version, combining message and evidence references; a changed
version supersedes the prior active record. Recall marks records expired when
their expiry time has passed.

Conversation deletion removes its cascade-owned memory. PostgreSQL performs
this through the conversation foreign key and its transaction boundary; the
in-memory stores stage the two deletions as one operation. No tombstone is kept
after a conversation is deleted.

## Recall

After provider retrieval and evidence reconciliation establish a physical event,
the evidence tool asks `MemoryRecallService` for the matching conversation,
physical event, disaster identifier, and country. Recall considers only active,
unexpired records with matching scope and returns newest records first.

The frozen `MemoryContextArtifact` is capped at five records and 1,500 summary
characters. It retains record identifiers and provenance references alongside
the summaries. It is request-scoped: the runtime does not restore an old plan,
workspace, or investigation from it.

The artifact may be passed to an enabled specialist by the supervisor, but its
identifiers cannot substitute for the specialist projection item's current
evidence and source lineage.

## Persistence

`MemoryStore` is an application port with in-memory and PostgreSQL adapters.
The PostgreSQL `agent_memory` table enforces the allowed lifecycle and authority
values, stores provenance identifier arrays, cascades on conversation deletion,
and has a partial unique index for one active physical-event reference per
conversation scope. The in-memory adapter preserves the same replacement and
deletion semantics for tests and local development.

Memory is deliberately not a global profile, cross-user preference store,
semantic/vector index, continuous-monitoring mechanism, or cross-request
evidence cache.
