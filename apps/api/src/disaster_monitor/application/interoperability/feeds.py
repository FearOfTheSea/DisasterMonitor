"""Local Atom feed projection for immutable Incident Watch findings."""

from __future__ import annotations

from datetime import UTC, datetime
from xml.etree.ElementTree import Element, SubElement, tostring

from disaster_monitor.domain.disaster import IncidentWatchChange

_ATOM = "http://www.w3.org/2005/Atom"


def export_watch_atom(
    watch_id: str,
    changes: tuple[IncidentWatchChange, ...],
    *,
    base_url: str,
) -> str:
    if not watch_id.strip() or not base_url.startswith(("http://", "https://")):
        raise ValueError("Atom feeds require a watch identity and HTTP base URL.")
    feed = Element("feed", xmlns=_ATOM)
    SubElement(feed, "id").text = f"urn:disaster-monitor:watch:{watch_id}"
    SubElement(feed, "title").text = f"DisasterMonitor Incident Watch {watch_id}"
    updated = max((item.created_at for item in changes), default=None)
    if updated is not None:
        SubElement(feed, "updated").text = _utc(updated)
    SubElement(
        feed,
        "link",
        rel="self",
        href=f"{base_url.rstrip('/')}/api/v1/incident-watches/{watch_id}/feed.atom",
    )
    for change in sorted(
        changes, key=lambda item: (item.created_at, item.change_id), reverse=True
    ):
        entry = SubElement(feed, "entry")
        SubElement(
            entry, "id"
        ).text = f"urn:disaster-monitor:finding:{change.change_id}"
        SubElement(entry, "title").text = change.summary
        SubElement(entry, "updated").text = _utc(change.created_at)
        SubElement(entry, "content", type="text").text = change.detail
        SubElement(entry, "category", term=change.kind.value)
    return '<?xml version="1.0" encoding="utf-8"?>' + tostring(
        feed, encoding="unicode", short_empty_elements=True
    )


def _utc(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


__all__ = ["export_watch_atom"]
