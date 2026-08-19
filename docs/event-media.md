# Event-associated source media

Disaster Monitor can add a small contextual photo gallery after its deterministic
workflow has selected a physical event. The current target is three photos. Each item
shows its source, caption, publication or capture date, credit, content role, rights
status, and event-association status. The design is disaster-neutral: the same service
accepts a typed `Disaster` and contains terms and display roles for every recognized
disaster, although executable event-provider coverage still determines which requests
can reach it.

This feature is presentation media, not disaster evidence. A photo cannot select an
event, create or change a reported fact, enter canonical Evidence World-State, justify
an operational recommendation, or acquire authority through a model judgment.

## Retrieval and source hierarchy

`EventMediaDiscovery` is an application port, so additional providers can be added
without changing report orchestration. Providers return metadata candidates; a shared
application policy performs event association and the service downloads only accepted
candidates. The current no-key adapter uses a news index for discovery, then reads the
original publisher page. It does not trust result thumbnails or publisher names from
the index.

The versioned registry at
`apps/api/src/disaster_monitor/infrastructure/media/resources/event_media_sources.v1.json`
assigns stable source IDs, priorities, exact HTTPS page hosts, and exact image-asset
hosts. Humanitarian publishers are preferred, followed by maintained news publishers.
Search results from any page outside the registry are discarded. Redirects are checked
again at every hop, and an article cannot send the retriever to an unregistered image
host. This is a presentation-source registry; it does not add providers to the trusted
disaster-evidence catalog.

The architecture supports a future provider hierarchy such as official emergency
agency galleries, humanitarian organizations, licensed open-media APIs, and finally
maintained source-page extraction. Every provider must emit the same metadata and pass
the same association and network-authority gates. A provider's position in that
hierarchy cannot bypass association checks.

## Event-association gates

The application derives `MediaEventContext` only from the selected event. It checks:

- article publication from one day before through 30 days after the event, and no
  future publication beyond the current clock tolerance;
- the same bounds for capture time when the source provides it;
- the selected disaster in the article title or selected image caption;
- the selected country, or event-location terms for worldwide/offshore results, in
  that same primary metadata;
- any explicit year against the selected event year;
- an exact provider event identifier when one appears;
- a registered source page and image host, bounded response sizes, JPEG/PNG headers,
  minimum dimensions, and duplicate content checksums.

A candidate that fails any gate is rejected before presentation. In particular, a
plausibly captioned photo from an older unrelated disaster fails the date or explicit-
year gate. Page boilerplate and surrounding search text cannot repair a mismatch in the
article title and selected image caption. An exact event identifier is reported as
`exact_event_link`; otherwise matching date, disaster, and geography is transparently
reported as `corroborated` rather than verified.

Pixels are not used to establish event identity. Metadata can still be wrong, so the UI
labels every item as contextual source media and exposes the association detail. The
gallery fails soft: no or insufficient accepted photos leaves the source-backed text
report intact and adds no factual claim.

## Rights, storage, and configuration

The current adapter reports `source_preview`, keeps the publisher/agency/photographer
credit found on the source page, and links back to that page. It does not invent a
license or claim reuse rights. Source-controlled previews remain subject to the source's
terms and should be reviewed before production redistribution.

Retrieved bytes are served through a same-origin API route from a bounded in-process
store. They are content-checksummed, byte-limited, and evicted when the configured
store budget is exceeded. They are not persisted and disappear on API restart.

The defaults require no new `.env` values:

```text
EVENT_MEDIA_ENABLED=true
EVENT_MEDIA_TARGET_COUNT=3
EVENT_MEDIA_CANDIDATE_LIMIT=12
EVENT_MEDIA_MAX_IMAGE_BYTES=3000000
EVENT_MEDIA_STORE_MAXIMUM_BYTES=24000000
```

Set `EVENT_MEDIA_ENABLED=false` to disable discovery. Provider timeouts and source-page
limits reuse `DISASTER_PROVIDER_TIMEOUT_SECONDS` and
`DISASTER_PROVIDER_MAX_RESPONSE_BYTES`. Media failures never route the request to Qwen
and never make a recognized disaster report unavailable.
