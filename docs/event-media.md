# Event-associated source media

Disaster Monitor can add a small contextual photo gallery after deterministic
workflow selects a physical event.

The current target is three photos. Each item shows its source, caption,
publication or capture date, credit, content role, rights status, and
event-association status.

The design is disaster-neutral. The same service accepts a typed `Disaster` and
has terms and display roles for every recognized disaster.

Executable event-provider coverage still determines which requests can reach the
service.

This feature is presentation media, not disaster evidence.
A photo cannot select an event, create or change a reported fact, or enter canonical
Evidence World-State.
It cannot justify an operational recommendation or gain authority through model
judgment.

## Retrieval and source hierarchy

`EventMediaDiscovery` is an application port. Add providers without changing report
orchestration.

Providers return metadata candidates. Shared application policy performs event
association. The service downloads only accepted candidates.

The current no-key adapter uses a news index for discovery, then reads the original
publisher page. It does not trust result thumbnails or publisher names from the index.

The versioned registry at
`apps/api/src/disaster_monitor/infrastructure/media/resources/event_media_sources.v1.json`
assigns stable source IDs, priorities, exact HTTPS page hosts, and exact image-asset
hosts.

Humanitarian publishers have priority. Maintained news publishers follow them.

Discard search results from pages outside the registry. Check redirects again at every
hop. Do not allow an article to send the retriever to an unregistered image host.

This is a presentation-source registry. It does not add providers to the trusted
disaster-evidence catalog.

Candidate collection and image retrieval use bounded backfill.

The news adapter scans source pages in waves. It continues past timeouts and pages
without a safe image, up to three times the configured candidate limit.

The application retrieves association-approved candidates in ranked batches. It stops
when the gallery is full or the candidate pool is exhausted.

Later candidates can replace broken, undersized, duplicate, or otherwise unusable
images. They cannot bypass an admission rule.

Idempotent media requests receive one retry for transient transport, timeout,
rate-limit, and server failures. Permanent and safety failures are not retried.

The architecture supports a future provider hierarchy: official emergency-agency
galleries, humanitarian organizations, licensed open-media APIs, and maintained
source-page extraction.

Every provider must emit the same metadata and pass the same association and
network-authority gates. Provider position cannot bypass association checks.

## Event-association gates

The application derives `MediaEventContext` only from the selected event. It checks:

- article publication from one day before through 30 days after the event, with no
  future publication beyond current clock tolerance;
- the same bounds for capture time when the source provides it;
- the selected disaster in the article title or selected image caption;
- the selected country, or event-location terms for worldwide or offshore results,
  in the same primary metadata;
- any explicit year against the selected event year;
- an exact provider event identifier when one appears;
- a registered source page and image host, bounded response sizes, JPEG/PNG headers,
  minimum dimensions, and duplicate content checksums.

Reject a candidate when any gate fails. A plausibly captioned photo from an older,
unrelated disaster fails the date or explicit-year gate.

Page boilerplate and surrounding search text cannot repair a mismatch in the article
title and selected image caption.

Report an exact event identifier as `exact_event_link`. Report matching date, disaster,
and geography as `corroborated`, not verified.

Do not use pixels to establish event identity. Metadata can still be wrong.

Label every item as contextual source media and expose association detail.

The gallery fails soft. No accepted photo leaves the source-backed text report intact
and adds no factual claim.

If discovery runs but accepts no photo, return an empty gallery with bounded provider,
rejection-count, and warning diagnostics. Never present rejected candidates as gallery
items.

## Rights, storage, and configuration

The current adapter reports `source_preview`. It keeps the publisher, agency, and
photographer credit found on the source page and links to that page.

It does not invent a license or claim reuse rights. Review source-controlled previews
before production redistribution.

Serve retrieved bytes through a same-origin API route from a bounded,
content-addressed filesystem store.

Never evict admitted assets to make room for new assets. Conversation-retained gallery
references remain usable across API restarts while the local data volume remains.

When the byte ceiling is reached, fail new media admission softly. Keep the
source-backed text report available.

The store does not yet implement automated garbage collection after conversation
deletion.

Compose mounts `EVENT_MEDIA_BLOB_ROOT` on its own named volume. Container replacement
does not invalidate persisted gallery references.

The defaults require no new `.env` values:

```text
EVENT_MEDIA_ENABLED=true
EVENT_MEDIA_TARGET_COUNT=3
EVENT_MEDIA_CANDIDATE_LIMIT=12
EVENT_MEDIA_MAX_IMAGE_BYTES=3000000
EVENT_MEDIA_STORE_MAXIMUM_BYTES=24000000
EVENT_MEDIA_BLOB_ROOT=data/event-media/blobs
```

`EVENT_MEDIA_CANDIDATE_LIMIT` bounds candidates returned by the news adapter.

To fill that pool when publisher-page extraction fails, the adapter can inspect at
most three times that number of unique registered pages.

Set `EVENT_MEDIA_ENABLED=false` to disable discovery. Provider timeouts and source-page
limits reuse `DISASTER_PROVIDER_TIMEOUT_SECONDS` and
`DISASTER_PROVIDER_MAX_RESPONSE_BYTES`.

Media failures never route the request to Qwen. They never make a recognized disaster
report unavailable.
