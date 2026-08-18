"""Focused adapter for official Fire and Disaster Management Agency reports."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from html.parser import HTMLParser
from io import BytesIO
from urllib.parse import urljoin

import httpx
from pypdf import PdfReader

from disaster_monitor.application.disaster import (
    DisasterQuery,
    ProviderBatch,
    ProviderIssue,
)
from disaster_monitor.application.services.evidence_reconciliation import (
    sanitize_provider_text,
)
from disaster_monitor.domain.disaster import (
    DisasterEvent,
    FactStatus,
    ReportedFact,
    SituationReport,
    SourceAuthority,
    SourceReference,
)
from disaster_monitor.infrastructure.disaster.errors import (
    DisasterProviderError,
    DisasterProviderResponseError,
)
from disaster_monitor.infrastructure.disaster.http import (
    SourcePayloadRecorder,
    build_snapshot_capture,
    get_bytes,
    get_text,
)

FDMA_INDEX_URL = "https://www.fdma.go.jp/disaster/info/"
JAPAN_TIMEZONE = timezone(timedelta(hours=9))
_NUMBER = r"([0-9][0-9,]*)"
_LOCATION_ALIASES = {
    "kumamoto": ("\u718a\u672c",),
    "aomori": ("\u9752\u68ee",),
    "ishikawa": ("\u77f3\u5ddd",),
    "tokyo": ("\u6771\u4eac",),
    "iwate": ("\u5ca9\u624b",),
    "miyagi": ("\u5bae\u57ce",),
    "fukushima": ("\u798f\u5cf6",),
    "yamanashi": ("\u5c71\u68a8",),
    "ibaraki": ("\u8328\u57ce",),
}


@dataclass(frozen=True, slots=True)
class _IndexEntry:
    title: str
    url: str
    event_date: datetime | None
    published_at: datetime | None
    revision: int


class _IndexParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.rows: list[tuple[list[str], str]] = []
        self._cells: list[str] | None = None
        self._parts: list[str] = []
        self._href = ""
        self._link_parts: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "tr":
            self._cells = []
            self._href = ""
        elif tag == "li":
            self._cells = []
            self._href = ""
        elif self._cells is not None and tag in {"td", "th"}:
            self._parts = []
        elif self._cells is not None and tag == "a":
            values = dict((key, value or "") for key, value in attrs)
            self._href = values.get("href", self._href)
            self._link_parts = []

    def handle_data(self, data: str) -> None:
        if self._cells is not None:
            self._parts.append(data)
        if self._link_parts is not None:
            self._link_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if self._cells is None:
            return
        if tag == "a":
            if self._href and "/disaster/info/items/" in self._href:
                title = " ".join(self._link_parts or ()).strip()
                if title:
                    self.rows.append(([title], self._href))
            self._link_parts = None
        elif tag in {"td", "th"}:
            self._cells.append(" ".join(self._parts).strip())
            self._parts = []
        elif tag in {"tr", "li"}:
            if tag == "li" and self._href and "/disaster/info/items/" in self._href:
                self._cells = None
                return
            if tag == "li" and self._parts:
                self._cells.append(" ".join(self._parts).strip())
            if self._cells:
                self.rows.append((self._cells, self._href))
            self._cells = None


def _date(value: str) -> datetime | None:
    match = re.search(r"(20\d{2})[./\u5e74-](\d{1,2})[./\u6708-](\d{1,2})", value)
    if match:
        return datetime(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    reiwa = re.search(r"\u4ee4\u548c\s*(\d+)\u5e74\s*(\d+)\u6708\s*(\d+)\u65e5", value)
    if reiwa:
        return datetime(
            2018 + int(reiwa.group(1)),
            int(reiwa.group(2)),
            int(reiwa.group(3)),
        )
    return None


def _revision(value: str) -> int:
    match = re.search(
        r"\u7b2c\s*([0-9\uff10-\uff19]+)\s*\u5831|"
        r"(?:report|revision)\s*([0-9]+)",
        value,
        re.I,
    )
    if not match:
        return 0
    raw = next(item for item in match.groups() if item is not None)
    return int(
        raw.translate(
            str.maketrans(
                "\uff10\uff11\uff12\uff13\uff14\uff15\uff16\uff17\uff18\uff19",
                "0123456789",
            )
        )
    )


def _entry_event_date(cells: list[str], href: str) -> datetime | None:
    compact = re.search(r"(20\d{2})(\d{2})(\d{2})", href)
    if compact:
        return datetime(
            int(compact.group(1)), int(compact.group(2)), int(compact.group(3))
        )
    return _date(" ".join(cells))


def _clean_number(value: str) -> str:
    return value.replace(",", "")


def _fact(
    category: str,
    label: str,
    value: str,
    source: SourceReference,
    event: DisasterEvent,
    observed_at: datetime | None,
    japanese_label: str,
) -> ReportedFact:
    return ReportedFact(
        category=category,
        label=f"{label} ({japanese_label})",
        value=value,
        status=FactStatus.CONFIRMED,
        source=source,
        event_id=event.event_id,
        observed_at=observed_at,
        claim_id=category,
    )


def _first_number(text: str, patterns: tuple[str, ...]) -> str | None:
    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if match:
            return _clean_number(match.group(1))
    return None


def _extract_facts(
    text: str,
    source: SourceReference,
    event: DisasterEvent,
    observed_at: datetime | None,
) -> tuple[ReportedFact, ...]:
    normalized_text = text.translate(
        str.maketrans(
            "\uff10\uff11\uff12\uff13\uff14\uff15\uff16\uff17\uff18\uff19",
            "0123456789",
        )
    )
    patterns: tuple[tuple[str, str, str, tuple[str, ...]], ...] = (
        (
            "fatalities",
            "Fatalities",
            "死者",
            (rf"死者\D{{0,12}}{_NUMBER}", rf"fatalit\w*\D{{0,12}}{_NUMBER}"),
        ),
        (
            "injuries",
            "Injuries",
            "負傷者",
            (rf"負傷者\D{{0,12}}{_NUMBER}", rf"injur\w*\D{{0,12}}{_NUMBER}"),
        ),
        (
            "missing",
            "Missing people",
            "行方不明",
            (rf"行方不明\D{{0,12}}{_NUMBER}", rf"missing\D{{0,12}}{_NUMBER}"),
        ),
        (
            "rescue_operations",
            "Rescue incidents",
            "救助",
            (rf"救助\D{{0,12}}{_NUMBER}\s*件",),
        ),
        (
            "evacuations",
            "Evacuees",
            "避難者",
            (rf"避難者\D{{0,12}}{_NUMBER}", rf"evacuat\w*\D{{0,12}}{_NUMBER}"),
        ),
        (
            "shelters",
            "Shelters",
            "避難所",
            (rf"避難所\D{{0,12}}{_NUMBER}", rf"shelter\w*\D{{0,12}}{_NUMBER}"),
        ),
        (
            "buildings_destroyed",
            "Residential buildings destroyed",
            "全壊",
            (rf"全壊\D{{0,12}}{_NUMBER}", rf"destroyed\D{{0,12}}{_NUMBER}"),
        ),
        (
            "buildings_damaged",
            "Residential buildings damaged",
            "半壊/一部破損",
            (rf"(?:半壊|一部破損)\D{{0,12}}{_NUMBER}", rf"damaged\D{{0,12}}{_NUMBER}"),
        ),
        (
            "fires",
            "Fires",
            "火災",
            (rf"火災\D{{0,12}}{_NUMBER}", rf"fires?\D{{0,12}}{_NUMBER}"),
        ),
    )
    dead = "\u6b7b\u8005"
    facts: list[ReportedFact] = []
    for category, label, japanese_label, expressions in patterns:
        value = None
        if category == "fatalities" and dead in normalized_text:
            table_rows: list[str] = []
            for occurrence in re.finditer(dead, normalized_text):
                table_rows.extend(
                    re.findall(
                        r"(?m)^\s*(\d[\d,]*(?:[ \t]+\d[\d,]*){2,})[ \t]*$",
                        normalized_text[occurrence.start() :],
                    )
                )
                if table_rows:
                    break
            if table_rows:
                value = _clean_number(table_rows[0].split()[0])
        if value is None:
            value = _first_number(normalized_text, expressions)
        if value is not None:
            facts.append(
                _fact(
                    category, label, value, source, event, observed_at, japanese_label
                )
            )
    if re.search(
        r"(?:道路|鉄道|停電|断水|通行止め|infrastructure|disrupt|outage)", text, re.I
    ):
        facts.append(
            _fact(
                "infrastructure",
                "Infrastructure disruption",
                "Disruption reported",
                source,
                event,
                observed_at,
                "インフラ",
            )
        )
    if re.search(
        r"(?:消防|救急|緊急消防援助隊|response|deployment|救助隊)", text, re.I
    ):
        facts.append(
            _fact(
                "response",
                "Emergency-response deployments",
                "Response deployment reported",
                source,
                event,
                observed_at,
                "消防・救急対応",
            )
        )
    unique: dict[str, ReportedFact] = {}
    for fact in facts:
        unique.setdefault(fact.category, fact)
    return tuple(unique.values())


def _extract_pdf_text(payload: bytes) -> str:
    try:
        reader = PdfReader(BytesIO(payload))
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
    except Exception as error:
        raise DisasterProviderResponseError(
            "The official FDMA PDF had no extractable text.",
            reason_code="invalid_payload",
        ) from error
    if not text.strip():
        raise DisasterProviderResponseError(
            "The official FDMA PDF had no extractable text.",
            reason_code="invalid_payload",
        )
    return text


def _entry_matches(
    entry: _IndexEntry, event: DisasterEvent, query: DisasterQuery
) -> bool:
    event_time = event.event_time
    if event_time.tzinfo is None:
        event_time = event_time.replace(tzinfo=UTC)
    if (
        entry.event_date is None
        or entry.event_date.date() != event_time.astimezone(JAPAN_TIMEZONE).date()
    ):
        return False
    haystack = entry.title.lower()
    location_text = " ".join(
        (event.location, event.source.title, query.prefecture or "")
    ).lower()
    tokens = [
        token
        for token in re.findall(
            r"[a-z][a-z-]{2,}|[\u4e00-\u9fff\u3005\u3007\u30f6]+",
            location_text,
        )
        if token not in {"japan", "earthquake"}
    ]
    aliases = [alias for token in tokens for alias in _LOCATION_ALIASES.get(token, ())]
    aliases.extend(
        token[index : index + 2]
        for token in tokens
        if not token.isascii() and len(token) >= 2
        for index in range(len(token) - 1)
    )
    return any(token in haystack for token in (*tokens, *aliases)) or (
        query.prefecture is not None and query.prefecture.lower() in haystack
    )


class FdmaSituationReportAdapter:
    """Retrieve the newest matching official FDMA earthquake situation report."""

    provider_name = "FDMA"
    source_id = "fdma-situation-reports"
    allowed_hosts = frozenset({"www.fdma.go.jp"})

    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        snapshot_recorder: SourcePayloadRecorder | None = None,
        timeout_seconds: float = 10.0,
        max_response_bytes: int = 1_000_000,
    ) -> None:
        self._client = client or httpx.AsyncClient(timeout=timeout_seconds)
        self._owns_client = client is None
        self._max_response_bytes = max_response_bytes
        self._snapshot_recorder = snapshot_recorder

    async def get_situation_reports(
        self,
        event: DisasterEvent,
        query: DisasterQuery,
        *,
        now: datetime,
    ) -> ProviderBatch[SituationReport]:
        index_capture = build_snapshot_capture(
            self._snapshot_recorder,
            source_id=self.source_id,
            parameters={"document": "disaster-index-v1"},
            rights_id="fdma-public-information-terms-2026-08",
            retrieved_at=now,
        )
        markup = await get_text(
            self._client,
            FDMA_INDEX_URL,
            allowed_hosts=self.allowed_hosts,
            max_bytes=self._max_response_bytes,
            provider_name=self.provider_name,
            capture=index_capture,
        )
        parser = _IndexParser()
        try:
            parser.feed(markup)
        except Exception as error:
            raise DisasterProviderResponseError(
                "The FDMA disaster index could not be parsed.",
                reason_code="invalid_payload",
            ) from error
        entries = [
            _IndexEntry(
                title=" ".join(cells),
                url=urljoin(FDMA_INDEX_URL, href),
                event_date=_entry_event_date(cells, href),
                published_at=_date(" ".join(cells)),
                revision=_revision(" ".join(cells)),
            )
            for cells, href in parser.rows
            if href and cells
        ]
        matches = sorted(
            (entry for entry in entries if _entry_matches(entry, event, query)),
            key=lambda item: (item.revision, item.event_date or datetime.min),
            reverse=True,
        )
        if not matches:
            return ProviderBatch(
                issues=(
                    ProviderIssue(
                        self.provider_name,
                        f"{self.provider_name}: The provider returned no matching "
                        "records.",
                        reason_code="empty_result",
                    ),
                )
            )
        selected = matches[0]
        issues: list[ProviderIssue] = []
        report_capture = build_snapshot_capture(
            self._snapshot_recorder,
            source_id=self.source_id,
            parameters={"document": selected.url},
            rights_id="fdma-public-information-terms-2026-08",
            retrieved_at=now,
        )
        try:
            payload = await get_bytes(
                self._client,
                selected.url,
                allowed_hosts=self.allowed_hosts,
                max_bytes=self._max_response_bytes,
                provider_name=self.provider_name,
                capture=report_capture,
            )
            if payload.startswith(b"%PDF") or selected.url.lower().endswith(".pdf"):
                text = _extract_pdf_text(payload)
            else:
                text = sanitize_provider_text(
                    payload.decode("utf-8", errors="replace"), limit=12_000
                )
        except DisasterProviderError as error:
            failure = error.failure
            issues.append(
                ProviderIssue(
                    self.provider_name,
                    f"{self.provider_name}: The matched official report could not "
                    "be read.",
                    reason_code=failure.reason_code,
                    retryable=failure.retryable,
                    http_status=failure.http_status,
                    detail=failure.detail,
                )
            )
            return ProviderBatch(issues=tuple(issues))
        publication_date = selected.published_at or selected.event_date
        published_at = (
            publication_date.replace(tzinfo=JAPAN_TIMEZONE).astimezone(UTC)
            if publication_date is not None
            else None
        )
        source = SourceReference(
            source_id=self.source_id,
            publisher="Fire and Disaster Management Agency of Japan",
            title=selected.title,
            canonical_url=selected.url,
            published_at=published_at,
            updated_at=published_at,
            retrieved_at=now,
            authority=SourceAuthority.NATIONAL_AUTHORITY,
            snapshot_id=(
                report_capture.snapshot.snapshot_id
                if report_capture and report_capture.snapshot
                else None
            ),
        )
        report = SituationReport(
            source=source,
            narrative=(
                "FDMA published an official situation report matched to the selected "
                "event. Structured facts extracted from the document are listed "
                "separately; consult the linked source for the complete narrative "
                "and revision notes."
            ),
            facts=_extract_facts(text, source, event, published_at),
            reported_event_time=event.event_time,
            locations=(event.location,),
            countries=(query.country.canonical_name,),
            country_codes=(query.country.alpha3_code,),
            hazard=query.hazard,
            magnitude=event.magnitude,
            provider_event_ids=event.provider_ids,
        )
        return ProviderBatch(
            records=(
                SituationReport(
                    source=source,
                    narrative=report.narrative,
                    facts=report.facts,
                    event_id=None,
                    reported_event_time=report.reported_event_time,
                    locations=report.locations,
                    countries=report.countries,
                    country_codes=report.country_codes,
                    hazard=report.hazard,
                    magnitude=report.magnitude,
                    provider_event_ids=report.provider_event_ids,
                ),
            ),
            issues=tuple(issues),
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()
