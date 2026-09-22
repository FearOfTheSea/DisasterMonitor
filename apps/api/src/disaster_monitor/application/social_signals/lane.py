"""Optional open-feed lane that emits untrusted discovery candidates."""

from datetime import datetime
from hashlib import sha256

from disaster_monitor.application.ports.news import BreakingNewsFeed
from disaster_monitor.domain.social_signals import (
    SignalSourceTerms,
    UntrustedSocialSignal,
)


class OpenSocialSignalLane:
    def __init__(self, feed: BreakingNewsFeed, source_terms: SignalSourceTerms) -> None:
        if feed.source_id != source_terms.source_id:
            raise ValueError("Open signal feed identity must match reviewed terms.")
        self._feed = feed
        self._source_terms = source_terms

    async def fetch_since(
        self, *, since: datetime, now: datetime
    ) -> tuple[UntrustedSocialSignal, ...]:
        items = await self._feed.fetch_since(since=since, now=now)
        return tuple(
            UntrustedSocialSignal(
                signal_id=(
                    "social-signal:"
                    + sha256(
                        f"{self._feed.source_id}|{item.external_id}".encode()
                    ).hexdigest()[:24]
                ),
                source_id=self._feed.source_id,
                external_id=item.external_id,
                text=item.title,
                canonical_url=item.canonical_url,
                published_at=item.published_at,
                retrieved_at=now,
                source_terms=self._source_terms,
            )
            for item in items
        )


__all__ = ["OpenSocialSignalLane"]
