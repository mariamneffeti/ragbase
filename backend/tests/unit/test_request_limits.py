import pytest

from app.core.request_limits import RequestBodyLimitMiddleware


@pytest.mark.asyncio
async def test_rejects_oversized_content_length_without_calling_app():
    called = False

    async def app(scope, receive, send):
        nonlocal called
        called = True

    messages = []

    async def send(message):
        messages.append(message)

    middleware = RequestBodyLimitMiddleware(app, max_body_bytes=4)
    await middleware(
        {"type": "http", "headers": [(b"content-length", b"5")]},
        lambda: None,
        send,
    )

    assert called is False
    assert messages[0]["status"] == 413


@pytest.mark.asyncio
async def test_rejects_oversized_streamed_body():
    async def app(scope, receive, send):
        while True:
            message = await receive()
            if not message.get("more_body"):
                break

    incoming = iter(
        [
            {"type": "http.request", "body": b"abc", "more_body": True},
            {"type": "http.request", "body": b"de", "more_body": False},
        ]
    )
    messages = []

    async def receive():
        return next(incoming)

    async def send(message):
        messages.append(message)

    middleware = RequestBodyLimitMiddleware(app, max_body_bytes=4)
    await middleware({"type": "http", "headers": []}, receive, send)

    assert messages[0]["status"] == 413


@pytest.mark.asyncio
async def test_accepts_body_at_limit():
    async def app(scope, receive, send):
        message = await receive()
        assert message["body"] == b"four"

    incoming = {"type": "http.request", "body": b"four", "more_body": False}

    async def receive():
        return incoming

    async def send(message):
        pass

    middleware = RequestBodyLimitMiddleware(app, max_body_bytes=4)
    await middleware({"type": "http", "headers": []}, receive, send)
