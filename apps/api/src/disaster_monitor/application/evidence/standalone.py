"""Lazy, bounded, non-model evidence retrieval with existing admission policies."""

import asyncio
import json
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
from math import isfinite
from typing import cast

from disaster_monitor.application.disaster import DisasterQuery
from disaster_monitor.application.evidence.evidence_reconciliation import (
    EvidenceReconciler,
)
from disaster_monitor.application.evidence.standalone_models import (
    AssociatedWarning,
    EvidenceSection,
    StandaloneEvidenceResult,
)
from disaster_monitor.application.media import MediaContinuationError
from disaster_monitor.application.ports.disaster_information import (
    SituationReportProvider,
)
from disaster_monitor.application.ports.standalone_evidence import (
    BaselineReader,
    CurrentWarningReader,
    EventMediaReader,
    ExposureReader,
    HumanitarianReader,
    IncidentEvidenceContext,
    IncidentEvidenceReader,
)
from disaster_monitor.application.warnings.association import (
    associate_earthquake_tsunami_warning,
    associate_warning,
)
from disaster_monitor.application.warnings.lifecycle import reconcile_cap_messages
from disaster_monitor.domain.disaster import EventCoordinate, geographic_distance_km
from disaster_monitor.domain.event_identifiers import (
    EventIdentifierRole,
    event_identifier_role,
)
from disaster_monitor.domain.events import EventGeometryKind
from disaster_monitor.domain.exposure import ExposureGeometry, ExposureGeometryRole
from disaster_monitor.domain.hazards.taxonomy import DEFAULT_HAZARD_TAXONOMY
from disaster_monitor.domain.imagery.regions import polygon_from_geojson
from disaster_monitor.domain.reported_impacts import inspect_report_impacts
from disaster_monitor.domain.warnings import WarningLifecycleState


class StandaloneEvidenceService:
    def __init__(
        self,
        contexts: IncidentEvidenceReader,
        *,
        situation: SituationReportProvider | None = None,
        reconciler: EvidenceReconciler | None = None,
        warnings: CurrentWarningReader | None = None,
        exposure: ExposureReader | None = None,
        humanitarian: HumanitarianReader | None = None,
        baseline: BaselineReader | None = None,
        media: EventMediaReader | None = None,
        dataset_limitations: tuple[str, ...] = (),
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._contexts = contexts
        self._situation = situation
        self._reconciler = reconciler or EvidenceReconciler()
        self._warnings = warnings
        self._exposure = exposure
        self._humanitarian = humanitarian
        self._baseline = baseline
        self._media = media
        self._dataset_limitations = dataset_limitations
        self._clock = clock
        self._cache: OrderedDict[
            tuple[str, str, str | None], StandaloneEvidenceResult
        ] = OrderedDict()
        self._inflight: dict[
            tuple[str, str, str | None], asyncio.Task[StandaloneEvidenceResult]
        ] = {}
        self._checked: dict[tuple[str, str, str | None], datetime] = {}
        self._sizes: dict[tuple[str, str, str | None], int] = {}
        self._cache_bytes = 0

    async def execute(
        self, identifier: str, section: str, *, cursor: str | None = None
    ) -> StandaloneEvidenceResult:
        if cursor is not None and section != "media":
            raise ValueError("Continuation is supported only for photographs.")
        if section not in (
            "impacts",
            "warnings",
            "forecast",
            "exposure",
            "humanitarian",
            "media",
        ):
            raise ValueError("Unsupported evidence section.")
        context = await self._contexts.read(identifier)
        cache_identity = (
            context.media.collection_version
            if section == "media"
            else context.media.physical_event_id
        )
        key = (cache_identity, section, cursor)
        cached = self._cache.get(key)
        ttl = timedelta(
            minutes=1
            if cached and cached.state in ("error", "degraded")
            else 2
            if section == "warnings"
            else 5
        )
        if cached and self._clock() - self._checked[key] < ttl:
            return cached
        task = self._inflight.get(key)
        if task is None:
            task = asyncio.create_task(
                self._load(context, cast(EvidenceSection, section), cursor=cursor)
            )
            self._inflight[key] = task
        try:
            result = await asyncio.shield(task)
            if (
                (
                    result.state == "error"
                    or (result.state == "degraded" and not _has_evidence(result))
                )
                and cached
                and cached.state in ("available", "empty", "degraded")
            ):
                result = replace(
                    cached,
                    state="degraded",
                    limitations=(
                        *cached.limitations,
                        *result.limitations,
                        (
                            "Refresh failed; retained evidence shows its original "
                            "retrieval time."
                        ),
                    ),
                )
            self._cache_bytes -= self._sizes.pop(key, 0)
            self._checked[key] = self._clock()
            self._sizes[key] = len(json.dumps(asdict(result), default=str).encode())
            self._cache_bytes += self._sizes[key]
            self._cache[key] = result
            self._cache.move_to_end(key)
            while len(self._cache) > 128 or self._cache_bytes > 16 * 1024 * 1024:
                removed, _ = self._cache.popitem(last=False)
                self._cache_bytes -= self._sizes.pop(removed)
                self._checked.pop(removed, None)
            return result
        except MediaContinuationError:
            initial_key = (cache_identity, "media", None)
            self._cache.pop(initial_key, None)
            self._cache_bytes -= self._sizes.pop(initial_key, 0)
            self._checked.pop(initial_key, None)
            raise
        finally:
            if task.done():
                self._inflight.pop(key, None)

    async def execute_inspection(
        self, identifier: str, bounds: tuple[float, float, float, float]
    ) -> StandaloneEvidenceResult:
        west, south, east, north = bounds
        if (
            not all(isfinite(value) for value in bounds)
            or not (-180 <= west < east <= 180 and -90 <= south < north <= 90)
            or east - west > 0.5
            or north - south > 0.5
            or geographic_distance_km(
                EventCoordinate(south, west), EventCoordinate(north, east)
            )
            > 60
        ):
            raise ValueError(
                "An operator inspection area requires bounded WGS84 "
                "coordinates and a diagonal at most 60 km."
            )
        context = await self._contexts.read(identifier)
        result = StandaloneEvidenceResult(
            context.media.event_id,
            context.media.physical_event_id,
            "exposure",
            "unconfigured",
            self._clock(),
            limitations=self._dataset_limitations,
        )
        if self._exposure is None:
            return replace(result, reason_codes=("datasets_unconfigured",))
        geometry = polygon_from_geojson(
            {
                "type": "Polygon",
                "coordinates": [
                    [
                        [west, south],
                        [east, south],
                        [east, north],
                        [west, north],
                        [west, south],
                    ]
                ],
            }
        )
        try:
            analysis = await self._exposure.execute(
                ExposureGeometry(
                    geometry,
                    ExposureGeometryRole.OPERATOR_INSPECTION,
                    "operator-inspection",
                    geometry.sha256(),
                    self._clock(),
                )
            )
            return replace(
                result,
                state="available",
                exposure=analysis,
                limitations=analysis.limitations,
            )
        except (ValueError, OSError):
            return replace(
                result,
                state="degraded",
                reason_codes=("dataset_coverage_unavailable",),
                limitations=(
                    (
                        "The supplied datasets cannot calculate this inspection area."
                        " Check coverage and valid pixels."
                    ),
                ),
            )

    async def aclose(self) -> None:
        tasks = tuple(self._inflight.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _load(
        self,
        context: IncidentEvidenceContext,
        section: EvidenceSection,
        *,
        cursor: str | None = None,
    ) -> StandaloneEvidenceResult:
        result = StandaloneEvidenceResult(
            context.media.event_id,
            context.media.physical_event_id,
            section,
            "empty",
            self._clock(),
        )
        try:
            if section == "warnings":
                return await self._related_warnings(context, result)
            if section == "media":
                if self._media is None:
                    return replace(
                        result,
                        state="unconfigured",
                        reason_codes=("media_unconfigured",),
                    )
                gallery = (
                    await self._media.discover(context.media, cursor=cursor)
                    if cursor is not None
                    else await self._media.discover(context.media)
                )
                return replace(
                    result,
                    state="available" if gallery and gallery.items else "empty",
                    media=gallery,
                    limitations=gallery.warnings
                    if gallery
                    else ("No admitted contextual photographs were returned.",),
                )
            if section == "exposure" and self._exposure is None:
                return replace(
                    result,
                    state="unconfigured",
                    reason_codes=("datasets_unconfigured",),
                    limitations=self._dataset_limitations
                    or (
                        (
                            "Supply a validated operator dataset manifest for "
                            "WorldPop/GHSL and local OSM."
                        ),
                    ),
                )
            event = context.event
            if event is None:
                return replace(
                    result,
                    reason_codes=("country_unresolved",),
                    limitations=(
                        (
                            "Country association is unresolved; "
                            "country-specific evidence"
                            " was not requested."
                        ),
                    ),
                )
            if section == "exposure":
                if (
                    context.geometry is None
                    or event.geometry is None
                    or event.geometry.kind is not EventGeometryKind.AREA
                ):
                    return replace(
                        result,
                        reason_codes=("supported_geometry_missing",),
                        limitations=(
                            (
                                "No supported source area is available. "
                                "A point locator is "
                                "not an impact footprint."
                            ),
                        ),
                    )
                assert self._exposure is not None
                analysis = await self._exposure.execute(
                    ExposureGeometry(
                        context.geometry,
                        ExposureGeometryRole.MAPPED_HAZARD,
                        event.source.source_id,
                        event.source.snapshot_id or event.event_id,
                        event.event_time,
                    )
                )
                return replace(
                    result,
                    state="available",
                    exposure=analysis,
                    limitations=analysis.limitations,
                )
            if section == "humanitarian":
                snapshot = (
                    await self._humanitarian.for_country(
                        event.country.alpha3_code, event_id=event.event_id
                    )
                    if self._humanitarian
                    else None
                )
                baseline = (
                    self._baseline.lookup(event.country.alpha3_code)
                    if self._baseline
                    else None
                )
                found = baseline is not None or bool(
                    snapshot and (snapshot.indicators or snapshot.operational_presence)
                )
                return replace(
                    result,
                    state="available" if found else "empty",
                    humanitarian=snapshot,
                    baseline=baseline,
                    limitations=(
                        *self._dataset_limitations,
                        (
                            "Country context and baseline vulnerability "
                            "do not establish "
                            "event impacts."
                        ),
                    ),
                )
            if self._situation is None:
                return replace(
                    result,
                    state="unconfigured",
                    reason_codes=("situation_unconfigured",),
                )
            query = DisasterQuery(
                event.disaster,
                event.country,
                "selected incident",
                (),
                time_window_days=30,
                latitude=context.media.latitude,
                longitude=context.media.longitude,
            )
            batch = await self._situation.get_situation_reports(
                event, query, now=self._clock()
            )
            packet = self._reconciler.build(
                query,
                event,
                batch.records,
                warnings=tuple(issue.detail for issue in batch.issues if issue.detail),
                retrieved_at=self._clock(),
            )
            if section == "forecast":
                return replace(
                    result,
                    state="degraded"
                    if batch.issues
                    else "available"
                    if packet.supplemental_geometry
                    else "empty",
                    forecast_layers=packet.supplemental_geometry,
                    limitations=packet.warnings,
                )
            accounts = tuple(
                account
                for report in (packet.world_state.reports if packet.world_state else ())
                for account in inspect_report_impacts(report)
            )
            return replace(
                result,
                state="degraded"
                if batch.issues or packet.partial
                else "available"
                if accounts
                else "empty",
                facts=tuple(account.fact for account in accounts),
                reported_accounts=accounts,
                limitations=(
                    *packet.warnings,
                    "All admitted in-scope source accounts are shown. "
                    "Counts are not added or selected as truth; "
                    "dates and geographic scopes may differ.",
                ),
            )
        except MediaContinuationError:
            raise
        except Exception:
            return replace(
                result,
                state="error",
                reason_codes=("section_retrieval_failed",),
                limitations=(
                    (
                        "This section could not be retrieved or validated. Other "
                        "sections remain available."
                    ),
                ),
            )

    async def _related_warnings(
        self, context: IncidentEvidenceContext, result: StandaloneEvidenceResult
    ) -> StandaloneEvidenceResult:
        if self._warnings is None:
            return replace(
                result, state="unconfigured", reason_codes=("warnings_unconfigured",)
            )
        batch = await self._warnings.current_messages()
        media = context.media
        associations = []
        for item in reconcile_cap_messages(batch.alerts, now=self._clock()):
            if item.state is not WarningLifecycleState.ACTIVE:
                continue
            association = None
            identifiers = tuple(
                identifier
                for identifier in (
                    media.physical_event_id,
                    media.event_id,
                    *media.provider_ids,
                )
                if event_identifier_role(identifier)
                is EventIdentifierRole.PHYSICAL_EVENT
            )
            identifiers = tuple(
                sorted(
                    identifiers,
                    key=lambda identifier: (
                        identifier.casefold()
                        not in {value.casefold() for value in item.alert.incidents}
                    ),
                )
            )
            for identifier in identifiers:
                association = associate_warning(
                    item.alert,
                    disaster=media.disaster,
                    event_id=identifier,
                    event_time=media.event_time,
                    event_geometry=context.geometry,
                )
                if association is not None:
                    break
            if (
                association is None
                and DEFAULT_HAZARD_TAXONOMY.require(
                    media.disaster.value
                ).tsunami_warning_context
                and media.latitude is not None
                and media.longitude is not None
            ):
                association = associate_earthquake_tsunami_warning(
                    item.alert,
                    earthquake_event_id=media.event_id,
                    earthquake_time=media.event_time,
                    earthquake_latitude=media.latitude,
                    earthquake_longitude=media.longitude,
                )
            if association is not None:
                associations.append(AssociatedWarning(item.alert, association))
        return replace(
            result,
            state="degraded"
            if batch.issue
            else "available"
            if associations
            else "empty",
            warnings=tuple(associations),
            limitations=((batch.issue.detail,) if batch.issue else ())
            + (
                (
                    "Candidate warnings indicate compatible time and source "
                    "geometry; they do not confirm event impacts."
                ),
            ),
        )


def _has_evidence(result: StandaloneEvidenceResult) -> bool:
    return bool(
        result.facts
        or result.narratives
        or result.forecast_layers
        or result.warnings
        or result.exposure
        or result.humanitarian
        or result.baseline
        or (result.media and result.media.items)
    )
