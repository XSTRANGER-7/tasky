# ADR 0005 - Transactional outbox, LISTEN/NOTIFY and SSE for notifications

- Status: accepted
- Date: 2026-09-22

## Context

An assignment, resolution, comment, @mention or SLA breach must reach the right people
by email and in the app. The email must never be lost when the provider is down, it must
never go out for a change that rolled back, and a retry must never send it twice.
Separately, open browsers should see changes other people make without polling.

The deployment is one small EC2 instance and a managed Postgres. There is no Redis and
no message broker, and adding one would be the biggest single piece of infrastructure.

## Decision

**Outbox in the same database.** The service that changes an incident also inserts
`notification_outbox` rows (and `in_app_notifications`) in the same transaction. A
unique `(event_id, recipient_user_id, kind)` makes enqueueing idempotent.

**A separate worker delivers.** It claims due rows with
`SELECT ... FOR UPDATE SKIP LOCKED LIMIT n`, so several workers never pick the same row.
It sends through a provider interface (SMTP, Brevo, Resend, console) and records the
result. Failures are retried after 1, 2, 4 and 8 minutes; the fifth failure marks the
row `failed`, and an admin can re-queue it from the outbox page. The worker writes a
heartbeat row, and `/health` and the admin page report it as `ok`, `stale` or `unknown`.

**Postgres LISTEN/NOTIFY for live updates.** A `before_commit` session hook sends
`pg_notify('incident_desk', ...)`. Postgres delivers a NOTIFY only when the transaction
commits, so a rolled-back change is never announced. Each API process holds one
`LISTEN` connection and fans messages out to its SSE subscribers through bounded queues.

**Server-Sent Events, not WebSockets.** Traffic is one-way (server to browser). SSE is
plain HTTP, so it goes through Caddy, the Vercel rewrite and our pure-ASGI middleware
unchanged. The browser client (`@microsoft/fetch-event-source`) sends the in-memory
access token as a header. Messages carry only `{type, incident}`; the client refetches
through the normal, permission-checked API, and `notification.new` is sent only to the
recipient.

## Consequences

- **At-least-once email.** If the worker crashes after the provider accepts a message
  but before it records `sent`, that email goes out again on the next pass. Provider
  idempotency keys would close that window; for incident notifications, a rare
  duplicate is better than a lost one.
- **NOTIFY is fire-and-forget.** A browser that is disconnected misses messages. On
  reconnect it refetches, and the notification list is also polled every 2 minutes as a
  safety net, so the stream only makes the UI faster and never decides correctness.
- **Payload limit.** NOTIFY payloads are capped at 8 kB. Ours are tiny because data is
  always refetched.
- **Token expiry on a long-lived stream.** The server sends `reauth` when the
  access token expires and closes the stream; the client refreshes and reconnects. A
  401 on connect takes the same path.
- **Scale ceiling.** Each API process uses one LISTEN connection, and a busy worker
  scans a partial index on pending rows. Both are comfortable far beyond this project;
  the next step would be a real queue (SQS or Redis streams), with the outbox table kept
  as the source of truth.
