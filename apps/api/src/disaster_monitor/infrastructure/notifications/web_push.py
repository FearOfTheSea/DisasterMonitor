"""Browser Web Push payload boundary with deterministic finding text."""

import json
import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

from disaster_monitor.domain.spatial_watches import WatchFinding


@dataclass(frozen=True, slots=True)
class BrowserPushSubscription:
    endpoint: str
    public_key: str
    auth_secret: str

    def __post_init__(self) -> None:
        if not self.endpoint.startswith("https://"):
            raise ValueError("Web Push endpoints must use HTTPS.")
        if not self.public_key or not self.auth_secret:
            raise ValueError("Web Push subscription keys are required.")


@dataclass(frozen=True, slots=True)
class VapidApplicationState:
    subject: str
    public_key: str
    private_key: str

    def __post_init__(self) -> None:
        if not self.subject.startswith(("mailto:", "https://")):
            raise ValueError("VAPID subject must be a mailto or HTTPS URI.")
        if not self.public_key or not self.private_key:
            raise ValueError("VAPID application keys are required.")


class LocalWebPushStateStore:
    """Persist VAPID application and browser subscriptions on the local host."""

    _SCHEMA_VERSION = "web-push.v1"

    def __init__(self, path: Path) -> None:
        if path.name in {"", ".", ".."}:
            raise ValueError("Web Push state requires a concrete file path.")
        path.parent.mkdir(parents=True, exist_ok=True)
        self._path = path

    def initialize(self, application: VapidApplicationState) -> None:
        document = self._read()
        existing = document.get("application")
        serialized = {
            "subject": application.subject,
            "public_key": application.public_key,
            "private_key": application.private_key,
        }
        if existing is not None and existing != serialized:
            raise ValueError("VAPID application state is already initialized.")
        document["application"] = serialized
        self._write(document)

    def application(self) -> VapidApplicationState | None:
        value = self._read().get("application")
        if value is None:
            return None
        if not isinstance(value, dict):
            raise ValueError("Stored VAPID application state is invalid.")
        return VapidApplicationState(
            subject=str(value.get("subject", "")),
            public_key=str(value.get("public_key", "")),
            private_key=str(value.get("private_key", "")),
        )

    def save_subscription(
        self, subscription_id: str, subscription: BrowserPushSubscription
    ) -> None:
        if not subscription_id.strip():
            raise ValueError("Web Push subscription identity is required.")
        document = self._read()
        subscriptions = self._subscription_documents(document)
        subscriptions[subscription_id] = {
            "endpoint": subscription.endpoint,
            "public_key": subscription.public_key,
            "auth_secret": subscription.auth_secret,
        }
        document["subscriptions"] = {
            key: subscriptions[key] for key in sorted(subscriptions)
        }
        self._write(document)

    def subscriptions(self) -> tuple[tuple[str, BrowserPushSubscription], ...]:
        values = self._subscription_documents(self._read())
        return tuple(
            (
                key,
                BrowserPushSubscription(
                    endpoint=str(value.get("endpoint", "")),
                    public_key=str(value.get("public_key", "")),
                    auth_secret=str(value.get("auth_secret", "")),
                ),
            )
            for key, value in sorted(values.items())
        )

    def delete_subscription(self, subscription_id: str) -> bool:
        document = self._read()
        subscriptions = self._subscription_documents(document)
        if subscription_id not in subscriptions:
            return False
        del subscriptions[subscription_id]
        document["subscriptions"] = subscriptions
        self._write(document)
        return True

    def _read(self) -> dict[str, object]:
        if not self._path.exists():
            return {
                "schema_version": self._SCHEMA_VERSION,
                "application": None,
                "subscriptions": {},
            }
        value = json.loads(self._path.read_text(encoding="utf-8"))
        if (
            not isinstance(value, dict)
            or value.get("schema_version") != self._SCHEMA_VERSION
        ):
            raise ValueError("Stored Web Push state has an unsupported schema.")
        return value

    @staticmethod
    def _subscription_documents(
        document: dict[str, object],
    ) -> dict[str, dict[str, object]]:
        raw = document.get("subscriptions")
        if not isinstance(raw, dict) or any(
            not isinstance(key, str) or not isinstance(value, dict)
            for key, value in raw.items()
        ):
            raise ValueError("Stored Web Push subscriptions are invalid.")
        return raw

    def _write(self, document: dict[str, object]) -> None:
        temporary = self._path.with_suffix(f"{self._path.suffix}.partial")
        temporary.write_text(
            json.dumps(document, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )
        temporary.chmod(0o600)
        os.replace(temporary, self._path)
        self._path.chmod(0o600)


PushSender = Callable[[str, bytes, str, str], Awaitable[None]]


class BrowserPushDelivery:
    def __init__(self, *, sender: PushSender) -> None:
        self._sender = sender

    async def deliver(
        self, subscription: BrowserPushSubscription, finding: WatchFinding
    ) -> None:
        payload = json.dumps(
            {
                "title": "DisasterMonitor watch finding",
                "body": finding.summary,
                "finding_id": finding.finding_id,
                "watch_id": finding.watch_id,
                "source_id": finding.source_id,
                "created_at": finding.created_at.isoformat(),
            },
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
        await self._sender(
            subscription.endpoint,
            payload,
            subscription.public_key,
            subscription.auth_secret,
        )
