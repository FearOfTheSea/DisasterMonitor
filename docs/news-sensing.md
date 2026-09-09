# Major-news disaster sensing

The news-sensing lane reduces discovery latency without treating journalism as an
authoritative physical-event source. It stores publication metadata as immutable
observations, creates deterministic provisional candidates only for supported hazards
and a versioned major-publisher allowlist, and publishes those candidates through the
same durable incident projection used by Active Incidents and worldwide assistant
answers.

## Runtime

The scheduler enqueues configured news feeds every 15 minutes. GDELT discovery is
enabled by default. AP and Reuters are supported through a licensed gateway contract
that returns normalized `items` with `id`, `publisher`, `title`, `url`,
`published_at`, and optional `updated_at` fields. Configure gateways with:

- `AP_NEWS_ENDPOINT` and `AP_NEWS_TOKEN`
- `REUTERS_NEWS_ENDPOINT` and `REUTERS_NEWS_TOKEN`

Set `NEWS_SENSING_ENABLED=false` to disable the lane or
`GDELT_NEWS_ENABLED=false` to disable GDELT discovery. Provider credentials remain
server-side.

The worker records all received news metadata. Promotion to a provisional candidate
requires exactly one recognized hazard, major-impact language, and a publisher in
`MAJOR_NEWS_PUBLISHERS_V1`. This is a conservative eligibility rule, not a severity
assessment. Unrecognized publications remain observations and do not enter the
incident projection.

## Persistence and status

Migration `0009_news_candidates.sql` creates append-only `news_observation` and
`incident_candidate_revision` tables. Candidate revisions retain source attribution
and these clocks:

- `news_break_at`
- `first_observed_at`
- `candidate_created_at`
- `verified_at`
- `monitor_visible_at`
- `assistant_ready_at`

News-only candidates use `provisional_news_detected`. When a compatible provider
incident has the same hazard, overlaps the normalized place identity, and occurs
within 72 hours, the projection retains the news clocks and reports `source_backed`.
Rejected candidates never enter the projection.

The browser labels provisional incidents and states that authoritative confirmation
is pending. Worldwide assistant answers read this same projection and use equivalent
language. A news report with no source coordinates can appear in the incident list but
cannot produce a map marker; the system does not fabricate a point.

## Claim boundary

The implementation creates the mechanism needed to measure a 12-hour objective. It
does not prove 12-hour global recall. Promotion still requires an independently
timestamped live-news denominator, licensed-feed deployment, and a sustained
evaluation across hazards, regions, languages, outages, duplicates, and corrections.
