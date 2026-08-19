from datetime import UTC, datetime

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
