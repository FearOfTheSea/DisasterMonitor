# Capability and promotion status

This page is the release-evidence authority for Disaster Monitor. It separates code
availability from evaluation strength. The status was audited on 2026-08-13 against
the implementation, frozen fixtures, executable gates, and ignored local evidence
locations. No ignored `data/` tree, licensed multimodal corpus, operator-study result,
SME ranking set, expert decision review, or operational learning-trajectory bundle was
present.

The vocabulary is exact:

- **Implemented capability** means a bounded path exists in production code with its
  stated authority and fallback.
- **Automated/synthetic gate passing** means the current deterministic repository
  fixtures and fault injections pass. It is not evidence of external validity or human
  utility.
- **Normative promotion gate passed** means the evidence required by the declared
  release protocol exists and passed. It never expands the capability's authority.
- **Normative promotion pending** means required evidence is absent or incomplete.
  The documented fallback remains active; repository-only fixtures cannot substitute.
- **Intentionally unsupported** means no production path is claimed or exposed.

## Family status

| Family                      | Implemented capability                                                                                                                                                                                       | Automated/synthetic gate                                                                                                                              | Normative promotion                                                                                                                                                                                                                                                        |
| --------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Source Intelligence (SI)    | Versioned trusted-source catalog and provider registry; registry-bound network authority; failure-isolated acquisition; candidate-only source screening with mandatory human trust promotion.                | **Passing:** SI-A/SI-B/SI-C coverage, selection, source-policy mutation, acquisition-fault, missing/revision, and adversarial candidate-store tests.  | **Passed for the bounded SI-A/SI-B/SI-C runtime.** This does not approve any candidate source. Every candidate trust/authority promotion remains a separate human decision.                                                                                                |
| Evidence / World-State (EW) | Deterministic physical-event identity; immutable temporal claim history; conflicts, omissions, freshness, and explicit inferred hypotheses outside verified facts.                                           | **Passing:** EW-A/EW-B/EW-C identity, temporal, calibration, Brier, mutation, and inferred/observed separation tests.                                 | **Pending.** Files labeled historical do not carry a locked external source manifest, source checksums, independent adjudication, or verifiable hidden outcomes.                                                                                                           |
| Multimodal awareness (MM)   | Bounded operator-supplied image admission; metadata-only event association; local visual analysis; provenance-bearing analytical COP overlays.                                                               | **Passing:** fast safety, association, metric-integrity, provenance, browser, and operator-harness tests.                                             | **Pending.** MM-A/MM-B lack licensed held-out assets and a locked selection; MM-C lacks legitimate paired expert/operator results.                                                                                                                                         |
| Triage (TR)                 | Typed information-need routing; clause-aware incident priority; ambiguity escalation; reversible internal low/moderate actions and human review/escalation otherwise.                                        | **Passing:** TR-A/TR-B/TR-C multilingual, ranking, adversarial negation, monotonicity, authority, rollback, and pass^8 tests.                         | **Pending.** TR-B lacks a provenance-locked historical episode set with blinded SME priority labels, expertise attestations, agreement/adjudication, and subgroup scope needed for the declared recall, false-dismissal, NDCG, and parity claims.                          |
| Decision Support (DS)       | Advisory facts/observations/estimates/options; source epistemic status preserved end to end; paired scenarios; confirmed-premise recommendation eligibility; reversible internal-only autonomy.              | **Passing:** DS-A/DS-B/DS-C lineage, epistemic truth table, calibration, constraints, mutation, rollback, and pass^8 tests.                           | **Pending.** DS-A/DS-B lack blind expert review on provenance-locked historical packets and independently held outcomes/policy adjudications. Repository-authored labels cannot establish expert acceptance or real-world calibration.                                     |
| Coordination (CO)           | Typed least-privilege handoffs; deterministic specialists; bounded merge; explicit sufficiency/termination; default-plan fallback on any unsafe or incomplete state.                                         | **Passing:** CO-A/CO-B/CO-C schema, provenance, privilege, end-state, deadlock, outage, policy-attack, budget, and pass^8 tests.                      | **Passed for bounded deterministic analytical coordination.** The declared CO protocol is an adversarial simulation gate and requires no human study. This status does not satisfy or bypass pending MM, TR, or DS evidence.                                               |
| Continuous Learning (CL)    | Offline parameter selection; typed drift detection and safe mode; allowlisted reversible optimization; production-derived continuous supervisor signals; checksum-bound V3 analytical release with rollback. | **Passing:** CL-A/CL-B/CL-C partition, drift, production-effect, reachability, multi-family, regression, protected-scope, safety, and rollback tests. | **Pending for real-trajectory/operational promotion.** The active V3 release is an automated non-authority fixture release; CL-A inputs contain no locked historical task provenance or genuine reviewer corrections. It is not evidence of learning from real operations. |
| Operational evidence (OP)   | Immutable source snapshots, snapshot-linked observations, PostgreSQL/PostGIS history, idempotent scheduler/workers, freshness/status, retention tombstones, attributed bounded review, and backup/restore tooling. | **Passing locally:** lineage, duplicate delivery, retry/dead-letter, freshness, retention, HTTP, UI, migration, replay-integrity, and Compose checks. | **Pending.** No owner-approved rights/retention package, trusted deployed identity boundary, successful recovery drill, long-running failure evidence, or 30-day supervised pilot exists. |

Run the family gates from the repository root:

```powershell
uv run --directory apps/api pytest -q tests/evaluation/test_source_intelligence.py
uv run --directory apps/api pytest -q tests/evaluation/test_evidence_world_state.py
uv run --directory apps/api pytest -q tests/evaluation/test_multimodal.py tests/evaluation/test_operator_study.py
uv run --directory apps/api pytest -q tests/evaluation/test_triage.py
uv run --directory apps/api pytest -q tests/evaluation/test_decision_support.py
uv run --directory apps/api pytest -q tests/evaluation/test_coordination.py
uv run --directory apps/api pytest -q tests/evaluation/test_continuous_learning.py
```

## Supplying pending normative evidence

EW promotion requires a deidentified, immutable manifest for the historical event and
claim episodes: source record IDs, origin, license/use basis, content checksums,
adjudicator identities or study-local codes, adjudication method, and hidden outcomes.
The DisasterAgentBench validator and replay boundary can load that locked bundle without
putting hidden labels in runtime episode objects. EW remains pending until legitimate
external episodes and outcomes are supplied and the frozen evaluator is run.

TR promotion requires a locked historical episode manifest plus blinded SME rankings.
The bundle must record study-local reviewer codes, qualifying expertise, independent
labels, agreement, adjudication, critical-event outcomes, and the hazard/geography
subgroups used for scope parity. Integrate it through a schema-validated ignored-data
loader, then rerun `test_triage.py`. Synthetic severity permutations remain useful
regressions but cannot supply the SME evidence.

DS promotion requires provenance-locked historical incident packets, blind expert
option/scenario ratings, qualifying expertise, independent policy-constraint
adjudication, and genuinely held outcomes for calibration. Integrate an ignored-data
loader that preserves packet and result checksums, then rerun
`test_decision_support.py`. LLM judges, simulated experts, and retrospective labels
created to match current output do not qualify.

CL operational promotion requires deidentified historical task trajectories and genuine
reviewer corrections with non-overlapping locked train/dev/test identities, provenance
checksums, and retained adverse outcomes. Extend the validated trajectory loader to
consume that ignored bundle and rerun `test_continuous_learning.py`. Until then, the V3
parameter remains limited to analytical follow-up ordering and cannot change facts,
trust, permissions, thresholds, sufficiency, termination, or action authority.

MM uses the existing fail-closed preparation and scoring tools. Stage only licensed
assets under ignored `data/multimodal/`, complete and lock the selection file, then run:

```powershell
uv run --directory apps/api python scripts/prepare_multimodal_benchmarks.py `
  --staged-root ../../data/multimodal `
  --selection-file ../../data/multimodal/selection.json
uv run --directory apps/api python scripts/run_multimodal_release.py `
  --staged-root ../../data/multimodal `
  --model qwen3-vl:2b `
  --output ../../data/multimodal/release-result.json
```

For MM-C, collect at least six legitimate participants under the frozen paired,
counterbalanced protocol and store only study-local records under ignored
`data/operator-study/`, then run:

```powershell
uv run --directory apps/api python scripts/run_mm_operator_study.py `
  --results ../../data/operator-study/results.json `
  --output ../../data/operator-study/score.json
```

Both MM commands fail closed when required assets, checksums, licenses, model results,
or human attestations are absent.

## Intentionally unsupported

Automatic imagery retrieval or raster monitoring; live weather; geocoding; arbitrary
map publication; official warning map overlays; OCR; online source crawling or automatic
source trust promotion; hosted models; production authentication/RBAC and TLS;
multi-user conversation persistence; cloud deployment; and public warnings, evacuation
directives, or resource-allocation orders remain intentionally unsupported. The
implemented FIRMS/GFM paths are typed observations/products, not automatic imagery or
official incident declarations.
