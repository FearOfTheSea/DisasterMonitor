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
from disaster_monitor.application.services.event_media import (
    DisasterMediaService,
    EventMediaAssociationPolicy,
)
from disaster_monitor.domain.disaster import Disaster
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
        (Disaster.TROPICAL_CYCLONE, "typhoon"),
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
