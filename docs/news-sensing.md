# Major-news disaster sensing

The news-sensing lane reduces discovery latency without treating journalism as an
authoritative physical-event source. It stores publication metadata as immutable
observations, creates deterministic provisional candidates only for supported hazards
and a versioned major-publisher allowlist, and publishes those candidates through the
same durable incident projection used by Active Incidents and worldwide assistant
answers.

## Runtime

The scheduler enqueues configured news feeds every 15 minutes. GDELT discovery is
enabled by default. Set `NEWS_SENSING_ENABLED=false` to disable the lane or
`GDELT_NEWS_ENABLED=false` to disable GDELT discovery. There are no licensed news
gateway endpoints or credentials in this design.

One direct publisher feed is admitted by default: NASA Earth Observatory Natural
Events, fetched from `science.nasa.gov` every 15 minutes with one request per run, a
1 MB body limit, conditional requests, strict redirect/host/path enforcement, and an
automatic review expiry on 2027-03-15. The 2026-09-15 rights review found NASA content
generally available for factual informational use with source acknowledgement; NASA
logos are not imported and third-party-marked content is not republished. The source
can be disabled immediately through the registry kill switch or by setting
`APPROVED_WEB_SOURCE_REGISTRY_PATH` to an empty approved registry.

GDELT remains enabled as the broad discovery index. Direct-feed and GDELT observations
are compared by publication-to-first-observation latency with a minimum of 30 samples
per path. Insufficient samples explicitly retain the existing defaults; admitting the
NASA feed does not claim that it is globally representative or replace GDELT.

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
timestamped live-news denominator, approved public-web source coverage, and a
sustained evaluation across hazards, regions, languages, outages, duplicates, and
corrections.
