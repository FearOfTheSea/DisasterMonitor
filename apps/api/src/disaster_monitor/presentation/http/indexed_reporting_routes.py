"""Expose index observations without treating their wording as publisher captures."""

from datetime import datetime
from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from disaster_monitor.application.incidents.indexed_reporting import (
    MAX_QUERY_LENGTH,
    IndexedReportingQueries,
)

router = APIRouter()


class IndexedReportingItemResponse(BaseModel):
    observation_id: str
    provider: str
    observed_at: datetime
    publisher: str
    title: str
    canonical_url: str
    published_at: datetime | None
    updated_at: datetime | None
    indexed_at: datetime | None
    index_excerpt: str | None
    search_wording: str | None


class IndexedReportingResponse(BaseModel):
    items: list[IndexedReportingItemResponse]
    query: str
    snapshot: str
    next_cursor: str | None


def service(request: Request) -> IndexedReportingQueries:
    queries = cast(
        IndexedReportingQueries | None, request.app.state.dependencies.indexed_reporting
    )
    if queries is None:
        raise HTTPException(503, "Indexed reporting is unavailable.")
    return queries


@router.get(
    "/discovery-scans/{scan_id}/indexed-reporting",
    response_model=IndexedReportingResponse,
    tags=["discovery"],
)
async def indexed_reporting(
    scan_id: UUID,
    queries: Annotated[IndexedReportingQueries, Depends(service)],
    query: Annotated[str, Query(max_length=MAX_QUERY_LENGTH)] = "",
    cursor: Annotated[str | None, Query(max_length=2048)] = None,
) -> IndexedReportingResponse:
    try:
        page = await queries.read(str(scan_id), query=query, cursor=cursor)
    except LookupError as error:
        raise HTTPException(404, str(error)) from error
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    return IndexedReportingResponse(
        items=[
            IndexedReportingItemResponse(
                observation_id=observation.observation_id,
                provider=observation.provider,
                observed_at=observation.observed_at,
                publisher=observation.item.publisher,
                title=observation.item.title,
                canonical_url=observation.item.canonical_url,
                published_at=observation.item.published_at,
                updated_at=observation.item.updated_at,
                indexed_at=observation.item.indexed_at,
                index_excerpt=observation.item.discovery_hint,
                search_wording=observation.item.search_title,
            )
            for observation in page.observations
        ],
        query=page.query,
        snapshot=page.snapshot,
        next_cursor=page.next_cursor,
    )
