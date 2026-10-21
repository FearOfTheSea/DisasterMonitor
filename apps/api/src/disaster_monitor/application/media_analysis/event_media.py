"""Conservative event association, selection, and storage for source media."""

import asyncio
import base64
import json
import re
import unicodedata
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from hashlib import sha256

from disaster_monitor.application.media import (
    DisasterMediaCandidate,
    DisasterMediaGallery,
    DisasterMediaItem,
    MediaAssociationStatus,
    MediaCandidateAssessment,
    MediaContentRole,
    MediaContinuationError,
    MediaDiscoveryBatch,
    MediaEventContext,
    MediaSourceAttribution,
    MediaUnavailableSource,
)
from disaster_monitor.application.ports.event_media import (
    EventMediaProvider,
    MediaAssetStore,
)
from disaster_monitor.domain.disaster import Disaster
from disaster_monitor.domain.hazards.news_classification import disasters_in_text

# Extra descriptive media terms supplement the canonical domain hazard vocabulary.
_MEDIA_CONTEXT_TERMS: dict[Disaster, tuple[str, ...]] = {
    Disaster.EARTHQUAKE: ("tremor",),
    Disaster.LANDSLIDE: ("debris flow",),
    Disaster.DROUGHT: ("dry spell", "water shortage"),
    Disaster.VOLCANIC_ERUPTION: ("volcano eruption", "eruptive activity", "ash plume"),
}


def _mentions_disaster(text: str, disaster: Disaster) -> bool:
    return disaster in disasters_in_text(text) or any(
        _contains_term(_normalized(text), term)
        for term in _MEDIA_CONTEXT_TERMS.get(disaster, ())
    )


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
        if re.search(
            r"\b(?:file photo(?:graph)?|archiv\w*|stock (?:photo|image)|illustrat\w*|"
            r"advertisement|unrelated|recommended|logo)\b",
            candidate.caption,
            re.I,
        ):
            return self._rejected(candidate, "media.association.unrelated_asset")
        linked = any(
            source.canonical_url == candidate.source_page_url
            for source in context.collected_articles
        )
        if linked:
            if candidate.source_page_url in context.multi_event_article_urls:
                caption = _normalized(candidate.caption)
                hazard_match = _mentions_disaster(candidate.caption, context.disaster)
                places = _location_terms(context.location)
                if (
                    not hazard_match
                    or not places
                    or not any(_contains_term(caption, term) for term in places)
                ):
                    return self._rejected(
                        candidate, "media.association.multi_event_caption_unresolved"
                    )
            if context.event_time_known:
                years = {
                    int(y) for y in re.findall(r"\b(?:19|20)\d{2}\b", candidate.caption)
                }
                if years and context.event_time.year not in years:
                    return self._rejected(
                        candidate, "media.association.explicit_year_mismatch"
                    )
                if candidate.captured_at and _aware(candidate.captured_at) < _aware(
                    context.event_time
                ) - timedelta(days=1):
                    return self._rejected(
                        candidate, "media.association.capture_time_mismatch"
                    )
            else:
                years = {
                    int(y) for y in re.findall(r"\b(?:19|20)\d{2}\b", candidate.caption)
                }
                if years and (
                    candidate.published_at is None
                    or years != {candidate.published_at.year}
                ):
                    return self._rejected(
                        candidate, "media.association.unresolved_capture_context"
                    )
            return MediaCandidateAssessment(
                candidate,
                MediaAssociationStatus.EXACT_EVENT_LINK,
                ("media.association.collected_article",)
                + (
                    ("media.association.event_time_unresolved",)
                    if not context.event_time_known
                    else ()
                ),
                (
                    "Photograph belongs to a retained event article; article "
                    "association does not independently verify the photographed "
                    "place or time."
                    + (
                        " Event time remains unresolved; "
                        "the caption date is not event onset."
                        if not context.event_time_known
                        else ""
                    )
                ),
            )
        if not context.event_time_known:
            return self._rejected(candidate, "media.association.event_time_unknown")
        rules: list[str] = []
        if candidate.published_at is None:
            return self._rejected(candidate, "media.association.publication_unknown")
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
        if not _mentions_disaster(primary_text, context.disaster):
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
    """Retain a bounded collection without changing event truth or report access."""

    def __init__(
        self,
        providers: Iterable[EventMediaProvider],
        store: MediaAssetStore,
        *,
        clock: Callable[[], datetime],
        target_count: int = 72,
        association_policy: EventMediaAssociationPolicy | None = None,
    ) -> None:
        self._providers = tuple(providers)
        self._store = store
        self._clock = clock
        if not 1 <= target_count <= 180:
            raise ValueError("Media collection must retain between 1 and 180 assets.")
        self._target_count = target_count
        self._association = association_policy or EventMediaAssociationPolicy()

    async def discover(
        self, context: MediaEventContext, *, cursor: str | None = None
    ) -> DisasterMediaGallery | None:
        now = _aware(self._clock())
        accepted: list[tuple[EventMediaProvider, MediaCandidateAssessment]] = []
        rejected_count = 0
        rejection_reasons: Counter[str] = Counter()
        provider_ids: list[str] = []
        warnings: list[str] = []
        unavailable: list[MediaUnavailableSource] = []
        truncated = False
        candidate_count = 0
        scope = sha256(
            (
                context.collection_version
                + "|".join(p.provider_id for p in self._providers)
            ).encode()
        ).hexdigest()
        start_provider, provider_cursor = _gallery_position(
            cursor, scope, len(self._providers)
        )
        next_cursor = None
        for index in range(start_provider, len(self._providers)):
            provider = self._providers[index]
            provider_ids.append(provider.provider_id)
            try:
                candidates = await asyncio.wait_for(
                    provider.discover(
                        context,
                        now=now,
                        cursor=provider_cursor if index == start_provider else None,
                        maximum_candidates=max(1, self._target_count - len(accepted)),
                    ),
                    timeout=120,
                )
            except MediaContinuationError:
                raise
            except Exception:
                warnings.append(
                    f"Media discovery from {provider.provider_id} was unavailable."
                )
                continue
            continuation = None
            if isinstance(candidates, MediaDiscoveryBatch):
                warnings.extend(candidates.warnings)
                unavailable.extend(candidates.unavailable_sources)
                truncated = truncated or candidates.truncated
                continuation = candidates.next_cursor
                candidates = candidates.candidates
            candidate_count += len(candidates)
            if len(candidates) > 180:
                truncated = True
            for candidate in candidates[:180]:
                assessment = self._association.assess(candidate, context, now=now)
                if assessment.status == MediaAssociationStatus.REJECTED:
                    rejected_count += 1
                    rejection_reasons[assessment.rule_ids[-1].rsplit(".", 1)[-1]] += 1
                    unavailable.append(
                        MediaUnavailableSource(
                            candidate.source_page_url,
                            candidate.publisher,
                            "Photograph excluded: "
                            + assessment.rule_ids[-1]
                            .rsplit(".", 1)[-1]
                            .replace("_", " "),
                        )
                    )
                    continue
                accepted.append((provider, assessment))
            if continuation is not None:
                next_cursor = _gallery_cursor(scope, index, continuation)
                break
            if len(accepted) >= self._target_count and index + 1 < len(self._providers):
                next_cursor = _gallery_cursor(scope, index + 1, None)
                break

        accepted.sort(key=_candidate_sort_key)
        truncated = truncated or len(accepted) > 180
        accepted = accepted[:180]
        items: list[DisasterMediaItem] = []
        checksums: dict[str, int] = {}
        batch_size = 4
        for start in range(0, len(accepted), batch_size):
            if len(items) >= self._target_count:
                truncated = True
                break
            retrieval_batch = accepted[start : start + batch_size]
            retrievals = await asyncio.gather(
                *(
                    asyncio.wait_for(
                        provider.retrieve(assessment.candidate), timeout=20
                    )
                    for provider, assessment in retrieval_batch
                ),
                return_exceptions=True,
            )
            for (_, assessment), retrieved in zip(
                retrieval_batch, retrievals, strict=True
            ):
                if len(items) >= self._target_count:
                    truncated = True
                    break
                if isinstance(retrieved, BaseException):
                    rejected_count += 1
                    rejection_reasons["delivery_failed"] += 1
                    unavailable.append(
                        MediaUnavailableSource(
                            assessment.candidate.source_page_url,
                            assessment.candidate.publisher,
                            (
                                "Photograph delivery failed; source article remains "
                                "available."
                            ),
                        )
                    )
                    continue
                try:
                    stored = self._store.put(retrieved)
                except Exception:
                    rejected_count += 1
                    rejection_reasons["storage_failed"] += 1
                    unavailable.append(
                        MediaUnavailableSource(
                            assessment.candidate.source_page_url,
                            assessment.candidate.publisher,
                            (
                                "Media storage limit or storage failure; "
                                "source article remains available."
                            ),
                        )
                    )
                    continue
                if stored.content_sha256 in checksums:
                    rejected_count += 1
                    rejection_reasons["duplicate_content"] += 1
                    index = checksums[stored.content_sha256]
                    items[index] = replace(
                        items[index],
                        source_references=tuple(
                            dict.fromkeys(
                                (
                                    *items[index].source_references,
                                    _attribution(assessment.candidate),
                                )
                            )
                        ),
                    )
                    continue
                checksums[stored.content_sha256] = len(items)
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
                        source_references=(_attribution(candidate),),
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
        truncated = truncated or next_cursor is not None
        if next_cursor is not None:
            warnings.append(
                "More source photographs remain. Continue collection "
                "to inspect the next bounded batch."
            )
        elif truncated:
            warnings.append(
                "Photograph collection truncated by acquisition or "
                "retained-asset limits. Source articles remain available."
            )
        return DisasterMediaGallery(
            event_id=context.event_id,
            physical_event_id=context.physical_event_id,
            generated_at=now,
            items=tuple(items),
            rejected_count=rejected_count,
            provider_ids=tuple(dict.fromkeys(provider_ids)),
            warnings=tuple(dict.fromkeys(warnings)),
            rejection_reasons=tuple(sorted(rejection_reasons.items())),
            collection_limit=self._target_count,
            candidate_count=candidate_count,
            truncated=truncated,
            unavailable_sources=tuple(dict.fromkeys(unavailable)),
            source_articles=context.collected_articles,
            next_cursor=next_cursor,
        )

    async def aclose(self) -> None:
        for provider in self._providers:
            close = getattr(provider, "aclose", None)
            if close is not None:
                await close()


def _gallery_cursor(scope: str, provider: int, cursor: str | None) -> str:
    return base64.urlsafe_b64encode(
        json.dumps([scope, provider, cursor]).encode()
    ).decode()


def _gallery_position(
    cursor: str | None, scope: str, count: int
) -> tuple[int, str | None]:
    if cursor is None:
        return 0, None
    try:
        if len(cursor) > 8192:
            raise ValueError("Cursor exceeds bound")
        values = json.loads(base64.b64decode(cursor, altchars=b"-_", validate=True))
        if not isinstance(values, list) or len(values) != 3:
            raise ValueError("Invalid cursor")
        supplied_scope, provider, token = values
        if (
            supplied_scope != scope
            or type(provider) is not int
            or not 0 <= provider < count
            or (token is not None and (not isinstance(token, str) or len(token) > 4096))
        ):
            raise ValueError("Cursor does not match collection")
        return provider, token
    except (ValueError, TypeError, UnicodeDecodeError, RecursionError):
        raise MediaContinuationError(
            "Invalid or changed media collection. "
            "Restart photographs from the selected event."
        ) from None


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
        -_aware(candidate.published_at).timestamp()
        if candidate.published_at
        else float("inf"),
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


def _attribution(candidate: DisasterMediaCandidate) -> MediaSourceAttribution:
    return MediaSourceAttribution(
        candidate.source_page_url,
        candidate.publisher,
        candidate.caption,
        candidate.credit,
        candidate.credit_kind,
        candidate.published_at,
        candidate.captured_at,
        candidate.rights_status,
    )
