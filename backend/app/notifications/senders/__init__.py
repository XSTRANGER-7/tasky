"""Email providers behind one interface (spec 9.6), chosen by EMAIL_PROVIDER.

Production uses an HTTPS API (Brevo / Resend): AWS blocks outbound port 25 on EC2 by
default and many hosts block SMTP entirely, so HTTPS needs no port changes. SMTP covers Mailpit
in development and real mailboxes (Gmail, Outlook, any provider) on 587 STARTTLS or 465 SSL;
``console`` only logs. Test doubles live in ``tests/fakes.py``, not here.
"""

from __future__ import annotations

import asyncio
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formatdate, make_msgid, parseaddr
from typing import Protocol

import httpx

from app.core.config import Settings
from app.core.logging import get_logger

log = get_logger(__name__)


class SendError(Exception):
    """Delivery failed; the worker records the message and retries with backoff."""


@dataclass(frozen=True)
class Email:
    to: str
    subject: str
    text: str
    html: str


class EmailSender(Protocol):
    name: str

    async def send(self, email: Email) -> None: ...


def _from(settings: Settings) -> tuple[str, str]:
    name, address = parseaddr(settings.email_from)
    return name or "Tasky", address


class SmtpSender:
    name = "smtp"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def _send_sync(self, email: Email) -> None:
        s = self.settings
        msg = EmailMessage()
        msg["From"] = s.email_from
        msg["To"] = email.to
        msg["Subject"] = email.subject
        # Real mail servers score messages without these as likely spam.
        msg["Date"] = formatdate(localtime=False)
        msg["Message-ID"] = make_msgid(domain=_from(s)[1].partition("@")[2] or None)
        msg.set_content(email.text)
        msg.add_alternative(email.html, subtype="html")
        context = ssl.create_default_context()
        # 465 = TLS from the first byte (SMTP_SSL); 587 = plain, then STARTTLS; 1025 = Mailpit.
        smtp: smtplib.SMTP = (
            smtplib.SMTP_SSL(
                s.smtp_host, s.smtp_port, timeout=s.email_timeout_seconds, context=context
            )
            if s.smtp_ssl
            else smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=s.email_timeout_seconds)
        )
        with smtp:
            if s.smtp_starttls and not s.smtp_ssl:
                smtp.starttls(context=context)
            if s.smtp_username and s.smtp_password:
                smtp.login(s.smtp_username, s.smtp_password)
            smtp.send_message(msg)

    async def send(self, email: Email) -> None:
        try:
            await asyncio.to_thread(self._send_sync, email)
        except (OSError, smtplib.SMTPException) as exc:
            raise SendError(f"smtp: {exc}") from exc


class _HttpSender:
    name = "http"

    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        self.settings = settings
        self._client = client

    async def _post(self, url: str, headers: dict[str, str], payload: dict[str, object]) -> None:
        client = self._client or httpx.AsyncClient(timeout=self.settings.email_timeout_seconds)
        try:
            res = await client.post(url, headers=headers, json=payload)
        except httpx.HTTPError as exc:
            raise SendError(f"{self.name}: {type(exc).__name__}: {exc}") from exc
        finally:
            if self._client is None:
                await client.aclose()
        if res.status_code >= 300:
            raise SendError(f"{self.name}: HTTP {res.status_code}: {res.text[:200]}")


class BrevoSender(_HttpSender):
    name = "brevo"
    URL = "https://api.brevo.com/v3/smtp/email"

    async def send(self, email: Email) -> None:
        sender_name, sender_email = _from(self.settings)
        await self._post(
            self.URL,
            {"api-key": self.settings.brevo_api_key or "", "accept": "application/json"},
            {
                "sender": {"name": sender_name, "email": sender_email},
                "to": [{"email": email.to}],
                "subject": email.subject,
                "htmlContent": email.html,
                "textContent": email.text,
            },
        )


class ResendSender(_HttpSender):
    name = "resend"
    URL = "https://api.resend.com/emails"

    async def send(self, email: Email) -> None:
        await self._post(
            self.URL,
            {"Authorization": f"Bearer {self.settings.resend_api_key or ''}"},
            {
                "from": self.settings.email_from,
                "to": [email.to],
                "subject": email.subject,
                "html": email.html,
                "text": email.text,
            },
        )


class ConsoleSender:
    """Logs the email instead of sending it. Safe default when nothing is configured."""

    name = "console"

    async def send(self, email: Email) -> None:
        log.info("email_console", to=email.to, subject=email.subject, preview=email.text[:160])


def build_sender(settings: Settings) -> EmailSender:
    if settings.email_provider == "smtp":
        return SmtpSender(settings)
    if settings.email_provider == "brevo":
        return BrevoSender(settings)
    if settings.email_provider == "resend":
        return ResendSender(settings)
    return ConsoleSender()
