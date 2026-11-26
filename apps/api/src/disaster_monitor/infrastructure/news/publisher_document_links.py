"""Turn publisher-owned report links into undated publisher retrieval leads."""

import ipaddress
import re
from hashlib import sha256
from urllib.parse import unquote, urldefrag, urljoin, urlsplit

from disaster_monitor.domain.news import NewsFeedItem
from disaster_monitor.infrastructure.news.public_documents import public_document_host

_FULL_REPORT = re.compile(
    r"\b(?:full report|complete report|rapport complet|informe completo)\b", re.I
)
_REPORT_LINK = re.compile(
    r"\b(?:full report|complete report|official report|situation report|"
    r"download (?:the )?report|report\s*\(pdf\)|"
    r"rapport complet|informe completo)(?!\w)",
    re.I,
)


def _is_public_host(host: str) -> bool:
    try:
        return ipaddress.ip_address(host).is_global
    except ValueError:
        return host.rstrip(".") != "localhost"


def publisher_document_leads(
    links: list[tuple[str, str]], *, page_url: str, publisher: str, page_title: str
) -> tuple[NewsFeedItem, ...]:
    leads = {}
    for href, label in sorted(links, key=lambda link: not _FULL_REPORT.search(link[1])):
        if not _REPORT_LINK.search(label):
            continue
        lead = publisher_pdf_lead(
            href, label, page_url=page_url, publisher=publisher, page_title=page_title
        )
        if lead is not None:
            leads.setdefault(lead.canonical_url, lead)
        if len(leads) == 2:
            break
    return tuple(leads.values())


def publisher_pdf_lead(
    href: str, label: str, *, page_url: str, publisher: str, page_title: str
) -> NewsFeedItem | None:
    try:
        url = urldefrag(urljoin(page_url, href))[0]
        host = public_document_host(url)
        pdf = unquote(urlsplit(url).path).lower().endswith(".pdf")
    except ValueError:
        return None
    if not host or not pdf or not _is_public_host(host) or url == page_url:
        return None
    return NewsFeedItem(
        external_id="publisher-document:" + sha256(url.encode()).hexdigest(),
        publisher=publisher if host == public_document_host(page_url) else host,
        title=label.strip()[:240] or "PDF attachment",
        canonical_url=url,
        published_at=None,
        updated_at=None,
        search_title=page_title.strip()[:300] or None,
        referring_document_url=page_url,
    )
