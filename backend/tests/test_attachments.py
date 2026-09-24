"""Attachments (spec 13 + 16): allow-list by content, 10 MB cap, random keys, signed
short-lived downloads, never executed, uploader/admin deletes, audit trail."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from app.core.config import Settings
from app.services.attachment_service import UnsupportedType, clean_filename, sniff
from app.storage import LocalStorage, S3Storage, content_disposition
from app.storage.sigv4 import presign_url
from tests.conftest import BuildApp, CreateIncident, Person

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
PDF = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n1 0 obj\n"


# ---------------------------------------------------------------- pure


@pytest.mark.parametrize(
    ("name", "data", "expected"),
    [
        ("shot.png", PNG, "image/png"),
        ("renamed.txt", PNG, "image/png"),  # content wins over the extension
        ("photo.jpg", b"\xff\xd8\xff\xe0rest", "image/jpeg"),
        ("anim.gif", b"GIF89a....", "image/gif"),
        ("report.pdf", PDF, "application/pdf"),
        ("app.log", b"2026-09-22 ERROR pool exhausted\n", "text/plain"),
        ("dump.json", b'{"ok": true}', "application/json"),
    ],
)
def test_sniff_accepts_the_allow_list(name: str, data: bytes, expected: str) -> None:
    assert sniff(name, data) == expected


@pytest.mark.parametrize(
    ("name", "data"),
    [
        ("evil.html", b"<html><script>alert(1)</script>"),
        ("image.svg", b"<svg onload=alert(1)>"),
        ("setup.exe", b"MZ\x90\x00"),
        ("notes.txt", b"binary\x00inside"),
        ("latin1.log", "caf\xe9".encode("latin-1")),
        ("broken.json", b"{not json"),
        ("fake.png", b"<?php system($_GET[c]); ?>"),  # extension alone proves nothing
    ],
)
def test_sniff_refuses_everything_else(name: str, data: bytes) -> None:
    with pytest.raises(UnsupportedType):
        sniff(name, data)


@pytest.mark.parametrize(
    ("raw", "clean"),
    [
        ("../../etc/passwd", "passwd"),
        ("C:\\Users\\x\\report.pdf", "report.pdf"),
        ('we"ird\nname.txt', "we_ird_name.txt"),
        ("...", "file"),
    ],
)
def test_filenames_are_display_only(raw: str, clean: str) -> None:
    assert clean_filename(raw) == clean


def test_sigv4_matches_the_aws_documentation_example() -> None:
    # "Authenticating Requests: Using Query Parameters (AWS Signature Version 4)".
    url = presign_url(
        method="GET",
        url="https://examplebucket.s3.amazonaws.com/test.txt",
        access_key="AKIAIOSFODNN7EXAMPLE",
        secret_key="wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
        region="us-east-1",
        expires=86400,
        now=datetime(2013, 5, 24, tzinfo=UTC),
    )
    assert url.endswith(
        "X-Amz-Signature=aeeed9bbccd4d02ee5c0109b86d86835f995330da4c265957d157751f604d404"
    )


async def test_s3_backend_signs_puts_and_presigns_downloads(settings: Settings) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200)

    s3_settings = settings.model_copy(
        update={
            "storage_backend": "s3",
            "s3_endpoint": "https://abc.supabase.co/storage/v1/s3",
            "s3_bucket": "attachments",
            "s3_access_key": "key",
            "s3_secret_key": "secret",
        }
    )
    storage = S3Storage(
        s3_settings, client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )
    await storage.put("incidents/1/abc", b"hello", "text/plain")

    (req,) = seen
    assert req.method == "PUT"
    assert str(req.url) == "https://abc.supabase.co/storage/v1/s3/attachments/incidents/1/abc"
    assert req.headers["authorization"].startswith("AWS4-HMAC-SHA256 Credential=key/")
    assert "content-type;host;x-amz-content-sha256;x-amz-date" in req.headers["authorization"]

    link = storage.download_url(
        "incidents/1/abc", filename="a.txt", content_type="text/plain", inline=False
    )
    query = parse_qs(urlsplit(link).query)
    assert query["X-Amz-Expires"] == [str(s3_settings.download_url_seconds)]
    assert query["response-content-disposition"][0].startswith("attachment;")
    assert "X-Amz-Signature" in query


def test_local_links_expire_and_cannot_be_tampered_with(settings: Settings) -> None:
    storage = LocalStorage(settings)
    link = storage.download_url(
        "incidents/1/k", filename="a.png", content_type="image/png", inline=True
    )
    q = {k: v[0] for k, v in parse_qs(urlsplit(link).query).items()}
    assert storage.verify(q["key"], int(q["exp"]), q["cd"], q["ct"], q["sig"])
    # Changing anything breaks the signature: another file, another type, a later expiry.
    assert not storage.verify("incidents/1/other", int(q["exp"]), q["cd"], q["ct"], q["sig"])
    assert not storage.verify(q["key"], int(q["exp"]), q["cd"], "text/html", q["sig"])
    assert not storage.verify(q["key"], int(q["exp"]) + 999, q["cd"], q["ct"], q["sig"])
    assert not storage.verify(q["key"], int(time.time()) - 1, q["cd"], q["ct"], q["sig"])


def test_content_disposition_is_header_safe() -> None:
    value = content_disposition('résumé "final".pdf', inline=False)
    assert value.startswith('attachment; filename="r_sum_ _final_.pdf"')
    assert "filename*=UTF-8''r%C3%A9sum%C3%A9%20%22final%22.pdf" in value


# ---------------------------------------------------------------- API


def _stored_files(settings: Settings) -> list[Path]:
    return [f for f in Path(settings.storage_dir).rglob("*") if f.is_file()]


async def _upload(
    client: httpx.AsyncClient, who: Person, key: str, name: str, data: bytes
) -> httpx.Response:
    return await client.post(
        f"/api/v1/incidents/{key}/attachments",
        params={"filename": name},
        content=data,
        headers={**who.headers, "content-type": "application/octet-stream"},
    )


@pytest.mark.db
async def test_upload_list_download_and_serve(
    client: httpx.AsyncClient, people: dict[str, Person], create_incident: CreateIncident
) -> None:
    inc = await create_incident()
    res = await _upload(client, people["mira"], str(inc["key"]), "screenshot.png", PNG)
    assert res.status_code == 201, res.text
    att = res.json()
    assert (att["content_type"], att["is_image"], att["size_bytes"]) == (
        "image/png",
        True,
        len(PNG),
    )
    assert att["can_delete"] is True

    listing = await client.get(
        f"/api/v1/incidents/{inc['key']}/attachments", headers=people["sam"].headers
    )
    assert [a["id"] for a in listing.json()] == [att["id"]]
    assert listing.json()[0]["can_delete"] is False  # viewers can see, not delete

    # 302 to a signed link; JSON when asked.
    redirect = await client.get(
        f"/api/v1/attachments/{att['id']}/download", headers=people["sam"].headers
    )
    assert redirect.status_code == 302
    link = await client.get(
        f"/api/v1/attachments/{att['id']}/download",
        params={"inline": "true"},
        headers={**people["sam"].headers, "accept": "application/json"},
    )
    url = link.json()["url"]
    assert redirect.headers["location"].startswith("/api/v1/files?")

    served = await client.get(url)  # the signed link itself needs no bearer token
    assert served.status_code == 200
    assert served.content == PNG
    assert served.headers["content-type"] == "image/png"
    assert served.headers["content-disposition"].startswith("inline;")
    assert "sandbox" in served.headers["content-security-policy"]
    assert served.headers["x-content-type-options"] == "nosniff"

    tampered = await client.get(url.replace("image%2Fpng", "text%2Fhtml"))
    assert tampered.status_code == 404

    events = await client.get(
        f"/api/v1/incidents/{inc['key']}/events", headers=people["mira"].headers
    )
    assert "attachment_added" in [e["event_type"] for e in events.json()]


@pytest.mark.db
async def test_pdf_and_text_always_download_never_inline(
    client: httpx.AsyncClient, people: dict[str, Person], create_incident: CreateIncident
) -> None:
    inc = await create_incident()
    att = (await _upload(client, people["mira"], str(inc["key"]), "report.pdf", PDF)).json()
    link = await client.get(
        f"/api/v1/attachments/{att['id']}/download",
        params={"inline": "true"},
        headers={**people["mira"].headers, "accept": "application/json"},
    )
    served = await client.get(link.json()["url"])
    assert served.headers["content-disposition"].startswith("attachment;")


@pytest.mark.db
async def test_upload_rules(
    client: httpx.AsyncClient,
    people: dict[str, Person],
    create_incident: CreateIncident,
    build_app: BuildApp,
) -> None:
    inc = await create_incident()
    key = str(inc["key"])

    html = await _upload(client, people["mira"], key, "x.html", b"<script>alert(1)</script>")
    assert (html.status_code, html.json()["error"]["code"]) == (415, "unsupported_type")

    empty = await _upload(client, people["mira"], key, "empty.txt", b"")
    assert empty.json()["error"]["code"] == "empty_file"

    viewer = await _upload(client, people["sam"], key, "a.png", PNG)
    assert viewer.status_code == 403

    missing = await _upload(client, people["mira"], "TASK-999", "a.png", PNG)
    assert missing.status_code == 404

    small = build_app(max_upload_mb=1)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=small), base_url="http://t"
    ) as c:
        big = await _upload(c, people["mira"], key, "big.log", b"x" * (1024 * 1024 + 1))
    assert (big.status_code, big.json()["error"]["code"]) == (413, "file_too_large")


@pytest.mark.db
async def test_delete_is_uploader_or_admin_and_removes_the_file(
    client: httpx.AsyncClient,
    people: dict[str, Person],
    create_incident: CreateIncident,
    settings: Settings,
) -> None:
    inc = await create_incident()
    att = (await _upload(client, people["mira"], str(inc["key"]), "a.log", b"hello\n")).json()
    assert _stored_files(settings) != []

    other = await client.delete(f"/api/v1/attachments/{att['id']}", headers=people["max"].headers)
    assert other.status_code == 403
    ok = await client.delete(f"/api/v1/attachments/{att['id']}", headers=people["admin"].headers)
    assert ok.status_code == 204

    assert _stored_files(settings) == []
    gone = await client.get(
        f"/api/v1/attachments/{att['id']}/download", headers=people["admin"].headers
    )
    assert gone.status_code == 404
    events = await client.get(
        f"/api/v1/incidents/{inc['key']}/events", headers=people["mira"].headers
    )
    assert "attachment_deleted" in [e["event_type"] for e in events.json()]
