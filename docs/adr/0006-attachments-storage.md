# ADR 0006 - Attachments: raw-body upload, content sniffing, signed links

- Status: accepted
- Date: 2026-09-22

## Context

Incidents need screenshots, logs and PDFs attached (10 MB, allow-list: PNG, JPEG, GIF,
PDF, TXT, LOG, JSON). Uploaded files are the classic way to get stored XSS or malware onto
a trusted domain. Development runs without cloud accounts; production stores files in a
free S3-compatible bucket (Supabase Storage). The 1 GB instance should not stream large
files through the API more than it has to.

## Decision

- **Upload as the raw request body** (`POST /incidents/{id}/attachments?filename=`),
  not multipart. No multipart parser to add or trust, and the size limit stops a large
  body while it is still arriving (`Content-Length` first, then a running count).
- **The server decides the type** from the first bytes (PNG/JPEG/GIF/PDF signatures) or,
  for text, the extension plus a strict UTF-8 check (and a JSON parse for `.json`). The
  client's `Content-Type` is ignored. SVG and HTML are never accepted.
- **Stored under a random key** (`incidents/<id>/<24 random bytes>`); the filename is
  display-only, cleaned of paths and control characters, and never touches the file
  system or the object key.
- **Downloads are short-lived signed links** (5 minutes). `GET /attachments/{id}/download`
  checks access and redirects (302), or returns the link as JSON for `<img>` previews,
  which cannot send a bearer token.
  - S3: a SigV4 presigned URL, with the response `Content-Disposition` and `Content-Type`
    pinned in the signature.
  - Local disk: an HMAC-signed `/api/v1/files` link (key, expiry, disposition and type
    are all signed; the key is derived from, but not equal to, the JWT secret).
- **Never executed**: files are served with `X-Content-Type-Options: nosniff`, a
  `default-src 'none'; sandbox` CSP, and `attachment` disposition for everything except
  images.
- **SigV4 is ~100 lines of our own** instead of boto3 (two operations only; no 70 MB SDK
  in a 450 MB container). It is verified against AWS's documented example in the tests.

## Consequences

- A leaked link stops working within minutes; revoking access to the incident revokes
  new links at once.
- The browser uploads to the API, not straight to the bucket. Direct-to-bucket
  presigned PUTs would save API bandwidth, but they need bucket CORS and a second "upload
  finished" call; at 10 MB and team scale that complexity is not worth it yet.
- Files are not virus-scanned. The allow-list, sniffing and "never executed" serving
  limit the damage. ClamAV in the worker is the next step if external users can upload.
- Deleting an incident keeps its attachments (soft delete). Deleting an attachment
  removes the row first and then the object; an object left behind by a failed delete is
  logged and harmless.
