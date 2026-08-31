"""Conservative event association, selection, and storage for source media."""

import asyncio
import re
import unicodedata
from collections.abc import Callable, Iterable
from datetime import UTC, datetime, timedelta

from disaster_monitor.application.media import (
    DisasterMediaCandidate,
    DisasterMediaGallery,
    DisasterMediaItem,
    MediaAssociationStatus,
    MediaCandidateAssessment,
    MediaContentRole,
    MediaEventContext,
)
from disaster_monitor.application.ports.event_media import (
    EventMediaProvider,
    MediaAssetStore,
)
from disaster_monitor.domain.disaster import Disaster

_DISASTER_TERMS: dict[Disaster, tuple[str, ...]] = {
    Disaster.EARTHQUAKE: ("earthquake", "quake", "tremor"),
    Disaster.FLOOD: ("flood", "flooding", "inundation"),
    Disaster.WILDFIRE: ("wildfire", "bushfire", "forest fire"),
    Disaster.LANDSLIDE: ("landslide", "mudslide", "debris flow"),
    Disaster.TROPICAL_CYCLONE: (
        "tropical cyclone",
        "cyclone",
        "hurricane",
        "typhoon",
        "tropical storm",
    ),
}
_ROLE_TERMS: tuple[tuple[MediaContentRole, tuple[str, ...]], ...] = (
    (
        MediaContentRole.RESCUE_EFFORT,
        (
            "rescue",
            "rescuer",
            "rescuers",
            "rescue worker",
            "rescue workers",
            "search crew",
            "search for survivors",
            "survivor",
            "survivors",
            "first responder",
        ),
    ),
    (
        MediaContentRole.RELIEF_OPERATION,
        ("relief", "aid distribution", "shelter", "evacuee", "humanitarian"),
    ),
    (
        MediaContentRole.AFTERMATH,
        ("aftermath", "rubble", "debris", "damage", "destroyed", "collapsed"),
    ),
    (
        MediaContentRole.SCIENTIFIC_OVERVIEW,
        ("satellite", "aerial", "map", "intensity", "epicenter"),
    ),
)


class EventMediaAssociationPolicy:
    """Admit source metadata; pixels cannot establish event identity."""

    def assess(
        self,
        candidate: DisasterMediaCandidate,
        context: MediaEventContext,
        *,
        now: datetime,
    ) -> MediaCandidateAssessment:
        rules: list[str] = []
        published_at = _aware(candidate.published_at)
        event_time = _aware(context.event_time)
        now = _aware(now)
        if not event_time - timedelta(days=1) <= published_at:
            return self._rejected(candidate, "media.association.article_predates_event")
        if published_at > min(
            now + timedelta(hours=1), event_time + timedelta(days=30)
        ):
            return self._rejected(candidate, "media.association.article_outside_window")
        rules.append("media.association.publication_window")
        if candidate.captured_at is not None:
            captured_at = _aware(candidate.captured_at)
            if (
                not event_time - timedelta(days=1)
                <= captured_at
                <= event_time + timedelta(days=30)
            ):
                return self._rejected(
                    candidate, "media.association.capture_time_mismatch"
                )
            rules.append("media.association.capture_window")

        primary_text = _normalized(
            " ".join((candidate.article_title, candidate.caption))
        )
        context_text = _normalized(candidate.context_text)
        text = f"{primary_text} {context_text}".strip()
        disaster_terms = tuple(
            _normalized(item) for item in _DISASTER_TERMS[context.disaster]
        )
        if not any(_contains_term(primary_text, term) for term in disaster_terms):
            return self._rejected(candidate, "media.association.disaster_missing")
        rules.append("media.association.disaster_text")

        country_terms = tuple(
            _normalized(item)
            for item in context.country_terms
            if len(_normalized(item)) >= 4
        )
        if country_terms:
            if not any(_contains_term(primary_text, term) for term in country_terms):
                return self._rejected(candidate, "media.association.country_mismatch")
            rules.append("media.association.country_text")
        else:
            location_terms = _location_terms(context.location)
            if location_terms and not any(
                _contains_term(primary_text, term) for term in location_terms
            ):
                return self._rejected(candidate, "media.association.location_mismatch")
            if location_terms:
                rules.append("media.association.location_text")

        years = {
            int(value) for value in re.findall(r"\b(?:19|20)\d{2}\b", primary_text)
        }
        if years and event_time.year not in years:
            return self._rejected(candidate, "media.association.explicit_year_mismatch")
        if event_time.year in years:
            rules.append("media.association.event_year_text")

        identifiers = tuple(
            _normalized(item)
            for item in (context.event_id, *context.provider_ids)
            if item
        )
        exact = any(_contains_term(text, item) for item in identifiers)
        if exact:
            rules.append("media.association.provider_event_identifier")
        status = (
            MediaAssociationStatus.EXACT_EVENT_LINK
            if exact
            else MediaAssociationStatus.CORROBORATED
        )
        return MediaCandidateAssessment(
            candidate,
            status,
            tuple(rules),
            (
                "The source metadata explicitly names the selected provider event."
                if exact
                else "Publication time, disaster, and selected-event geography agree."
            ),
        )

    @staticmethod
    def _rejected(
        candidate: DisasterMediaCandidate, rule_id: str
    ) -> MediaCandidateAssessment:
        return MediaCandidateAssessment(
            candidate,
            MediaAssociationStatus.REJECTED,
            (rule_id,),
            "The source metadata did not safely match the selected event.",
        )


class DisasterMediaService:
    """Find a small gallery without changing event truth or report availability."""

    def __init__(
        self,
        providers: Iterable[EventMediaProvider],
        store: MediaAssetStore,
        *,
        clock: Callable[[], datetime],
        target_count: int = 3,
        association_policy: EventMediaAssociationPolicy | None = None,
    ) -> None:
        self._providers = tuple(providers)
        self._store = store
        self._clock = clock
        self._target_count = target_count
        self._association = association_policy or EventMediaAssociationPolicy()

    async def discover(self, context: MediaEventContext) -> DisasterMediaGallery | None:
        now = _aware(self._clock())
        accepted: list[tuple[EventMediaProvider, MediaCandidateAssessment]] = []
        rejected_count = 0
        provider_ids: list[str] = []
        warnings: list[str] = []
        for provider in self._providers:
            provider_ids.append(provider.provider_id)
            try:
                candidates = await provider.discover(context, now=now)
            except Exception:
                warnings.append(
                    f"Media discovery from {provider.provider_id} was unavailable."
                )
                continue
            for candidate in candidates:
                assessment = self._association.assess(candidate, context, now=now)
                if assessment.status == MediaAssociationStatus.REJECTED:
                    rejected_count += 1
                    continue
                accepted.append((provider, assessment))

        accepted.sort(key=_candidate_sort_key)
        items: list[DisasterMediaItem] = []
        checksums: set[str] = set()
        batch_size = max(self._target_count * 2, self._target_count)
        for start in range(0, len(accepted), batch_size):
            if len(items) >= self._target_count:
                break
            retrieval_batch = accepted[start : start + batch_size]
            retrievals = await asyncio.gather(
                *(
                    provider.retrieve(assessment.candidate)
                    for provider, assessment in retrieval_batch
                ),
                return_exceptions=True,
            )
            for (_, assessment), retrieved in zip(
                retrieval_batch, retrievals, strict=True
            ):
                if len(items) >= self._target_count:
                    break
                if isinstance(retrieved, BaseException):
                    rejected_count += 1
                    continue
                try:
                    stored = self._store.put(retrieved)
                except Exception:
                    rejected_count += 1
                    continue
                if stored.content_sha256 in checksums:
                    rejected_count += 1
                    continue
                checksums.add(stored.content_sha256)
                candidate = assessment.candidate
                items.append(
                    DisasterMediaItem(
                        media_id=stored.media_id,
                        event_id=context.event_id,
                        physical_event_id=context.physical_event_id,
                        source_id=candidate.source_id,
                        publisher=candidate.publisher,
                        source_page_url=candidate.source_page_url,
                        caption=candidate.caption,
                        credit=candidate.credit,
                        credit_kind=candidate.credit_kind,
                        published_at=candidate.published_at,
                        captured_at=candidate.captured_at,
                        license_name=candidate.license_name,
                        license_url=candidate.license_url,
                        rights_status=candidate.rights_status,
                        role=_content_role(candidate),
                        association_status=assessment.status,
                        association_rule_ids=assessment.rule_ids,
                        association_detail=assessment.detail,
                        uncertainty=(
                            "Source-associated preview; the photograph is contextual "
                            "media, not a verified Disaster Monitor fact."
                        ),
                        content_sha256=stored.content_sha256,
                        width=retrieved.width,
                        height=retrieved.height,
                    )
                )
        if not items:
            warnings.append(
                "No source-associated images met the event and media safety gates."
            )
        if items and len(items) < self._target_count:
            warnings.append(
                f"Only {len(items)} source-associated image(s) met the event and "
                "media safety gates."
            )
        return DisasterMediaGallery(
            event_id=context.event_id,
            physical_event_id=context.physical_event_id,
            generated_at=now,
            items=tuple(items),
            rejected_count=rejected_count,
            provider_ids=tuple(dict.fromkeys(provider_ids)),
            warnings=tuple(dict.fromkeys(warnings)),
        )

    async def aclose(self) -> None:
        for provider in self._providers:
            close = getattr(provider, "aclose", None)
            if close is not None:
                await close()


def _candidate_sort_key(
    value: tuple[EventMediaProvider, MediaCandidateAssessment],
) -> tuple[int, int, float, str]:
    candidate = value[1].candidate
    association_rank = (
        0 if value[1].status == MediaAssociationStatus.EXACT_EVENT_LINK else 1
    )
    return (
        association_rank,
        candidate.source_priority,
        -_aware(candidate.published_at).timestamp(),
        candidate.candidate_id,
    )


def _content_role(candidate: DisasterMediaCandidate) -> MediaContentRole:
    text = _normalized(
        f"{candidate.article_title} {candidate.context_text} {candidate.caption}"
    )
    for role, terms in _ROLE_TERMS:
        if any(_contains_term(text, _normalized(term)) for term in terms):
            return role
    return MediaContentRole.RELEVANT_SCENE


def _normalized(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    ascii_text = "".join(char for char in decomposed if not unicodedata.combining(char))
    return " ".join(re.sub(r"[^a-z0-9]+", " ", ascii_text).split())


def _contains_term(text: str, term: str) -> bool:
    return bool(term) and f" {term} " in f" {text} "


def _location_terms(location: str) -> tuple[str, ...]:
    parts = [item.strip() for item in location.split(",") if item.strip()]
    first = parts[0] if parts else location
    first = re.sub(
        r"^\s*\d+(?:\.\d+)?\s*km\s+[A-Z-]+\s+of\s+",
        "",
        first,
        flags=re.IGNORECASE,
    )
    normalized_parts = tuple(
        item
        for item in (_normalized(first), *(_normalized(item) for item in parts[1:]))
        if len(item) >= 4
    )
    words = tuple(
        word for phrase in normalized_parts for word in phrase.split() if len(word) >= 4
    )
    return tuple(dict.fromkeys((*normalized_parts, *words)))


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
