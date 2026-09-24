"""AWS Signature Version 4 for S3-compatible storage (AWS, Supabase Storage, R2, MinIO).

Two operations only, so a 100-line signer beats a 70 MB SDK: presigned GET URLs for
downloads and header-signed PUT/DELETE for uploads. Verified against the example in
AWS's "Authenticating Requests: Using Query Parameters" documentation (see tests).
"""

from __future__ import annotations

import hashlib
import hmac
from collections.abc import Mapping
from datetime import datetime
from urllib.parse import quote, urlsplit

ALGORITHM = "AWS4-HMAC-SHA256"
UNSIGNED = "UNSIGNED-PAYLOAD"


def _hmac(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode(), hashlib.sha256).digest()


def _signing_key(secret: str, date: str, region: str, service: str) -> bytes:
    k = _hmac(("AWS4" + secret).encode(), date)
    k = _hmac(k, region)
    k = _hmac(k, service)
    return _hmac(k, "aws4_request")


def _uri_encode(value: str, *, keep_slash: bool = False) -> str:
    return quote(value, safe="/-_.~" if keep_slash else "-_.~")


def _canonical_query(params: Mapping[str, str]) -> str:
    return "&".join(f"{_uri_encode(k)}={_uri_encode(v)}" for k, v in sorted(params.items()))


def presign_url(
    *,
    method: str,
    url: str,
    access_key: str,
    secret_key: str,
    region: str,
    expires: int,
    now: datetime,
    extra_params: Mapping[str, str] | None = None,
    service: str = "s3",
) -> str:
    """Presigned URL (query-string auth) valid for ``expires`` seconds from ``now``."""
    parts = urlsplit(url)
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    date = now.strftime("%Y%m%d")
    scope = f"{date}/{region}/{service}/aws4_request"
    params = {
        "X-Amz-Algorithm": ALGORITHM,
        "X-Amz-Credential": f"{access_key}/{scope}",
        "X-Amz-Date": amz_date,
        "X-Amz-Expires": str(expires),
        "X-Amz-SignedHeaders": "host",
        **(extra_params or {}),
    }
    canonical = "\n".join(
        [
            method,
            _uri_encode(parts.path or "/", keep_slash=True),
            _canonical_query(params),
            f"host:{parts.netloc}\n",
            "host",
            UNSIGNED,
        ]
    )
    to_sign = "\n".join(
        [ALGORITHM, amz_date, scope, hashlib.sha256(canonical.encode()).hexdigest()]
    )
    signature = hmac.new(
        _signing_key(secret_key, date, region, service), to_sign.encode(), hashlib.sha256
    ).hexdigest()
    return (
        f"{parts.scheme}://{parts.netloc}{_uri_encode(parts.path, keep_slash=True)}"
        f"?{_canonical_query(params)}&X-Amz-Signature={signature}"
    )


def sign_headers(
    *,
    method: str,
    url: str,
    access_key: str,
    secret_key: str,
    region: str,
    now: datetime,
    payload: bytes = b"",
    headers: Mapping[str, str] | None = None,
    service: str = "s3",
) -> dict[str, str]:
    """Headers (incl. Authorization) for a request signed in the header form."""
    parts = urlsplit(url)
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    date = now.strftime("%Y%m%d")
    scope = f"{date}/{region}/{service}/aws4_request"
    payload_hash = hashlib.sha256(payload).hexdigest()
    signed: dict[str, str] = {
        "host": parts.netloc,
        "x-amz-content-sha256": payload_hash,
        "x-amz-date": amz_date,
        **{k.lower(): v.strip() for k, v in (headers or {}).items()},
    }
    names = sorted(signed)
    canonical = "\n".join(
        [
            method,
            _uri_encode(parts.path or "/", keep_slash=True),
            parts.query,
            "".join(f"{n}:{signed[n]}\n" for n in names),
            ";".join(names),
            payload_hash,
        ]
    )
    to_sign = "\n".join(
        [ALGORITHM, amz_date, scope, hashlib.sha256(canonical.encode()).hexdigest()]
    )
    signature = hmac.new(
        _signing_key(secret_key, date, region, service), to_sign.encode(), hashlib.sha256
    ).hexdigest()
    out = {k: v for k, v in signed.items() if k != "host"}
    out["authorization"] = (
        f"{ALGORITHM} Credential={access_key}/{scope}, "
        f"SignedHeaders={';'.join(names)}, Signature={signature}"
    )
    return out
