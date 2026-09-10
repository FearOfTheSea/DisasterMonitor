"""Policy values for controlled public-web news collection."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from urllib.parse import unquote, urlsplit

_SOURCE_ID = re.compile(r"^[a-z0-9][a-z0-9-]{2,79}$")


def _require_aware(name: str, value: datetime | None) -> None:
    if value is not None and (value.tzinfo is None or value.utcoffset() is None):
        raise ValueError(f"{name} must be timezone-aware.")


class WebAcquisitionMode(StrEnum):
    RSS_ATOM = "rss_atom"
    NEWS_SITEMAP = "news_sitemap"


class WebFetchOutcome(StrEnum):
    SUCCESS = "success"
    NOT_MODIFIED = "not_modified"
    POLICY_REJECTED = "policy_rejected"
    RATE_LIMITED = "rate_limited"
    UPSTREAM_ERROR = "upstream_error"
    PARSER_ERROR = "parser_error"


@dataclass(frozen=True, slots=True)
class ApprovedWebSource:
    """One explicitly reviewed and tightly bounded public-web source."""

    source_id: str
    publisher_name: str
    feed_url: str
    allowed_hosts: tuple[str, ...]
    allowed_path_prefixes: tuple[str, ...]
    acquisition_mode: WebAcquisitionMode
    user_agent: str
    contact_email: str
    robots_policy_url: str
    terms_url: str
    reviewed_at: datetime
    review_expires_at: datetime
    crawl_delay_seconds: int
    request_limit_per_run: int
    maximum_response_bytes: int
    enabled: bool = True
    kill_switch_reason: str | None = None

    def __post_init__(self) -> None:
        if not _SOURCE_ID.fullmatch(self.source_id):
            raise ValueError("Web source IDs require a stable lowercase slug.")
        if not self.publisher_name.strip():
            raise ValueError("Web sources require a publisher name for attribution.")
        if not self.allowed_hosts:
            raise ValueError("Web sources require at least one allowed host.")
        normalized_hosts = tuple(
            host.casefold().rstrip(".") for host in self.allowed_hosts
        )
        if any(not host or ":" in host or "/" in host for host in normalized_hosts):
            raise ValueError("Web source allowed hosts must be DNS names.")
        object.__setattr__(self, "allowed_hosts", normalized_hosts)
        if not self.allowed_path_prefixes or any(
            not prefix.startswith("/") for prefix in self.allowed_path_prefixes
        ):
            raise ValueError("Web sources require absolute allowed path prefixes.")
        if not self.user_agent.strip() or not self.contact_email.strip():
            raise ValueError("Web sources require a contact-bearing user agent.")
        if self.contact_email.casefold() not in self.user_agent.casefold():
            raise ValueError("The web source contact must appear in the user agent.")
        for name, value in (
            ("reviewed_at", self.reviewed_at),
            ("review_expires_at", self.review_expires_at),
        ):
            _require_aware(name, value)
        if self.review_expires_at <= self.reviewed_at:
            raise ValueError("Web source review expiry must follow its review date.")
        if not 0 <= self.crawl_delay_seconds <= 86_400:
            raise ValueError("Web source crawl delay is outside the supported bound.")
        if not 1 <= self.request_limit_per_run <= 10:
            raise ValueError("Web source request limit must be between 1 and 10.")
        if not 10_000 <= self.maximum_response_bytes <= 5_000_000:
            raise ValueError(
                "Web source response limit is outside the supported bound."
            )
        if self.kill_switch_reason is not None and not self.kill_switch_reason.strip():
            raise ValueError("A configured kill switch requires a reason.")
        for name, url in (
            ("feed", self.feed_url),
            ("robots policy", self.robots_policy_url),
            ("terms", self.terms_url),
        ):
            if not _is_https_url(url):
                raise ValueError(f"Web source {name} requires an HTTPS URL.")
        if not self.allows_url(self.feed_url):
            raise ValueError("Web source feed URL is outside its allowed host or path.")

    def is_admitted(self, now: datetime) -> bool:
        _require_aware("admission time", now)
        return (
            self.enabled
            and self.kill_switch_reason is None
            and self.reviewed_at <= now < self.review_expires_at
        )

    def allows_url(self, url: str) -> bool:
        try:
            parsed = urlsplit(url)
            port = parsed.port
        except ValueError:
            return False
        host = (parsed.hostname or "").casefold().rstrip(".")
        decoded_path = unquote(parsed.path)
        path_segments = decoded_path.split("/")
        return (
            parsed.scheme == "https"
            and parsed.username is None
            and parsed.password is None
            and port in {None, 443}
            and host in self.allowed_hosts
            and "\\" not in decoded_path
            and not any(segment in {".", ".."} for segment in path_segments)
            and any(
                decoded_path.startswith(prefix) for prefix in self.allowed_path_prefixes
            )
            and not parsed.fragment
        )


@dataclass(frozen=True, slots=True)
class WebFetchState:
    source_id: str
    etag: str | None = None
    last_modified: str | None = None
    last_attempt_at: datetime | None = None
    last_success_at: datetime | None = None
    consecutive_failures: int = 0
    circuit_open_until: datetime | None = None

    def __post_init__(self) -> None:
        if not self.source_id.strip() or self.consecutive_failures < 0:
            raise ValueError(
                "Web fetch state requires valid source identity and counts."
            )
        for name, value in (
            ("last_attempt_at", self.last_attempt_at),
            ("last_success_at", self.last_success_at),
            ("circuit_open_until", self.circuit_open_until),
        ):
            _require_aware(name, value)


@dataclass(frozen=True, slots=True)
class WebFetchAudit:
    audit_id: str
    source_id: str
    requested_url: str
    attempted_at: datetime
    outcome: WebFetchOutcome
    status_code: int | None
    bytes_received: int
    response_sha256: str | None
    error_code: str | None = None

    def __post_init__(self) -> None:
        if not self.audit_id.strip() or not self.source_id.strip():
            raise ValueError("Web fetch audits require stable identity.")
        _require_aware("attempted_at", self.attempted_at)
        if self.bytes_received < 0:
            raise ValueError("Web fetch audit bytes cannot be negative.")


def _is_https_url(url: str) -> bool:
    try:
        parsed = urlsplit(url)
        return (
            parsed.scheme == "https"
            and bool(parsed.hostname)
            and parsed.username is None
            and parsed.password is None
            and parsed.port in {None, 443}
        )
    except ValueError:
        return False
