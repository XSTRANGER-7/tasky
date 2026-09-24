# ADR 0003 - JWT access tokens with rotating refresh tokens

- Status: accepted
- Date: 2026-09-22

## Context

The SPA (Vercel) talks to the API (EC2) through a same-origin rewrite for REST, but the
Phase 4 SSE stream goes straight to the API domain and must authenticate with a header.
We want short-lived credentials, revocation (logout, deactivation, theft), and no
"logged out every 15 minutes" experience.

Options considered:

1. **Server sessions** (opaque cookie + session table): simple and revocable, but every
   request needs a lookup and the cross-origin SSE stream would need the cookie too.
2. **A single long-lived JWT**: no revocation short of rotating the signing key.
3. **Short-lived JWT access token + opaque rotating refresh token** (chosen).

## Decision

- **Access token**: JWT HS256, 15 minutes, claims `sub`, `typ=access`, `iat`, `exp`,
  `jti`; verified with a pinned algorithm list (so `alg=none` and algorithm confusion
  fail). Kept in memory by the SPA and sent as `Authorization: Bearer`.
- **Refresh token**: 256 random bits, stored only as SHA-256 in `refresh_tokens`, sent as
  an `HttpOnly; SameSite=Strict; Path=/api/v1/auth` cookie (Secure outside development).
- **Rotation**: each `/auth/refresh` revokes the presented token (row-locked) and issues a
  new one, linked via `replaced_by_id`.
- **Reuse detection**: presenting an already-revoked token revokes *all* of that user's
  refresh tokens. A stolen token is therefore good for at most one use, and using it
  ends the victim's and the attacker's sessions alike, which surfaces the theft.
- **Authorisation reads the database**: the user row (role, `is_active`) is loaded per
  request, so demotion and deactivation are immediate; deactivation also revokes all
  refresh tokens.

## Consequences

- One primary-key lookup per authenticated request -- acceptable at this scale, and it
  buys immediate role changes.
- Concurrent refreshes from two tabs can trip reuse detection. The client makes refresh
  single-flight within a tab; cross-tab coordination is a follow-up.
- The refresh cookie never reaches non-auth routes (path scope) and is never readable by
  JavaScript; an XSS can act while the page is open but cannot exfiltrate a session that
  outlives it.
