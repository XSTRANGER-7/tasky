"""Email providers: SMTP against a real in-process SMTP server, the HTTPS APIs against a
mock transport, and provider selection."""

from __future__ import annotations

import json
import socket
from email import message_from_bytes
from email.message import Message

import httpx
import pytest
from aiosmtpd.controller import Controller

from app.core.config import Settings
from app.notifications.senders import (
    BrevoSender,
    ConsoleSender,
    Email,
    ResendSender,
    SendError,
    SmtpSender,
    build_sender,
)

EMAIL = Email(
    to="jonas@demo.io", subject="[INC-1] Test", text="plain body", html="<p>html body</p>"
)


class _Sink:
    def __init__(self) -> None:
        self.messages: list[Message] = []

    async def handle_DATA(self, server: object, session: object, envelope: object) -> str:
        self.messages.append(message_from_bytes(envelope.content))  # type: ignore[attr-defined]
        return "250 OK"


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture
def smtp_server():  # type: ignore[no-untyped-def]
    sink = _Sink()
    # A concrete port: aiosmtpd probes readiness by connecting, which fails for port 0.
    port = _free_port()
    controller = Controller(sink, hostname="127.0.0.1", port=port)
    controller.start()
    try:
        yield port, sink
    finally:
        controller.stop()


async def test_smtp_sends_multipart_mail(smtp_server, settings: Settings) -> None:  # type: ignore[no-untyped-def]
    port, sink = smtp_server
    sender = SmtpSender(settings.model_copy(update={"smtp_host": "127.0.0.1", "smtp_port": port}))

    await sender.send(EMAIL)

    (msg,) = sink.messages
    assert msg["To"] == "jonas@demo.io"
    assert msg["Subject"] == "[INC-1] Test"
    # Without these, real mail servers score the message as likely spam.
    assert msg["Date"]
    assert msg["Message-ID"].startswith("<") and msg["Message-ID"].endswith(">")
    parts = {
        p.get_content_type(): p.get_payload(decode=True).decode()
        for p in msg.walk()
        if not p.is_multipart()
    }
    assert parts["text/plain"].strip() == "plain body"
    assert parts["text/html"].strip() == "<p>html body</p>"


async def test_smtp_connection_failure_is_a_send_error(settings: Settings) -> None:
    sender = SmtpSender(
        settings.model_copy(
            update={"smtp_host": "127.0.0.1", "smtp_port": 1, "email_timeout_seconds": 1}
        )
    )

    with pytest.raises(SendError, match="smtp"):
        await sender.send(EMAIL)


def _client(status: int, seen: list[httpx.Request]) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            status, json={"messageId": "abc"} if status < 300 else {"message": "nope"}
        )

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_brevo_payload(settings: Settings) -> None:
    seen: list[httpx.Request] = []
    s = settings.model_copy(
        update={"brevo_api_key": "k-123", "email_from": "Incident Desk <desk@demo.io>"}
    )

    await BrevoSender(s, client=_client(201, seen)).send(EMAIL)

    (req,) = seen
    assert str(req.url) == "https://api.brevo.com/v3/smtp/email"
    assert req.headers["api-key"] == "k-123"
    body = json.loads(req.content)
    assert body["sender"] == {"name": "Incident Desk", "email": "desk@demo.io"}
    assert body["to"] == [{"email": "jonas@demo.io"}]
    assert (body["subject"], body["textContent"], body["htmlContent"]) == (
        "[INC-1] Test",
        "plain body",
        "<p>html body</p>",
    )


async def test_resend_payload(settings: Settings) -> None:
    seen: list[httpx.Request] = []

    await ResendSender(
        settings.model_copy(update={"resend_api_key": "re_1"}), client=_client(200, seen)
    ).send(EMAIL)

    (req,) = seen
    assert req.headers["authorization"] == "Bearer re_1"
    assert json.loads(req.content)["to"] == ["jonas@demo.io"]


async def test_http_error_status_is_a_send_error(settings: Settings) -> None:
    with pytest.raises(SendError, match="HTTP 401"):
        await BrevoSender(settings, client=_client(401, [])).send(EMAIL)


async def test_network_error_is_a_send_error(settings: Settings) -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route", request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(boom))
    with pytest.raises(SendError, match="ConnectError"):
        await ResendSender(settings, client=client).send(EMAIL)


@pytest.mark.parametrize(
    ("provider", "cls"),
    [
        ("smtp", SmtpSender),
        ("brevo", BrevoSender),
        ("resend", ResendSender),
        ("console", ConsoleSender),
    ],
)
def test_build_sender(settings: Settings, provider: str, cls: type) -> None:
    assert isinstance(build_sender(settings.model_copy(update={"email_provider": provider})), cls)


async def test_console_sender_never_fails() -> None:
    await ConsoleSender().send(EMAIL)
