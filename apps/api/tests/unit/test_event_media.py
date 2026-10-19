from dataclasses import replace
from datetime import UTC, datetime
from importlib import import_module
from pathlib import Path

import pytest

from disaster_monitor.application.media import (
    DisasterMediaCandidate,
    MediaAssociationStatus,
    MediaCreditKind,
    MediaEventContext,
    MediaRightsStatus,
    RetrievedMedia,
)
from disaster_monitor.application.media_analysis.event_media import (
    DisasterMediaService,
    EventMediaAssociationPolicy,
)
from disaster_monitor.domain.disaster import Disaster
from disaster_monitor.domain.evidence_types import SourceReference
from disaster_monitor.infrastructure.media.memory_store import InMemoryMediaAssetStore

NOW = datetime(2026, 8, 15, 12, tzinfo=UTC)
EVENT_TIME = datetime(2026, 8, 10, 5, 54, tzinfo=UTC)


def _context(disaster: Disaster = Disaster.EARTHQUAKE) -> MediaEventContext:
    return MediaEventContext(
        event_id="us6000tjl2",
        physical_event_id="physical-event:colombia-2026",
        disaster=disaster,
        location="5 km S of San José del Palmar, Colombia",
        event_time=EVENT_TIME,
        provider_ids=("us6000tjl2",),
        country_code="COL",
        country_terms=("Colombia", "Republic of Colombia"),
        latitude=4.95,
        longitude=-76.25,
    )


def _candidate(
    identifier: str,
    *,
    title: str = "Rescuers search rubble after the Colombia earthquake",
    caption: str = "Rescue workers in Colombia after the earthquake.",
    published_at: datetime = datetime(2026, 8, 11, 8, tzinfo=UTC),
    priority: int = 20,
) -> DisasterMediaCandidate:
    return DisasterMediaCandidate(
        candidate_id=f"candidate:{identifier}",
        provider_id="fixture-media",
        source_id=f"fixture-source:{identifier}",
        publisher=f"Publisher {identifier}",
        source_page_url=f"https://example.test/{identifier}",
        image_url=f"https://images.example.test/{identifier}.png",
        article_title=title,
        context_text=title,
        caption=caption,
        credit=f"Agency {identifier}",
        credit_kind=MediaCreditKind.AGENCY,
        published_at=published_at,
        captured_at=None,
        license_name=None,
        license_url=None,
        rights_status=MediaRightsStatus.SOURCE_PREVIEW,
        source_priority=priority,
    )


@pytest.mark.parametrize(
    ("disaster", "term"),
    (
        (Disaster.EARTHQUAKE, "earthquake"),
        (Disaster.FLOOD, "flooding"),
        (Disaster.WILDFIRE, "wildfire"),
        (Disaster.LANDSLIDE, "landslide"),
        (Disaster.DROUGHT, "drought"),
        (Disaster.TROPICAL_CYCLONE, "typhoon"),
        (Disaster.VOLCANIC_ERUPTION, "volcanic eruption"),
    ),
)
def test_association_policy_is_disaster_neutral(disaster: Disaster, term: str) -> None:
    context = _context(disaster)
    candidate = _candidate(
        disaster.value,
        title=f"Colombia {term} response",
        caption=f"Emergency teams respond to the {term} in Colombia.",
    )

    result = EventMediaAssociationPolicy().assess(candidate, context, now=NOW)

    assert result.status == MediaAssociationStatus.CORROBORATED
    assert "media.association.disaster_text" in result.rule_ids
    assert "media.association.country_text" in result.rule_ids


def test_association_rejects_an_old_unrelated_disaster_photo() -> None:
    candidate = _candidate(
        "old-nepal-photo",
        title="Colombia earthquake update",
        caption="Rescue workers after the 2015 Nepal earthquake.",
    )

    result = EventMediaAssociationPolicy().assess(candidate, _context(), now=NOW)

    assert result.status == MediaAssociationStatus.REJECTED
    assert result.rule_ids == ("media.association.explicit_year_mismatch",)


def test_collected_multi_event_article_does_not_make_every_photo_match():
    candidate = _candidate(
        "multi",
        title="Weekly earthquake and hurricane update",
        caption="Crews clear trees after Hurricane Arlen in Florida.",
    )
    source = SourceReference(
        "news",
        "Daily",
        candidate.article_title,
        candidate.source_page_url,
        NOW,
        None,
        NOW,
    )
    context = replace(
        _context(),
        collected_articles=(source,),
        multi_event_article_urls=(source.canonical_url,),
    )
    result = EventMediaAssociationPolicy().assess(candidate, context, now=NOW)
    assert result.status == MediaAssociationStatus.REJECTED
    assert "multi_event" in result.rule_ids[-1]


@pytest.mark.parametrize(
    "disaster,caption",
    [
        (Disaster.FLOOD, "Floods in Colombia left roads covered with debris."),
        (Disaster.WILDFIRE, "Wildfires in Colombia left roads covered with debris."),
        (Disaster.LANDSLIDE, "Landslides in Colombia left roads covered with debris."),
        (
            Disaster.EARTHQUAKE,
            "Earthquakes in Colombia left roads covered with debris.",
        ),
    ],
)
def test_plural_hazard_in_caption_retains_collected_event_association(
    disaster, caption
):
    candidate = _candidate("plural", title=caption, caption=caption)
    source = SourceReference(
        "news",
        "Daily",
        caption,
        candidate.source_page_url,
        candidate.published_at,
        None,
        NOW,
    )
    context = replace(
        _context(disaster),
        collected_articles=(source,),
        multi_event_article_urls=(source.canonical_url,),
    )
    assert (
        EventMediaAssociationPolicy().assess(candidate, context, now=NOW).status
        == MediaAssociationStatus.EXACT_EVENT_LINK
    )


@pytest.mark.parametrize(
    "caption",
    [
        "Stock image of a flood.",
        "Illustration of an earthquake.",
        "Archival rescue photo.",
        "File photograph of a flood.",
    ],
)
def test_stock_archive_and_illustrative_lead_images_are_excluded(caption):
    candidate = _candidate("illustrative", caption=caption)
    result = EventMediaAssociationPolicy().assess(candidate, _context(), now=NOW)
    assert result.status == MediaAssociationStatus.REJECTED


@pytest.mark.asyncio
async def test_expanded_gallery_retains_duplicate_sources_and_delivery_failures():
    candidates = tuple(_candidate(str(i)) for i in range(9))

    class Provider:
        provider_id = "fixture"

        async def discover(self, context, *, now):
            return candidates

        async def retrieve(self, candidate):
            if candidate == candidates[-1]:
                raise OSError("broken image")
            content = (
                b"same"
                if candidate in candidates[:2]
                else candidate.candidate_id.encode()
            )
            return RetrievedMedia(candidate, content, "image/png", 640, 360)

    result = await DisasterMediaService(
        (Provider(),), InMemoryMediaAssetStore(), clock=lambda: NOW
    ).discover(_context())
    assert len(result.items) == 7
    duplicate = next(
        i for i in result.items if i.source_page_url == candidates[0].source_page_url
    )
    assert {s.source_page_url for s in duplicate.source_references} == {
        c.source_page_url for c in candidates[:2]
    }
    assert any(
        s.source_page_url == candidates[-1].source_page_url
        for s in result.unavailable_sources
    )
    assert result.collection_limit >= len(result.items)


def test_linked_article_can_supply_media_without_an_invented_onset():
    candidate = _candidate("linked")
    source = SourceReference(
        "news",
        "Daily",
        candidate.article_title,
        candidate.source_page_url,
        None,
        None,
        NOW,
    )
    context = replace(_context(), collected_articles=(source,), event_time_known=False)
    result = EventMediaAssociationPolicy().assess(candidate, context, now=NOW)
    assert result.status == MediaAssociationStatus.EXACT_EVENT_LINK
    assert "media.association.collected_article" in result.rule_ids


def test_caption_date_does_not_disqualify_explicitly_linked_contextual_photo():
    candidate = _candidate(
        "dated-context",
        caption=("Rescue workers after the Colombia earthquake on August 11, 2026."),
    )
    source = SourceReference(
        "news",
        "Daily",
        candidate.article_title,
        candidate.source_page_url,
        candidate.published_at,
        None,
        NOW,
    )
    context = replace(_context(), collected_articles=(source,), event_time_known=False)
    result = EventMediaAssociationPolicy().assess(candidate, context, now=NOW)
    assert result.status == MediaAssociationStatus.EXACT_EVENT_LINK
    assert "media.association.event_time_unresolved" in result.rule_ids
    assert "unresolved" in result.detail
    assert not context.event_time_known


@pytest.mark.asyncio
async def test_gallery_selects_three_and_never_fetches_injected_old_photo() -> None:
    valid = tuple(_candidate(str(index), priority=index) for index in range(1, 4))
    old = _candidate(
        "old-injected",
        title="2015 Nepal earthquake aftermath",
        caption="An older unrelated disaster in Nepal.",
        published_at=datetime(2015, 4, 26, tzinfo=UTC),
        priority=0,
    )

    class Provider:
        provider_id = "fixture-media"

        def __init__(self) -> None:
            self.retrieved: list[str] = []

        async def discover(self, context, *, now):
            return (*valid, old)

        async def retrieve(self, candidate):
            self.retrieved.append(candidate.candidate_id)
            content = b"image-" + candidate.candidate_id.encode()
            return RetrievedMedia(candidate, content, "image/png", 640, 360)

    provider = Provider()
    service = DisasterMediaService(
        (provider,),
        InMemoryMediaAssetStore(),
        clock=lambda: NOW,
        target_count=3,
    )

    gallery = await service.discover(_context())

    assert gallery is not None
    assert len(gallery.items) == 3
    assert gallery.rejected_count == 1
    assert {item.source_id for item in gallery.items} == {
        "fixture-source:1",
        "fixture-source:2",
        "fixture-source:3",
    }
    assert "candidate:old-injected" not in provider.retrieved
    assert all(item.event_id == "us6000tjl2" for item in gallery.items)


@pytest.mark.asyncio
async def test_gallery_backfills_when_the_initial_retrieval_batch_is_rejected() -> None:
    candidates = tuple(_candidate(str(index), priority=index) for index in range(1, 10))

    class Provider:
        provider_id = "fixture-media"

        def __init__(self) -> None:
            self.retrieved: list[str] = []

        async def discover(self, context, *, now):
            return candidates

        async def retrieve(self, candidate):
            self.retrieved.append(candidate.candidate_id)
            if int(candidate.candidate_id.rsplit(":", 1)[-1]) <= 6:
                raise ValueError("The source returned an unusable image.")
            content = b"image-" + candidate.candidate_id.encode()
            return RetrievedMedia(candidate, content, "image/png", 640, 360)

    provider = Provider()
    gallery = await DisasterMediaService(
        (provider,),
        InMemoryMediaAssetStore(),
        clock=lambda: NOW,
        target_count=3,
    ).discover(_context())

    assert gallery is not None
    assert [item.source_id for item in gallery.items] == [
        "fixture-source:7",
        "fixture-source:8",
        "fixture-source:9",
    ]
    assert gallery.rejected_count == 6
    assert provider.retrieved == [
        *(f"candidate:{index}" for index in range(1, 7)),
        *(f"candidate:{index}" for index in range(7, 10)),
    ]
    assert gallery.warnings == ()


@pytest.mark.asyncio
async def test_zero_accepted_images_return_bounded_diagnostics() -> None:
    rejected = _candidate(
        "unrelated",
        title="Unrelated weather update",
        caption="A routine weather scene in Colombia.",
    )

    class Provider:
        provider_id = "fixture-media"

        async def discover(self, context, *, now):
            return (rejected,)

        async def retrieve(self, candidate):
            raise AssertionError("Rejected media must never be retrieved.")

    gallery = await DisasterMediaService(
        (Provider(),),
        InMemoryMediaAssetStore(),
        clock=lambda: NOW,
    ).discover(_context())

    assert gallery is not None
    assert gallery.items == ()
    assert gallery.rejected_count == 1
    assert gallery.provider_ids == ("fixture-media",)
    assert gallery.rejection_reasons == (("disaster_missing", 1),)
    assert gallery.warnings == (
        "No source-associated images met the event and media safety gates.",
    )


def test_filesystem_media_assets_survive_store_reconstruction(tmp_path: Path) -> None:
    module = import_module("disaster_monitor.infrastructure.media.filesystem_store")
    store_type = module.FilesystemMediaAssetStore
    media = RetrievedMedia(
        _candidate("durable"), b"durable-image-bytes", "image/png", 640, 360
    )

    stored = store_type(tmp_path / "event-media").put(media)
    reloaded = store_type(tmp_path / "event-media").get(stored.media_id)

    assert reloaded == stored


def test_full_filesystem_store_preserves_existing_media_reference(
    tmp_path: Path,
) -> None:
    module = import_module("disaster_monitor.infrastructure.media.filesystem_store")
    store_type = module.FilesystemMediaAssetStore
    first = RetrievedMedia(
        _candidate("retained"), b"retained-image", "image/png", 640, 360
    )
    second = RetrievedMedia(_candidate("new"), b"new-image", "image/png", 640, 360)
    store = store_type(tmp_path / "event-media", maximum_bytes=len(first.content))

    retained = store.put(first)
    with pytest.raises(ValueError, match="byte limit"):
        store.put(second)

    assert (
        store_type(tmp_path / "event-media", maximum_bytes=len(first.content)).get(
            retained.media_id
        )
        == retained
    )
