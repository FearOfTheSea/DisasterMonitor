# Controlled public-web news collection rollout

## Decision

Replace the licensed AP/Reuters gateway proposal with a controlled, allowlisted
public-web collection capability. This is not a general crawler. Every source and
path must pass an explicit admission review before any request is made.

The collector exists only to obtain disaster-discovery metadata: publisher, headline,
canonical URL, publication/update time, and a stable external identifier. It must not
persist article bodies or use scraped text as authoritative confirmation.

## Non-negotiable source admission

Maintain a versioned source registry. Each entry must include:

- approved scheme, hosts, ports, paths, and redirect hosts;
- acquisition mode in preference order: RSS/Atom, XML sitemap, structured JSON-LD,
  then explicitly approved listing HTML;
- the reviewed robots policy, applicable terms, review date, reviewer, and next review;
- a descriptive contact-bearing user agent and source-specific crawl delay;
- request, concurrency, response-size, and daily bandwidth budgets;
- parser version, supported languages, timestamp semantics, and attribution rules;
- operational owner, enabled state, kill-switch reason, and expiry date.

An entry is rejected when access requires authentication, payment, CAPTCHA solving,
browser-fingerprint evasion, proxy rotation, or bypassing a technical restriction.
The system must not assume that a publicly reachable page is permitted to be crawled.
AP, Reuters, and every other publisher require the same source-by-source review; none
is pre-approved by this plan.

## Proposed architecture

Keep `BreakingNewsFeed` as the application port. Add infrastructure behind it in four
cohesive components:

1. `ApprovedWebSourceRegistry` loads and validates the signed, versioned admission
   records. Disabled, expired, or review-overdue sources cannot be scheduled.
2. `BoundedWebFetcher` performs conditional GET requests with `ETag` and
   `Last-Modified`, a fixed user agent, per-source token buckets, bounded redirects,
   timeouts, maximum response sizes, and content-type checks.
3. One deterministic parser per approved source transforms only admitted metadata
   into `NewsFeedItem`. Parsers never execute page JavaScript or send page content to
   the language model.
4. `WebCollectionScheduler` creates idempotent jobs through the existing durable job
   queue. The current `NewsCandidateIngestion` remains responsible for observation
   storage, classification, clustering, and candidate promotion.

The fetcher must resolve DNS before each connection, reject private/link-local/loopback
destinations, validate every redirect against the registry, and prevent alternate-port
and encoded-host SSRF. Retrieved markup is untrusted data, never instructions.

## Storage and copyright boundary

Persist only the normalized metadata already accepted by `NewsObservation`, plus the
HTTP status, response hash, parser version, retrieval time, and non-sensitive failure
code needed for audit. Do not retain article bodies, images, subscriber-only content,
cookies, or session tokens. If short-lived HTML quarantine is later required for parser
diagnostics, it needs a separate approved retention policy and must not be enabled by
default.

Canonical URLs and headlines retain publisher attribution. Removal, correction, and
updated timestamps create new immutable observations; they never silently rewrite
prior evidence.

## Failure controls and observability

- Honor `Retry-After`; use exponential backoff with jitter for 429 and 5xx responses.
- Open a per-source circuit after repeated failures. Do not shift traffic to another
  hostname or evade the restriction.
- Stop a parser when required fields disappear, item volume changes sharply, duplicate
  rates spike, or timestamps move outside configured bounds.
- Provide global and per-source kill switches that take effect before the next fetch.
- Record fetch latency, status classes, bytes, new-item count, publication-to-observed
  delay, parse failures, robots/terms review age, and circuit state.
- Alert on missed schedules, p95 observation delay, parser drift, sustained rate limits,
  and any attempted URL outside the allowlist.

Publication time must come from deterministic structured metadata with an explicit
timezone. If it is absent or ambiguous, retain `first_observed_at` but do not invent
`news_break_at` or include the item in publication-to-detection SLA calculations.

## Rollout sequence

### 0. Governance and threat model

- Approve the registry schema, source-review checklist, user-agent identity, retention
  boundary, incident response, and kill-switch ownership.
- Add tests for SSRF, redirects, decompression bombs, malformed encodings, oversized
  responses, hostile markup, and instruction-like page content.
- Exit when security and source-admission reviewers sign off on the mechanism. No live
  publisher requests occur in this phase.

### 1. Fetching framework

- Implement the registry, bounded fetcher, robots/terms revalidation hook, conditional
  requests, budgets, circuits, metrics, and audit records.
- Use a local fixture server only. Prove that an unregistered URL cannot be fetched.
- Exit when unit, integration, architecture, and failure-injection tests pass.

### 2. Two-source pilot

- Admit two public sources only after documented review. Prefer feeds or sitemaps over
  HTML and choose different regions or languages.
- Run in observation-only mode; do not create incident candidates.
- Compare collected timestamps and recall against an independent, timestamped event
  denominator for at least two weeks.
- Exit when there are no policy violations, parser drift is detectable, and collection
  delay plus recall meet the agreed pilot thresholds.

### 3. Shadow candidate evaluation

- Feed normalized observations through the existing classifier and clustering logic,
  but keep candidates invisible to operators and the assistant.
- Review false positives, missed events, corrections, duplicate clusters, and location
  extraction across every supported hazard.
- Exit only with an approved precision/recall report and documented failure examples.

### 4. Guarded production

- Enable provisional candidates for one source at a time behind a runtime feature flag.
- Preserve the existing provisional label and authoritative-confirmation boundary.
- Roll back automatically on parser drift, stale review status, abnormal volume, or
  source-policy failure.
- Expand coverage only after each source completes its own observation and shadow gates.

### 5. Twelve-hour objective assessment

- Measure `monitor_visible_at - news_break_at` and
  `assistant_ready_at - news_break_at` against the independent denominator.
- Report p50, p95, maximum, recall within 12 hours, and coverage by source, hazard,
  language, and region. Exclude ambiguous publication times explicitly.
- Claim the objective only after a sustained evaluation window and published coverage
  boundaries. Scheduler cadence alone is not evidence of the SLA.

## Initial implementation slices

1. Registry domain model and validation tests.
2. Fetch policy and SSRF-safe HTTP adapter with deterministic fixtures.
3. Conditional-fetch state and durable audit records.
4. Feed/sitemap parser contract and one fixture-only adapter.
5. Scheduler, circuits, metrics, and operator kill switches.
6. Governance-approved live pilot followed by shadow evaluation.

No source-specific scraper should be implemented before slices 1–5 and the source's
admission record are complete.

## Foundation implementation status

The core of slices 1–4 and the scheduler/circuit portion of slice 5 are implemented
for RSS/Atom and Google News sitemap metadata, using fixture-only validation:

- `ApprovedWebSource` enforces HTTPS, exact hosts, allowed paths, standard port,
  review expiry, contact-bearing user agents, request/size budgets, and kill switches.
- `BoundedWebFetcher` revalidates DNS destinations, rejects non-public addresses,
  bounds redirects and bytes, restricts content types, honors conditional request
  validators, and fails closed on rate limits and upstream errors.
- deterministic parsers reject DTD/entity input and retain only headline metadata;
- consecutive failures open a source-specific circuit for 30 minutes;
- PostgreSQL persists mutable conditional-fetch state and append-only fetch audits;
- the existing 15-minute scheduler and news-candidate worker accept approved web feeds
  through the existing `BreakingNewsFeed` port.

Before a live pilot, the remaining controls are automated robots/terms revalidation,
daily bandwidth and concurrency accounting, `Retry-After`/backoff scheduling, parser
drift and latency metrics, and an observation-only route that cannot promote candidates.
These are promotion gates, not deferred production cleanup.

There are no packaged or enabled publisher records. To make an approved registry
available to the scheduler and worker, set `APPROVED_WEB_SOURCE_REGISTRY_PATH` to an
operator-managed JSON file following
`docs/examples/approved-web-sources.example.json`. Editing the example alone has no
runtime effect. A worker restart is required after registry membership or kill-switch
changes.

The two-source live pilot, shadow evaluation, and guarded production stages remain
blocked on those controls and source-by-source governance approval. DNS is checked
immediately before each request, but the initial implementation does not pin the
approved address through the TLS connection; live promotion requires a network-level
egress allowlist or a transport with DNS pinning to close that rebinding gap.
