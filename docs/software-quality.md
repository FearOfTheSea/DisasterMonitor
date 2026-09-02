# Software quality policy

DisasterMonitor optimizes for software that remains safe and economical to change.
Correctness, safety, provenance, and security constraints are non-negotiable.
Among otherwise valid solutions, maintainability and architectural integrity take
priority over development speed, minimal diffs, and implementation convenience.

This policy applies to production code, tests, scripts, schemas, configuration, and
documentation.

## Decision order

Evaluate implementation choices in this order:

1. Preserve correctness, safety, security, provenance, and bounded claims.
2. Preserve Clean Architecture and dependency direction.
3. Maximize maintainability, clarity, cohesion, and testability.
4. Protect reliability, operability, accessibility, and measured performance.
5. Minimize delivery time and implementation effort among the solutions that satisfy
   the preceding qualities.

The fastest solution is not acceptable when it hides ownership, couples unrelated
behavior, duplicates policy, bypasses a boundary, or makes future changes riskier.
Likewise, quality does not justify speculative frameworks or abstractions without a
current responsibility. Choose the simplest design that expresses the real boundaries.

## Clean Code and maintainability standard

A maintainable change makes these questions easy to answer:

- Where does this behavior belong?
- Which rule or dependency can cause it to change?
- Can it be tested without unrelated infrastructure?
- Can another contributor change it without reading an entire subsystem?
- Will an invalid dependency or contract change fail clearly?

Prefer:

- names that express domain intent;
- focused functions, classes, and modules with one reason to change;
- explicit inputs, outputs, dependencies, and failure states;
- immutable values and deterministic transformations where practical;
- narrow interfaces owned by their consumers;
- one authoritative implementation of each policy;
- early validation at boundaries and valid states inside the system;
- straightforward control flow over clever compression;
- automated enforcement for architectural and contract rules.

Avoid:

- catch-all modules, utility dumping grounds, and oversized coordinators;
- boolean flags or mode switches that combine separate use cases;
- hidden global state, temporal coupling, and action-at-a-distance side effects;
- duplicated validation, mapping, or business rules across layers;
- abstractions named after implementation mechanics instead of responsibilities;
- comments that compensate for unclear code;
- compatibility layers that quietly become permanent implementation homes;
- tests coupled to private call sequences or incidental structure.

## Clean Architecture standard

Backend dependencies point inward:

```text
presentation --> application --> domain

infrastructure adapters --> application ports --> domain
```

- Domain owns business concepts, invariants, and deterministic domain policy. It does
  not import frameworks, transports, persistence, providers, or other outward layers.
- Application owns use cases and declares the ports they require. It coordinates
  domain behavior without depending on concrete adapters.
- Infrastructure implements application ports and isolates databases, model runtimes,
  external providers, filesystems, and framework integrations.
- Presentation owns transport parsing and serialization. It delegates decisions to
  application use cases rather than reimplementing them.
- Composition roots construct the runtime object graph. Their special import privileges
  do not permit business logic or a second orchestration layer.

Frontend features own their user behavior and communicate through typed boundaries.
React components do not call external disaster providers, embed backend policy, or
become unbounded mixtures of transport, state orchestration, rendering, and geometry.

Cross-layer convenience imports are architectural defects. Fix the ownership or define
a focused port instead of weakening an architecture test.

## Size and cohesion

LOC identifies review candidates; it does not measure design quality by itself.

- Review every hand-maintained source file above 500 LOC for mixed responsibilities.
- Split files above 700 LOC unless a documented exception demonstrates one cohesive
  external contract or sequential protocol with a single reason to change.
- Keep stable compatibility facades limited to re-exports and composition.
- Extract a unit only when it has a meaningful name, ownership boundary, dependency
  seam, reusable policy, or independently testable behavior.
- Do not create trivial one-function files merely to satisfy a line target.

Generated code is exempt from hand-maintained LOC thresholds when its source of truth
and freshness check are explicit.

## Quality attributes

Maintainability guides design, but it is not the only quality attribute:

- **Correctness and safety:** invalid states fail closed; claims retain evidence and
  provenance.
- **Testability:** deterministic rules are isolated from I/O and tested at stable
  boundaries.
- **Reliability:** external failures are bounded, explicit, and do not become false
  success or absence claims.
- **Operability:** logs, metrics, health, readiness, and errors identify actionable
  boundaries without exposing secrets.
- **Security and privacy:** credentials remain server-side, inputs are validated, and
  authority is least-privileged.
- **Performance:** optimize measured bottlenecks while preserving readable ownership;
  record non-obvious performance constraints in tests or rationale comments.
- **Accessibility and usability:** user-facing workflows remain understandable,
  keyboard-operable where appropriate, and honest about coverage and failure.

Tradeoffs must name the affected attributes. “Faster to implement” or “more convenient”
is insufficient justification for lowering an attribute without an explicit constraint.

## Change workflow

Before changing code:

1. Identify the owning layer, current tests, public contracts, and likely reasons to
   change.
2. Decide whether the current structure can absorb the behavior without losing
   cohesion.
3. Define expected behavior and relevant failure cases at the narrowest stable test
   layer.

During implementation:

1. Keep dependencies explicit and inward-pointing.
2. Remove duplication introduced or exposed by the change.
3. Refactor when the existing structure prevents a clear implementation; do not stack
   another special case onto a known design problem for speed.
4. Keep refactoring behavior-preserving and validate it proportionally.

Before completion:

1. Confirm the code reads in terms of responsibilities and domain intent.
2. Confirm architecture, contract, static-analysis, and relevant behavioral checks.
3. Update documentation where ownership, contracts, or operational behavior changed.
4. Record any necessary exception with its scope, consequence, and removal condition.

## Review questions

- Does each changed unit have one clear responsibility and reason to change?
- Are business rules located in domain or application rather than adapters or UI?
- Do dependencies point inward, with concrete details behind application-owned ports?
- Is policy implemented once and reused through a stable boundary?
- Can important behavior and failures be tested deterministically?
- Are names and control flow understandable without explanatory narration?
- Did the change reduce or at least avoid increasing coupling and cognitive load?
- Is any quality tradeoff supported by evidence rather than convenience?
- Would a future contributor know where to make the next related change?

## Exceptions and technical debt

Occasionally an external constraint prevents the preferred design. Document the exact
constraint, affected quality attributes, bounded scope, risk mitigation, owner or
removal condition, and test coverage. An exception must not silently redefine the
architecture or become a template for new code.

Known debt discovered inside the requested scope should be resolved with the change.
Debt outside scope should be recorded precisely enough to act on; vague “cleanup later”
notes are not an acceptable substitute for a maintainable boundary.
