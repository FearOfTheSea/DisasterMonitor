# P4 long-term capabilities

P4 is implemented as bounded research and accessibility foundations, not as a blanket
expansion into emergency-response coordination. The authority boundary from ADR 0001
continues to apply.

## Implemented bounded foundations

### Open signal triage (tasks 120–121)

`OpenSocialSignalLane` can consume an explicitly configured open RSS/Atom-style feed
only when its source ID matches reviewed public/self-hosted terms. It emits
`UntrustedSocialSignal` records with HTTPS lineage, `authority=untrusted_signal`, and
`creates_physical_event=false`.

`LocalSignalTriageClassifier` uses operator-labelled examples and a deterministic,
versioned local token-overlap policy. It records every training label ID. Its result is
only a discovery category and can never change authority. No live social publisher is
enabled by default.

### Imagery micro-review (task 122)

Independent operator labels can be aggregated for one immutable analytical finding
hash. Duplicate reviewer labels fail closed. A quorum may support analytical
confidence, but the summary remains `analytical_observation` and
`official_damage_claim=false`.

### Scenarios and replay (tasks 123–124)

Planning scenarios and historical replays require pinned source snapshot IDs and carry
`simulated=true`. The application rejects any attempt to target canonical evidence.
Hypothetical layers are checksum-addressed and explicitly labelled as scenario layers.

These are application foundations, not a claim that operational scenario content or a
replay library is bundled.

### Historical loss context (task 125)

The reviewed CSV adapter accepts normalized local DesInventar or DELTA exports with an
explicit source URL, dataset version, reviewable license, and data timestamps. Unknown
hazards or malformed rows fail closed. The context service excludes future/current
records and states that historical losses are not evidence of current impact.

### Case notebooks (task 126)

Case notebooks and entries are durable local operator state. Entries may pin source
snapshots and analytical-run IDs or record questions and conclusions. They always
retain `evidence=false` and `alters_canonical_state=false`. The notebook endpoints are:

- `POST /api/v1/operator-workspace/notebooks`;
- `POST /api/v1/operator-workspace/notebooks/{id}/entries`; and
- `GET /api/v1/operator-workspace/notebooks/{id}/entries`.

The local JSON store migrates the prior v1 document on its next atomic write.

### Accessible and localized representations (tasks 129–130)

The incident rail includes an operator-expandable text table and a dedicated print
layout. Hazard, activity, severity, authority, and provider tier are written in text;
selection and boundaries retain non-color cues, including forced-color mode.

Versioned English and Vietnamese terminology packs cover the maintained hazard names
and the CAP tsunami-warning name. Packs require human-review metadata. Authority names
are passed through unchanged rather than translated destructively.

## Deliberately deferred capability gates

Tasks 111–119, 127, and 128 remain unavailable. Their exact evidence gates are
machine-checked in `p4-capability-gates.v1.json` and include concrete deployment needs,
auth/audit or privacy foundations, named interchange standards, and new ADRs where the
product domain would expand.

This is an implementation outcome: the repository now fails closed instead of leaving
those high-risk boundaries implicit. It is not a claim that the gated feature itself
has been delivered.

## Validation

```powershell
uv run --directory apps/api pytest -q tests/unit/test_p4_long_term_capabilities.py
uv run --directory apps/api pytest -q tests/integration/test_p4_adapters.py tests/integration/test_p3_field_report_routes.py
cd apps/web
npm test -- --run tests/ActiveIncidentsPanel.test.tsx
```
