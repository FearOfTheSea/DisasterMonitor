"""Shared, bounded CDSE client-credentials access for catalog and rendering."""

import asyncio
from time import monotonic
from urllib.parse import urlsplit

import httpx

DEFAULT_TOKEN_URL = (
    "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/"
    "protocol/openid-connect/token"
)


class CDSEAuthenticationError(Exception):
    def __init__(self, message: str, reason_code: str, retryable: bool) -> None:
        super().__init__(message)
        self.reason_code = reason_code
        self.retryable = retryable


class CDSEClientCredentials:
    """Keep credentials server-side and share concurrent token renewal."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        client_id: str | None,
        client_secret: str | None,
        token_url: str = DEFAULT_TOKEN_URL,
    ):
        parsed = urlsplit(token_url)
        if (
            parsed.scheme != "https"
            or parsed.hostname != "identity.dataspace.copernicus.eu"
            or parsed.port not in (None, 443)
            or parsed.username
            or parsed.password
            or parsed.fragment
            or parsed.query
            or parsed.path != "/auth/realms/CDSE/protocol/openid-connect/token"
        ):
            raise ValueError(
                "CDSE authentication requires its registered token endpoint."
            )
        self._client = client
        self._client_id = (client_id or "").strip()
        self._client_secret = (client_secret or "").strip()
        self._url = token_url
        self._value = ""
        self._expires_at = 0.0
        self._lock = asyncio.Lock()

    @property
    def available(self) -> bool:
        return bool(self._client_id and self._client_secret)

    async def access_token(self, *, force_refresh: bool = False) -> str:
        async with self._lock:
            if (
                not force_refresh
                and self._value
                and self._expires_at > monotonic() + 30
            ):
                return self._value
            if not self.available:
                raise CDSEAuthenticationError(
                    "CDSE credentials are not configured.",
                    "credentials_required",
                    False,
                )
            try:
                response = await self._client.post(
                    self._url,
                    data={
                        "grant_type": "client_credentials",
                        "client_id": self._client_id,
                        "client_secret": self._client_secret,
                    },
                    headers={"Accept": "application/json"},
                    follow_redirects=False,
                )
            except httpx.HTTPError as error:
                raise CDSEAuthenticationError(
                    "The CDSE token request failed.", "credentials_unavailable", True
                ) from error
            if response.status_code >= 300:
                raise CDSEAuthenticationError(
                    "The CDSE token endpoint rejected the configured credentials.",
                    "credentials_required"
                    if response.status_code in {401, 403}
                    else "token_http_error",
                    response.status_code >= 500,
                )
            try:
                document = response.json()
                value = document["access_token"]
                expires = int(document.get("expires_in", 300))
            except (ValueError, KeyError, TypeError, OverflowError) as error:
                raise CDSEAuthenticationError(
                    "The CDSE token response has an unsupported schema.",
                    "token_schema_invalid",
                    False,
                ) from error
            if not isinstance(value, str) or not value.strip():
                raise CDSEAuthenticationError(
                    "The CDSE token response did not contain a usable token.",
                    "credentials_required",
                    False,
                )
            self._value = value.strip()
            self._expires_at = monotonic() + max(1, expires)
            return self._value
