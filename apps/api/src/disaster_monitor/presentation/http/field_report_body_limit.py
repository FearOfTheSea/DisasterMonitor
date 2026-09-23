"""Bound memory spent parsing field-report uploads and imports."""

from __future__ import annotations

from starlette.types import ASGIApp, Message, Receive, Scope, Send

MAX_FIELD_REPORT_BODY_BYTES = 52 * 1024 * 1024
_LIMITED_PATHS = {"/api/v1/field-reports", "/api/v1/field-reports/imports"}


class FieldReportBodyLimitMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or scope["method"] != "POST"
            or scope["path"] not in _LIMITED_PATHS
        ):
            await self._app(scope, receive, send)
            return
        headers = dict(scope.get("headers", []))
        length = headers.get(b"content-length")
        if length is not None:
            try:
                if int(length) > MAX_FIELD_REPORT_BODY_BYTES:
                    await _reject(send)
                    return
            except ValueError:
                await _reject(send)
                return
        chunks: list[bytes] = []
        size = 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            size += len(chunk)
            if size > MAX_FIELD_REPORT_BODY_BYTES:
                await _reject(send)
                return
            chunks.append(chunk)
            if not message.get("more_body", False):
                break
        body = b"".join(chunks)
        delivered = False

        async def replay() -> Message:
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        await self._app(scope, replay, send)


async def _reject(send: Send) -> None:
    body = b'{"detail":"Field-report request body exceeds the 52 MiB limit."}'
    await send(
        {
            "type": "http.response.start",
            "status": 413,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})
