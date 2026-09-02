# Agent runtime

DisasterMonitor follows one rule:

`LLM-first orchestration, evidence-first truth`

The model interprets requests and can propose plans. Deterministic validation,
allowlisted tools, provider capabilities, and normalized evidence establish
current facts.

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
Deterministic evidence-sufficiency gate
    ↓
Bounded policy-authorized follow-up, if selected
    ↓
Reassess sufficiency
    ↓
Compose grounded answer exactly once
```

`RunDisasterAgent` is the application entry point for assistant requests.

Non-disaster and general-knowledge requests can use the general model path.
Disaster investigations use the bounded agent runtime.

## Runtime behavior

- Validate agent interpretation against exact fields, enums, and known metadata.
- Use deterministic disaster routing when interpretation is invalid but routing is
  possible.
- Prevent the agent from inventing trusted countries, providers, authorities, URLs,
  or evidence.
- Run the default investigation plan without Ollama.
- Enforce tool prerequisites and write normalized artifacts to a request-scoped
  evidence workspace.
- Keep `CurrentDisasterReportService` as a compatibility facade over the same tool
  path.

Tool contracts, budgets, and typed state are shared. Implementations remain
separate for source, evidence, decision, and coordination capabilities.

Each tool receives the smallest applicable dependency bundle. The runtime has no
dynamic plugin or service-locator path.

The default disaster flow is:

```text
list_sources_for_task
find_disaster_event
retrieve_situation_evidence
reconcile_disaster_evidence
compose_disaster_answer
```

The runtime validates the initial plan, executes its pre-composition steps, and
then performs an application-owned evidence-sufficiency assessment. The
assessment has one of three stable states: `sufficient`,
`followup_available`, or `terminal_gap`. It reports bounded gap codes rather than
provider or model prose. Composition is always the final step of a validated
trusted disaster plan and is not available to the review model as a way to skip
evidence stages.

At most one follow-up can be executed for a request. Production policy can offer
only a retry of event discovery when no event was established and a retryable
provider issue was admitted, or a retry of situation evidence when a selected
event exists and a retryable provider issue was admitted. The event retry reruns
its dependent situation retrieval and reconciliation; the situation retry reruns
retrieval and reconciliation. Empty successful lookups, non-retryable issues,
unsupported roles, missing configuration, and ordinary capability gaps do not
create follow-up options. The model can select only an exact option ID supplied
by the application; it cannot provide a provider, URL, tool, argument, or plan.
Invalid, failed, or unavailable model review safely finishes with the already
admitted evidence. Counters and specialist budgets continue across both phases.

After a follow-up, the application reassesses sufficiency without permitting a
second replan. A failed retry retains first-pass evidence and the final report
preserves its partial or degraded status.

When admitted multimodal assets exist, the runtime can insert visual analysis and
Common Operational Picture steps before composition.

Response localization and contextual-media discovery keep their user-facing
fallback behavior. Failures emit a typed diagnostic, a structured log entry, and a
low-cardinality metric. User responses do not expose internal exception details.

## Execution limits

A request has these limits:

- 8 plan steps
- 12 tool calls
- 4 model operations
- 2 specialist-model calls when specialist rollout is enabled
- 1 replan decision

The one replan decision is a single application-authorized follow-up selection;
it does not reset the tool, model, or specialist counters.

Specialist-model calls have separate accounting from interpretation, planning,
review, localization, and visual-model calls. The two supported model-backed roles
run sequentially through the configured text model.

The runtime does not construct another text model or a parallel Ollama worker.
Request state carries the remaining specialist budget. Each execution checks that
budget, so repeated composition cannot reset the two-call limit.

Trusted built-in workflow tools can appear only once in a validated plan.

Each request also carries a non-persisted deterministic decision trace. It records
stable lifecycle events such as task and plan validation, tool outcomes,
sufficiency assessments, review decisions, follow-up selection or rejection,
composition, and termination. It contains no raw prompts, chain-of-thought,
provider payloads, or unrestricted provider text. A pure replay validator can
reconstruct the decision sequence and rejects multiple replans, out-of-order or
duplicate composition, events after termination, and represented budget
violations. Replay validates decisions; it does not replay provider I/O.

The runtime does not allow:

- recursion or autonomous workers
- arbitrary code or command execution
- dynamic imports
- arbitrary filesystem access
- model-selected providers or URLs
- generated SQL
- unrestricted network access

## Evidence

Current answers use normalized evidence, not model memory.

The evidence workspace can contain:

- selected physical-event identity
- provider observations
- reconciled world state
- evidence packets
- gaps and conflicts
- inferred hypotheses
- triage and decision-support artifacts
- admitted multimodal observations

Keep verified facts, preliminary observations, disputed claims, estimates, and
hypotheses distinct.

Missing evidence is not zero evidence.

## Authority

The agent can reason about evidence. Deterministic policy controls authority.

- The provider registry determines available sources.
- Source metadata determines authority and scope.
- High-consequence actions remain prohibited or require human review.
- Analytical outputs cannot promote themselves to verified facts.
- Multimodal observations cannot replace source-backed disaster evidence.
- Source candidates cannot become trusted providers at runtime.

## Coordination

Specialist coordination is bounded and request-scoped.

Handoffs require typed artifacts, provenance, declared ownership, and existing
permissions. Specialists cannot create authority or mutate canonical evidence.

Invalid provenance, privilege escalation, policy drift, conflicts, or budget
overruns use the existing single-supervisor result.

Deterministic collaboration is the baseline and the default. When
`SPECIALIST_LLM_ENABLED=true`, only evidence reconciliation and decision analysis
can request one model draft each.

Event identity remains deterministic. Multimodal analysis remains on the
visual-analysis path.

Each model-backed specialist receives a compact read-only projection of admitted
artifacts. It has no tools, provider access, network access, filesystem access, or
recursive-agent authority.

Each specialist returns an untrusted `SpecialistFindingDraft`. Application policy
checks role, task ownership, granted permissions, state lineage, evidence and source
membership, provenance, safety fingerprint, contradictions, and budgets.

The returned key must select one exact projection item. Its evidence and source
identifiers must equal that item’s current-evidence lineage. Projection-wide or
historical-memory identifiers cannot replace item lineage.

Any model or validation failure discards all model findings for the request. The
runtime retains the deterministic result and does not change canonical evidence.

## State

DisasterMonitor keeps five state categories separate.

1. **Durable conversation transcripts.** `ConversationStore` retains message IDs,
   roles, text, timestamps, and versioned assistant response payloads for the UI and
   conversation lifecycle. Conversation deletion atomically and physically removes
   its cascade-owned transcript and derived memory.

   PostgreSQL performs one conversation delete in a transaction. It relies on the
   maintained `ON DELETE CASCADE` ownership invariant. The in-memory implementation
   has the same all-or-nothing behavior. Conversation deletion does not retain
   memory tombstones.
2. **Bounded conversational history.** For applicable general-model requests, the
   runtime selects the newest whole transcript messages. It caps them at eight
   messages and 6,000 characters. It sends them as non-authoritative prompt
   context. User turns can resolve a narrowly referential disaster follow-up.
   Assistant text cannot establish a disaster anchor or current fact.
3. **Typed long-term historical memory.** When `LONG_TERM_MEMORY_ENABLED=true`,
   `MemoryStore` separately retains validated, high-confidence conversation and
   physical-event references. Lifecycle states are `active`, `superseded`,
   `expired`, and `deleted`. Recall is deterministic and capped at five records and
   1,500 characters. Recall can use an already-resolved physical event plus disaster
   and country identifiers.

   The store keeps references such as physical-event ID, evidence IDs, and prior
   state version. It does not keep volatile current claims. Models and specialists
   cannot write or search the store. Policy alone admits candidates. Specialists
   receive only a supervisor-created frozen `MemoryContextArtifact`.

   Persistence atomically replaces the active physical-event reference in a
   conversation scope. PostgreSQL enforces at most one active reference in that
   scope.
4. **Request-scoped agent and evidence state.** Plans, tool state, workspaces,
   handoffs, analytical findings, multimodal state, and recalled memory context
   exist only for the current request. The runtime does not restore them as an
   autonomous investigation.
5. **Canonical operational evidence.** Provider snapshots, normalized
   observations, physical-event identity, and versioned world state retain their
   existing source, provenance, and authority rules. This persistence is separate
   from transcripts and memory.

Conversation history and typed long-term memory are historical, non-authoritative
context. Neither can become a verified fact, provider observation, trusted source,
or current world-state claim.

Questions about current disaster conditions always run provider retrieval and
deterministic reconciliation before the runtime recalls historical references or
exposes them to specialists.

The runtime has no continuous investigation loop or autonomous background monitoring.
It has no cross-request evidence recovery from memory, global personal memory,
cross-user preference memory, semantic or vector retrieval, or unrestricted
self-modification.
