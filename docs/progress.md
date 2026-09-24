# Progress log

One entry per working day: what landed, what is next. Useful context for reviewers and
for the interview.

## 2026-09-22 - Phase 0 (Skeleton)

**Done**

- Repository layout per spec section 15; Compose stack (db, mailpit, api, worker, web).
- API app factory with request-ID middleware (`req_<ULID>`), structlog JSON logging,
  unified error envelope, security headers, CORS allow-list, Prometheus `/metrics`,
  optional Sentry.
- `/health` with DB probe and 2 s timeout (503 when the DB is down).
- Settings validated by pydantic-settings; production refuses a weak `JWT_SECRET` or `*` CORS.
- Alembic initialised with naming conventions; baseline migration enables `citext`, `pg_trgm`.
- Worker process shell with graceful shutdown.
- Frontend: Vite + React 18 + strict TS + Tailwind with design/motion tokens; status page.
- Tests: backend (health, request context/errors, config, worker), frontend (status page).
- CI: backend, frontend, gitleaks, compose smoke. Deploy workflow on `v*` tags.
- Deploy assets: prod Compose, Caddyfile, EC2 bootstrap, `vercel.json`, runbook.

**Found when first run on real CPython + Postgres (fixed)**

- prometheus-fastapi-instrumentator 7.1 crashes on FastAPI 0.141 included routers ->
  replaced by a small pure-ASGI metrics middleware (`app/core/metrics.py`).
- Config tests read the runner's `APP_ENV` (would have failed in CI) -> env isolated.
- Windows: async psycopg cannot use the Proactor loop -> selector loop for worker,
  seed, tests and `make dev-api`.

## 2026-09-22 - Phase 1 (Auth + users)

**Done**

- Migration `0002`: `users` (CITEXT email, role enum), `refresh_tokens`; `alembic check`
  confirms models and migrations agree, and CI now enforces it.
- argon2id hashing, JWT access tokens, opaque rotating refresh tokens with reuse
  detection, HttpOnly/SameSite=Strict cookie scoped to `/api/v1/auth`.
- `/auth/register|login|refresh|logout|me`, `/users` list + update with role/ownership
  rules and a last-admin guard; deactivation revokes sessions immediately.
- In-memory per-IP rate limits with `RateLimit-*` headers.
- Seed script (`make seed` / `make seed-local`) with the three demo accounts.
- OpenAPI export + generated TypeScript types; CI fails if either is stale.
- Frontend: typed client with single-flight silent refresh, auth context, login and
  register pages, protected home with team directory. Verified in a browser against the
  live API (login, reload resume, sign-out, HttpOnly cookie not readable from JS).
- Tests: 88 backend (90 % coverage) incl. `test_auth.py` + `test_permissions.py`;
  17 frontend. A frontend test caught a real bug: error bodies were read twice, so every
  API error showed as a generic "HTTP 401".

**Open (needs your accounts)**

- [ ] Push to GitHub, confirm CI green.
- [ ] Deploy per docs/deployment.md; run `make seed` on the instance
      (`docker compose -f docker-compose.prod.yml exec api python -m app.scripts.seed`);
      confirm login on the live URL (Phase 1 exit criterion).

## 2026-09-22 - Phases 2 and 3 + core UI

**Done**

- Migrations `0003` (incidents, comments, incident_events, idempotency_keys; generated
  weighted search_vector; partial, GIN and trigram indexes) and `0004` (event `seq`).
- Server-side lifecycle (`ALLOWED` map), permission matrix as pure functions, SLA clocks
  from config, first-response tracking, per-field audit, soft delete/restore,
  `Idempotency-Key`, comments with internal notes and a 15-minute edit window.
- Query layer: repeatable filters, full-text + trigram word similarity + key lookup,
  relevance and multi-field sorts, keyset cursors. `EXPLAIN` test proves the list index.
- Dashboard summary with 30 s cache invalidated on every audited write.
- Seed: 5 users, 25 incidents across 14 days, played through the real services.
- UI: app shell, command palette, dashboard (validated chart palette), list with views and
  URL filters, create drawer, detail page with status control, comments, timeline, SLA bars.
- Tests: 247 backend (94 % coverage), 47 frontend. Route + Markdown code splitting.

**Bugs found by running it for real (all fixed, with regression tests)**

- Same-transaction audit events could share a timestamp and reorder -> identity `seq`.
- Trigram whole-string similarity missed one-word typos in long titles -> word similarity.
- Command palette: async results left nothing highlighted, so Enter did nothing.
- Create drawer: a shared `layoutId` stalled the exit animation after choosing a priority,
  leaving an invisible modal mounted over the page.
- Detail page kept the previous incident's tab when navigating between incidents.

**Open (needs your accounts)** -- unchanged: push + CI, deploy, live checks.

**Next (Phase 4)**: transactional outbox + in-app notifications, worker delivery with
backoff and `SKIP LOCKED`, providers (smtp/brevo/console), SLA breach checker, watchers,
@mentions, SSE live updates, notification centre UI.

## 2026-09-22 - Phase 4 (Notifications + live updates)

**Done**

- Migration `0005`: `notification_outbox` (unique per event/recipient/kind, partial index
  on due rows), `in_app_notifications`, `incident_watchers`, `worker_heartbeats`, and new
  audit event types (watcher added/removed, SLA breached).
- Recipient rules as one pure function (table-tested); `@mentions` resolved by email
  local part; notifications staged in the same transaction as the change.
- Worker: `SKIP LOCKED` batches, 1/2/4/8-minute backoff, failed after 5 attempts,
  heartbeat surfaced in `/health`; SLA breach checker de-duplicated per deadline.
- Providers: SMTP, Brevo, Resend, console. Jinja2 HTML + text templates, snapshot-tested,
  HTML escaped, header injection impossible.
- Live updates: `pg_notify` from a `before_commit` hook (nothing on rollback), one LISTEN
  broker per process, `GET /events/stream` (SSE) with keep-alives, per-recipient filtering
  and `reauth` on token expiry. ADR 0005 records the outbox/NOTIFY/SSE decision.
- UI: notification bell (badge, swing, popover, mark all read), toast with *Open*,
  notifications page (inbox, unread filter, email log, email on/off), Watch button and
  watcher avatars, `@` autocomplete in comments, live refresh of lists/detail/dashboard,
  offline banner, admin email outbox (counts, worker health, filter, last error, retry),
  palette entries.
- Tests: 314 backend (91.5 % coverage; SMTP against a real in-process server, SSE against
  a real uvicorn), 76 frontend.
- Verified live: SSE through the Vite proxy delivers `incident.updated` and the
  recipient's `notification.new` within a second; a mention email went pending -> sent in
  ~4 s through the worker.

**Found along the way (fixed)**

- httpx's ASGI transport buffers whole responses, so SSE had to be tested over real HTTP.
- aiosmtpd cannot bind port 0 on Windows (readiness probe) -> pick a free port first.
- Messages sent while a browser was disconnected were simply lost -> a reconnect now
  refetches incidents, the dashboard and notifications.
- Known, accepted: a NOTIFY that lands while the very first notifications fetch is still
  in flight is folded into that request by TanStack Query, so the bell can lag until the
  next event or the 2-minute poll.

**Next (Phase 6)**: attachments, Playwright end-to-end, Lighthouse pass, security
checklist, `v1.0.0` on the live URL.

## 2026-09-22 - Phase 5 (Frontend complete)

**Done**

- Backend: `GET /incidents?watching=true`; read-only `GET /admin/settings` (SLA targets,
  feature flags, runtime, worker status). 4 new tests.
- Shell rebuilt: grouped sidebar (Admin section), unread badge, settings / theme / health
  footer, breadcrumb, phone bottom bar with a draggable "More" sheet, animated route
  transitions, an error boundary per route (request ID + copy details), `?` shortcut
  sheet, `G`-sequences and `Ctrl /`.
- Preferences store: theme System / Dark / Light and motion System / Full / Reduced,
  persisted, applied before first paint, driving both CSS and `MotionConfig`.
- New screens: Settings, admin Users, admin Configuration.
- List: Watching view, quick actions (assign / status / watch) with `A` / `S`, first-load
  stagger, live-arrival glow. Detail: status checkmark pop, timeline grouped by day,
  comment auto-scroll, assignee workload counts. Dashboard: sparklines + priority donut.
  Login: drifting gradient mesh.
- Tests: 89 Vitest; Playwright smoke flow (report -> watch -> @mention -> resolve ->
  notification; admin pages; viewer restrictions; phone layout without sideways scroll)
  passing in Chrome, Edge, Brave and a Pixel 7 viewport.

**Found along the way (fixed)**

- `networkidle` never settles with an SSE stream open; E2E waits for content instead.
- Lazy route chunks can take >1 s to transform in tests; `asyncUtilTimeout` raised to 3 s.
- The login rate limit (5/min per IP) trips a multi-browser E2E run; documented running
  the API with `LOGIN_RATE_LIMIT_PER_MIN=100` for E2E.

**Not yet measured**: the Lighthouse accessibility score (exit criterion >= 95); axe-style
checks were done by hand (labels, roles, focus rings, reduced motion), not with a tool.

## 2026-09-22 - Phase 6 (Polish + ship) and Phase 7 (AI)

**Done: Phase 6**

- Migration `0006`: `attachments` (10 MB check constraint, unique random storage key) and
  `ai_suggestions`; new audit types `attachment_added`, `attachment_deleted`, `ai_applied`.
  Round-trips down to base and back.
- Attachments: the raw file as the request body (no multipart dependency), type sniffed
  from the content (allow-list; SVG/HTML refused), random keys, 302 to short-lived signed
  links, served sandboxed. Local-disk backend with HMAC links; S3 backend with our own
  SigV4, verified against AWS's documented example. ADR 0006.
- UI: attachments panel with drag and drop, paste-a-screenshot and click to upload,
  thumbnails, a lightbox with arrow keys, remove for uploader/admin.
- Docs: README rewritten in the spec's order (traceability, architecture, AI accuracy,
  tests, API, design, deployment), `docs/runbook.md`, `docs/security.md` (walked: 2 items
  open, with reasons), ADRs 0006/0007, screenshots, production `.env` for Brevo,
  Supabase Storage and AI.
- Secrets: manual pattern scan of every file to be committed: clean. `.gitleaks.toml`
  allowlists only AWS's published example key.
- Docker: an `attachments` volume and a `/data` directory owned by the non-root user.

**Done: Phase 7**

- One provider interface: an OpenAI-compatible client for Groq/Gemini/Ollama, a
  FakeProvider for tests, and a deterministic rule engine (`LLM_PROVIDER=rules`) that
  works offline and is the fallback on timeout, 429/5xx, invalid output or the daily cap.
- Triage with duplicate detection, thread summary, postmortem draft (posted as an
  internal note on accept), natural-language search to filters; every suggestion stored
  with model, prompt version, latency and tokens; accept/reject audited; accept-rate stats
  for admins. ADR 0007.
- Safety: schema-validated output with extra keys forbidden, IDs checked in the
  database, fenced user text, no emails or hashes or attachments to the model,
  internal-note visibility respected, 10/min per user, daily cap, input cap, timeout +
  one retry.
- Eval harness: 20 hand-labelled incidents; rule engine **13/20 priority** (19/20 within
  one level), **17/20 category**. The LLM number needs an API key and is not measured yet.

**Found along the way (fixed)**

- "show me critical ..." was read as "assigned to me"; bare "me" no longer means the assignee.
- "open incidents" found nothing when the work was in progress: "open" now means unresolved.
- The postmortem timeline listed watcher events; noise events are skipped.
- Multiple dropped files lost their toasts (TanStack's per-call `mutate` callbacks fire
  only for the latest call); now one promise per file.
- The dev compose `environment:` on `api` would have replaced the shared block (YAML
  merge is shallow) and dropped `DATABASE_URL`; moved into the anchor.

**Not done (needs you)**: commit and tag `v1.0.0`, push, deploy to the live URL, record
the hero GIF, measure the LLM number with a Groq key, and write the "How AI tools were
used" paragraph in your own words.

Totals after Phases 6-7: **375 backend tests (93 % coverage)**, 98 frontend tests,
Playwright smoke passing in Chrome, Edge, Brave and a phone viewport.

## 2026-09-22 - Cleanup and real integrations

**Removed** (sent to the Recycle Bin, restorable): the stale Phase 0 copy
`incident-desk/incident-desk/` (73 files, all superseded), build output
(`frontend/dist`), test output (Playwright report and results, `.coverage`) and every
tool cache. Dead code: `join_lines`, `has_comment_from_non_reporter`, an unused `Storage`
protocol, `applyTheme`, three unused motion presets, an unused type. Test doubles
(`FakeSender`, `FakeProvider`) moved from `app/` to `tests/fakes.py`, so production code
contains only real integrations. `.gitignore` tidied (`.claude/` ignored).

**Real data instead of demo data**

- `DEMO_MODE` (default off): the login page shows demo accounts only when it is on;
  the register link only when self-registration is open (`GET /api/v1/auth/config`).
- `python -m app.scripts.create_admin`: the first real admin (prompted password, or
  `ADMIN_PASSWORD`), or promote/recover an existing account.
- Admin -> Users -> **Add person** (works with registration closed), with a generated
  temporary password and a role.
- The demo seed refuses a production database without `--allow-production`.
- `python -m app.scripts.check_integrations [--send-test-email ...]`: checks the
  database and migrations, the worker, email (SMTP login or API key, optional real send),
  storage (write/read/delete) and the AI provider, then reports ok/warn/FAIL.
- SMTP: port 465 (`SMTP_SSL`) as well as 587 STARTTLS, and `Date`/`Message-ID` headers
  for deliverability.
- [docs/integrations.md](integrations.md): step-by-step setups for PostgreSQL, Neon,
  Supabase, Gmail, Outlook/M365, any SMTP, Brevo, Resend, Supabase Storage, AWS S3,
  Cloudflare R2, Groq, Gemini, Ollama and Sentry, plus a go-live checklist.

**Found along the way**: Vite reloaded the page whenever Playwright wrote its report
(now ignored by the watcher); a Resend "sending access" key would have been reported as
broken by the check (now a warning that suggests a test send).
