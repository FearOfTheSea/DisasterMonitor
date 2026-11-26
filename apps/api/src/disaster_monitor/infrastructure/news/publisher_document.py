"""Build discovery evidence from the same publisher representation in both feeds."""

import re
from datetime import datetime

from disaster_monitor.domain.discovery import DiscoveryArticle
from disaster_monitor.domain.evidence_types import SourceReference
from disaster_monitor.domain.news import NewsFeedItem
from disaster_monitor.infrastructure.news.discovery_parser import (
    _publication_date,
    parse_discovery_article,
)
from disaster_monitor.infrastructure.news.public_documents import (
    PublicDocument,
    PublicPdfDocument,
)
from disaster_monitor.infrastructure.news.publisher_pdf import extract_publisher_pdf

PublisherDocument = str | PublicDocument | PublicPdfDocument
_PUBLICATION_LINE = re.compile(
    r"^[ \t]*(?:(?:published|dref published|publication date|publishing date)"
    r"[ \t]*:[ \t]*(?:\r?\n[ \t]*)?|published(?:[ \t]+on)?[ \t]+)"
    r"([^\r\n]{1,64})$",
    re.I | re.M,
)


def _pdf_publication(imprint: str) -> tuple[datetime | None, bool]:
    # PDF creation, modification and transport dates do not attest publication.
    statements = {match.strip() for match in _PUBLICATION_LINE.findall(imprint)}
    if len(statements) != 1:
        return None, False
    (value,) = statements
    if re.fullmatch(r"\d{1,2} [A-Za-z]+ \d{4}", value):
        try:
            value = datetime.strptime(value, "%d %B %Y").date().isoformat()
        except ValueError:
            return None, False
    return _publication_date(value)


async def parse_publisher_document(
    document: PublisherDocument, lead: NewsFeedItem, *, retrieved_at: datetime
) -> DiscoveryArticle:
    if isinstance(document, PublicPdfDocument):
        pdf = await extract_publisher_pdf(document.body)
        if not pdf.text:
            raise ValueError("Publisher PDF contains no readable text.")
        publication, day = _pdf_publication(pdf.imprint)
        return DiscoveryArticle(
            source=SourceReference(
                source_id="open-news",
                publisher=lead.publisher,
                title=pdf.title or lead.title,
                canonical_url=lead.canonical_url,
                published_at=publication,
                updated_at=None,
                retrieved_at=retrieved_at,
                publication_precision=(
                    "day" if day else "exact" if publication else "unknown"
                ),
            ),
            text=pdf.text,
            indexed_at=lead.indexed_at,
            original_url=document.url if document.url != lead.canonical_url else None,
        )
    return parse_discovery_article(
        document.html if isinstance(document, PublicDocument) else document,
        document_url=document.url if isinstance(document, PublicDocument) else None,
        url=lead.canonical_url,
        title=lead.title,
        publisher=lead.publisher,
        retrieved_at=retrieved_at,
        indexed_at=lead.indexed_at,
    )
