"""ASGI middleware enforcing strict HTTP request body size limits."""

import json
from typing import Callable
from starlette.datastructures import Headers
from starlette.responses import Response
from starlette.types import ASGIApp, Receive, Scope, Send

DEFAULT_MAX_REQUEST_BYTES = 524_288  # 512 KiB


class RequestSizeLimitMiddleware:
    """ASGI middleware that enforces a maximum request body size ceiling.
    
    Rejects requests whose Content-Length exceeds the limit immediately.
    For chunked streaming requests lacking Content-Length, tracks received bytes
    and aborts with HTTP 413 if the ceiling is breached.
    Handles client disconnects cleanly.
    """

    def __init__(self, app: ASGIApp, max_bytes: int = DEFAULT_MAX_REQUEST_BYTES):
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        content_length = headers.get("content-length")

        if content_length is not None:
            try:
                length = int(content_length)
                if length > self.max_bytes:
                    response = Response(
                        content=json.dumps(
                            {"detail": f"Request body exceeds maximum allowed size of {self.max_bytes} bytes."}
                        ),
                        status_code=413,
                        media_type="application/json",
                    )
                    await response(scope, receive, send)
                    return
            except ValueError:
                pass

        # For chunked bodies or undeclared content-length, track stream bytes
        received_bytes = 0
        response_sent = False

        async def limited_receive() -> dict:
            nonlocal received_bytes, response_sent
            message = await receive()
            msg_type = message.get("type")

            if msg_type == "http.disconnect":
                return message

            if msg_type == "http.request":
                body = message.get("body", b"")
                received_bytes += len(body)
                if received_bytes > self.max_bytes:
                    if not response_sent:
                        response_sent = True
                        response = Response(
                            content=json.dumps(
                                {"detail": f"Request body exceeds maximum allowed size of {self.max_bytes} bytes."}
                            ),
                            status_code=413,
                            media_type="application/json",
                        )
                        await response(scope, receive, send)
                    # Abort further streaming
                    return {"type": "http.disconnect"}

            return message

        try:
            await self.app(scope, limited_receive, send)
        except Exception:
            if not response_sent:
                raise
