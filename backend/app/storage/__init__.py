"""Attachment storage: local disk (development) or any S3-compatible bucket (production).

Both backends store bytes under a random key and hand out short-lived download URLs:
presigned S3 URLs, or HMAC-signed URLs served by the API for local disk. The download
endpoint only ever redirects to one of these, so a leaked link expires on its own.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import secrets
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote, urlencode

import httpx

from app.core.config import Settings
from app.storage.sigv4 import presign_url, sign_headers


class StorageError(Exception):
    pass


def new_key(incident_id: str) -> str:
    """Random, unguessable, and never derived from the user's filename."""
    return f"incidents/{incident_id}/{secrets.token_urlsafe(24)}"


def content_disposition(filename: str, *, inline: bool) -> str:
    ascii_name = "".join(c if c.isascii() and c not in '"\\' else "_" for c in filename)
    kind = "inline" if inline else "attachment"
    return f"{kind}; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename)}"


# ---------------------------------------------------------------- local disk


class LocalStorage:
    def __init__(self, settings: Settings) -> None:
        self.root = Path(settings.storage_dir).resolve()
        self.base_url = settings.app_base_url.rstrip("/")
        self.ttl = settings.download_url_seconds
        # Derived key: a leaked download URL cannot be used to forge tokens, and vice versa.
        self._key = hashlib.sha256(f"attachments:{settings.jwt_secret}".encode()).digest()

    def _path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if self.root not in path.parents:  # defence in depth: keys are ours, never user text
            raise StorageError("invalid storage key")
        return path

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        path = self._path(key)

        def write() -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)

        await asyncio.to_thread(write)

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(self._path(key).unlink, missing_ok=True)

    def read(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    async def get(self, key: str) -> bytes:
        try:
            return await asyncio.to_thread(self.read, key)
        except OSError as exc:
            raise StorageError(f"local get: {type(exc).__name__}") from exc

    def sign(self, key: str, expires_at: int, disposition: str, content_type: str) -> str:
        msg = f"{key}\n{expires_at}\n{disposition}\n{content_type}".encode()
        return hmac.new(self._key, msg, hashlib.sha256).hexdigest()

    def verify(
        self, key: str, expires_at: int, disposition: str, content_type: str, signature: str
    ) -> bool:
        if expires_at < time.time():
            return False
        expected = self.sign(key, expires_at, disposition, content_type)
        return hmac.compare_digest(expected, signature)

    def download_url(self, key: str, *, filename: str, content_type: str, inline: bool) -> str:
        expires_at = int(time.time()) + self.ttl
        disposition = content_disposition(filename, inline=inline)
        query = urlencode(
            {
                "key": key,
                "exp": expires_at,
                "cd": disposition,
                "ct": content_type,
                "sig": self.sign(key, expires_at, disposition, content_type),
            }
        )
        # Relative to the API so it works behind the dev proxy and the Vercel rewrite alike.
        return f"/api/v1/files?{query}"


# ---------------------------------------------------------------- S3-compatible


class S3Storage:
    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        if not (settings.s3_endpoint and settings.s3_bucket):
            raise StorageError("STORAGE_BACKEND=s3 needs S3_ENDPOINT and S3_BUCKET")
        self.endpoint = settings.s3_endpoint.rstrip("/")
        self.bucket = settings.s3_bucket
        self.region = settings.s3_region
        self.access_key = settings.s3_access_key or ""
        self.secret_key = settings.s3_secret_key or ""
        self.ttl = settings.download_url_seconds
        self._client = client

    def _url(self, key: str) -> str:
        return f"{self.endpoint}/{self.bucket}/{key}"  # path-style: works for every provider

    async def _send(
        self, method: str, key: str, data: bytes = b"", headers: dict[str, str] | None = None
    ) -> bytes:
        url = self._url(key)
        signed = sign_headers(
            method=method,
            url=url,
            access_key=self.access_key,
            secret_key=self.secret_key,
            region=self.region,
            now=datetime.now(UTC),
            payload=data,
            headers=headers,
        )
        client = self._client or httpx.AsyncClient(timeout=30)
        try:
            res = await client.request(method, url, content=data, headers=signed)
        except httpx.HTTPError as exc:
            raise StorageError(f"s3 {method}: {type(exc).__name__}") from exc
        finally:
            if self._client is None:
                await client.aclose()
        if res.status_code >= 300 and not (method == "DELETE" and res.status_code == 404):
            raise StorageError(f"s3 {method}: HTTP {res.status_code}")
        return res.content

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        await self._send("PUT", key, data, {"content-type": content_type})

    async def delete(self, key: str) -> None:
        await self._send("DELETE", key)

    async def get(self, key: str) -> bytes:
        return await self._send("GET", key)

    def download_url(self, key: str, *, filename: str, content_type: str, inline: bool) -> str:
        return presign_url(
            method="GET",
            url=self._url(key),
            access_key=self.access_key,
            secret_key=self.secret_key,
            region=self.region,
            expires=self.ttl,
            now=datetime.now(UTC),
            extra_params={
                "response-content-disposition": content_disposition(filename, inline=inline),
                "response-content-type": content_type,
            },
        )


def build_storage(settings: Settings) -> LocalStorage | S3Storage:
    if settings.storage_backend == "s3":
        return S3Storage(settings)
    return LocalStorage(settings)
