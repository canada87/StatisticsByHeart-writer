"""Pure-ASGI body guard: gzip request decoding + size cap (on the decompressed size)."""

from __future__ import annotations

import zlib

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.errors import error_response


class _TooLargeError(Exception):
    pass


class _BadBodyError(Exception):
    pass


class BodyGuardMiddleware:
    def __init__(self, app: ASGIApp, max_body_bytes: int) -> None:
        self.app = app
        self.max_body_bytes = max_body_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] in ("GET", "HEAD", "OPTIONS", "DELETE"):
            await self.app(scope, receive, send)
            return

        headers = {k.lower(): v for k, v in scope["headers"]}
        encoding = headers.get(b"content-encoding", b"").decode().strip().lower()
        if encoding not in ("", "identity", "gzip"):
            await error_response(415, "unsupported_encoding", "Only gzip is supported")(
                scope, receive, send
            )
            return

        declared = headers.get(b"content-length")
        if (
            declared
            and encoding != "gzip"
            and declared.isdigit()
            and int(declared) > self.max_body_bytes
        ):
            await error_response(413, "body_too_large", "Body too large")(scope, receive, send)
            return

        try:
            body = await self._read_body(receive, gzip=encoding == "gzip")
        except _TooLargeError:
            await error_response(413, "body_too_large", "Body too large")(scope, receive, send)
            return
        except _BadBodyError:
            await error_response(400, "invalid_body", "Corrupt gzip body")(scope, receive, send)
            return

        new_headers = [
            (k, v)
            for k, v in scope["headers"]
            if k.lower() not in (b"content-encoding", b"content-length")
        ]
        new_headers.append((b"content-length", str(len(body)).encode()))
        scope = {**scope, "headers": new_headers}

        sent = False

        async def replay() -> Message:
            nonlocal sent
            if not sent:
                sent = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()  # client disconnect

        await self.app(scope, replay, send)

    async def _read_body(self, receive: Receive, *, gzip: bool) -> bytes:
        decomp = zlib.decompressobj(wbits=31) if gzip else None
        chunks: list[bytes] = []
        total = 0
        while True:
            message = await receive()
            if message["type"] != "http.request":
                break
            chunk: bytes = message.get("body", b"")
            if decomp is not None and chunk:
                try:
                    chunk = decomp.decompress(chunk, self.max_body_bytes - total + 1)
                except zlib.error as exc:
                    raise _BadBodyError from exc
                if decomp.unconsumed_tail:
                    raise _TooLargeError
            total += len(chunk)
            if total > self.max_body_bytes:
                raise _TooLargeError
            chunks.append(chunk)
            if not message.get("more_body", False):
                break
        if decomp is not None:
            try:
                tail = decomp.flush()
            except zlib.error as exc:
                raise _BadBodyError from exc
            if not decomp.eof:
                raise _BadBodyError
            total += len(tail)
            if total > self.max_body_bytes:
                raise _TooLargeError
            chunks.append(tail)
        return b"".join(chunks)
