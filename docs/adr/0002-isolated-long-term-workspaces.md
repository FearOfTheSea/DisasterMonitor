# ADR 0002: Isolate speculative and retrospective workspaces

## Status

Accepted — 2026-09-22.

## Context

The P4 backlog includes useful research, simulation, and discovery tools alongside
capabilities that would expand DisasterMonitor into identity management, response
coordination, public submissions, or privacy-critical personal records. Implementing
the latter without a real deployment would create security and product-domain
obligations that the local-first evidence workstation does not currently own.

## Decision

DisasterMonitor may implement bounded P4 tools when their state is structurally
separate from canonical evidence:

- public social/RSS items remain untrusted discovery signals;
- local signal classification retains operator-label lineage and cannot change
  source authority;
- imagery micro-review can summarize independent labels only as analytical
  confidence;
- hypothetical planning and historical replay use simulated workspaces that reject
  canonical-evidence writes;
- historical loss records are retrospective preparedness context;
- case notebooks are non-evidence operator state;
- terminology packs are source-controlled and human-reviewed; and
- alternate incident representations express hazard, activity, severity, authority,
  and source tier in text and print.

Deployment-dependent P4 capabilities fail closed under the versioned gates in
`docs/p4-capability-gates.v1.json`. A user request does not manufacture the deployment
evidence, privacy basis, threat model, or interoperability contract named by those
gates.

## Consequences

The application can support investigation and preparedness without allowing
simulation, crowd volume, model classification, retrospective statistics, or analyst
conclusions to become current disaster truth. Authentication, collaboration, work
orders, resource coordination, volunteer/person records, public submissions, a plugin
SDK, and peer synchronization remain unsupported until their individual gates pass.
