<p align="center"><img src="frontend/public/logo.svg" width="72" alt="Tasky logo"></p>

<h1 align="center">Tasky</h1>

<p align="center"><strong>Team task management that keeps everyone in the loop.</strong></p>

Tasky is a self-hosted task tracker for small and mid-sized teams. You create a team,
invite people, and assign work to one or more of them. Tasky keeps the people involved
informed: it sends email, updates every open screen live, tracks response and resolution
deadlines, and records every change. It suits teams that have outgrown a spreadsheet or a
long email thread but do not want a heavyweight ticketing system.

![Tasky dashboard, dark theme](docs/screenshots/dashboard-dark.png)

[What makes Tasky different](#what-makes-tasky-different) ·
[Features](#features) · [Screenshots](#screenshots) · [Tech stack](#tech-stack) ·
[Quick start](#quick-start) · [Configuration](#configuration) ·
[Using Supabase](#using-supabase) · [Development](#development) · [Testing](#testing) ·
[Security](#security) · [Troubleshooting](#troubleshooting)

## What makes Tasky different

- **Several people per task, with a lead.** A task can be assigned to up to ten
  teammates. Everyone assigned is emailed, sees it under My work and hears about every
  change; the first one is the lead, shown first and used for sorting.
- **Team workspaces with no platform super-admin.** Whoever creates a team becomes its
  admin, and admin rights stop at that team. Other people ask to join, and the team's
  admins approve them as member, viewer or co-admin, or decline. A team always keeps at
  least one admin.
- **Emails survive a restart.** Every email is written to an outbox table in the same
  database transaction as the change that caused it. A separate worker sends it and
  retries failures with backoff (1, 2, 4 and 8 minutes). Team admins get an
  **Email outbox** page with worker health, the last error for each email and a Retry
  button.
- **Real-time updates.** Lists, task pages, the dashboard and notifications refresh
  over server-sent events as soon as anything changes.
- **Two SLA timers per task.** Every task has a response deadline and a resolution
  deadline, set by its priority. A background checker flags breaches and emails the
  assignees.
- **AI that only suggests.** Tasky can suggest triage (priority, category, assignee and
  possible duplicates), summarise a thread, draft a postmortem and turn plain-language
  search into filters. Nothing changes until someone clicks Accept. AI is off by
  default. When you turn it on, an offline rule engine does the work, and you can
  optionally use Groq or Gemini (or a local Ollama) instead. Tasky falls back to the rule
  engine if the model fails.
- **Full audit timeline.** Every create, edit, assignment, status change, comment,
  attachment and accepted AI suggestion is recorded and shown on the task, grouped by
  day.
- **A calm, glass-style UI.** Frosted, iOS-style surfaces in light and dark themes,
  with a reduced-motion setting that follows the operating system unless you override it.
- **Keyboard-first.** Press `Ctrl K` for the command palette, `G` then a letter to
  jump to a page, `J`/`K` to move through lists, and `C` to create a task.

### How it compares

| | Tasky | Shared spreadsheet | Typical to-do app | Email threads |
| --- | --- | --- | --- | --- |
| Several assignees with a lead | Yes | Manual | Sometimes | No |
| Team join requests approved by admins | Yes | Sharing settings only | Varies | No |
| Emails queued and retried (outbox) | Yes | No | Varies | Sender's mail client |
| Response and resolution SLA timers | Yes | Formulas, no alerts | Due dates | No |
| Complete audit history per item | Yes | Version history | Varies | The thread itself |
| Real-time updates | Yes | Yes | Usually | No |
| AI suggestions that never act alone | Yes (optional) | No | Varies | No |
| Self-hostable, source available | Yes | Rarely | Rarely | Mail server only |

## Features

### Tasks

- Tasks have short, readable keys such as `TASK-42`. Old `INC-42` links still work.
- Each task shows **Created by**, **Assigned to** (one or more people, lead first) and
  **Assigned by**.
- Tasks move through **Open → In progress → Resolved → Closed**. The server enforces
  which moves are allowed and who may make them.
- Priorities are low, medium, high and critical. Each priority has its own SLA
  minutes, which you can configure.
- You can write comments in Markdown (sanitised) and `@mention` teammates. Team members
  can post internal notes that viewers cannot see. You can edit your own comments for
  15 minutes after posting.
- You can attach images, PDFs, logs, text and JSON files, up to 10 MB each by default.
  Files download through short-lived signed links.
- Anyone can watch a task. Team admins can add or remove people on a task, and the
  people they add are emailed.
- Only a task's creator or a team admin can delete it. Deleted tasks go to a recycle
  bin, and only admins can restore them.
- The task list has filters, full-text and typo-tolerant search, sorting and live
  updates.

### Teams and people

- On first sign-in, a **Create your team** page asks you to name your team, and you
  become its admin. To join someone else's team, find it from the team menu and send a
  join request.
- Team admins approve or decline join requests, add existing accounts, change roles
  (admin, member, viewer) and remove members.
- A person can belong to several teams and switch between them. Every list, search and
  dashboard shows only the current team's work.

### Notifications and email

- Tasky sends email for:
  - assignment
  - task updates: status changes and edits, in one email that lists every change
  - resolution
  - being added to a task
  - new comments (to watchers) and `@mentions`
  - SLA breaches
  - team join requests, approvals and declines
  - being added to a team, role changes and removal
  - password reset
- Team admins also get copies of assignments, updates and resolutions.
- Tasky never notifies the person who made the change. Each person can turn email off
  on the Notifications page, and the in-app notification centre (bell, unread count) still gets
  everything.
- Supported email providers are SMTP (Gmail, Outlook, Mailpit and others), Brevo and
  Resend. With `console`, emails are logged instead of sent.
- Optionally, new accounts can be copied into **Supabase Auth**, so they appear under
  Authentication → Users. The copies are for display only: no passwords are sent, and
  they cannot be used to sign in.

### AI assistant

- **Triage while you type a new task:** suggested priority, category and assignee,
  with a confidence score and reasoning, plus similar tasks and possible duplicates.
- **Thread summary:** a summary of the task, its current status and open questions.
- **Postmortem draft:** once a task is resolved, an editable Markdown draft that you can
  post as an internal note.
- **Plain-language search:** in the palette or the list search, start with `?` (for
  example `?my critical open tasks that breached`). Tasky turns the request into normal
  filters and never runs SQL.
- Engines are set with `LLM_PROVIDER`: `none` (off), `rules` (offline and free), `groq`,
  `gemini` or `ollama`. Calls are rate-limited per user and capped per day. If the model
  times out or returns invalid output, the rule engine answers instead.

### Dashboard

- KPI tiles with 14-day sparklines: Open, In progress, SLA breached and MTTR (last 7
  days).
- A **Created vs resolved** chart for the last 14 days.
- **Open work by priority** and **Open work by person**.
- **Recent activity** from the audit log.

### Accounts and security

- Sign in with email and password, or with Google (OAuth authorization code flow with
  PKCE, run by the server).
- Reset a forgotten password by email. The link works once and expires after 30
  minutes by default.
- Upload a profile photo and crop it in the browser before it is saved.
- Public sign-up can be turned off (`ALLOW_SELF_REGISTER=false`), so that only team
  admins create accounts.

### Look and feel

- Light, dark or system theme (`Ctrl /` toggles it), and reduced motion that you can set
  to System, Reduced or Full.
- Works from 320 px wide: a sidebar on desktop and a bottom bar on phones.
- Keyboard shortcuts for everything common. Press `?` to see them all.

| Shortcut | Action |
| --- | --- |
| `Ctrl K` | Command palette (start with `?` to ask in plain words) |
| `C` | New task |
| `G` then `D` / `T` / `M` / `W` / `N` / `S` | Dashboard, Tasks, My work, Watching, Notifications, Settings |
| `J` / `K`, `Enter` | Move through the list, open the selected task |
| `A` / `S` | Assign the selected task / change its status |
| `/` | Search the list |
| `Ctrl Enter` | Submit a comment or the create form |

## Screenshots

<table>
  <tr>
    <td width="50%"><img src="docs/screenshots/landing.png" alt="Landing page"><br><sub>Landing page</sub></td>
    <td width="50%"><img src="docs/screenshots/login.png" alt="Sign-in page"><br><sub>Sign in with email or Google</sub></td>
  </tr>
  <tr>
    <td><img src="docs/screenshots/dashboard-light.png" alt="Dashboard in the light theme"><br><sub>Dashboard, light theme</sub></td>
    <td><img src="docs/screenshots/tasks.png" alt="Task list"><br><sub>Task list with filters and live updates</sub></td>
  </tr>
  <tr>
    <td><img src="docs/screenshots/task-detail.png" alt="Task detail with AI summary"><br><sub>A task with its AI summary</sub></td>
    <td><img src="docs/screenshots/get-started.png" alt="Create your team page"><br><sub>First sign-in: create your team</sub></td>
  </tr>
  <tr>
    <td colspan="2"><img src="docs/screenshots/mobile.png" alt="Tasky on a phone"><br><sub>Phone views</sub></td>
  </tr>
</table>

## Tech stack

| Layer | Tools |
| --- | --- |
| API | FastAPI, Pydantic v2, SQLAlchemy 2 (async, psycopg 3), Alembic |
| Database | PostgreSQL 16 (14+ works; runs on Supabase or Neon too) |
| Background work | A separate Python worker: email outbox, SLA checker, Supabase Auth copy |
| Web app | React 18, TypeScript, Vite, TanStack Query, Tailwind CSS, Radix UI, Framer Motion, Recharts |
| API client | Typed from the OpenAPI schema with `openapi-typescript` and `openapi-fetch` |
| Tests | pytest, Vitest and Testing Library, Playwright end-to-end smoke tests |
| Delivery | Docker Compose, GitHub Actions |

## Quick start

### Option A: Docker

You need Docker Desktop, or Docker Engine with the Compose plugin.

```bash
cp .env.example .env
make up          # or: docker compose up -d --build
make seed        # optional demo data (or: docker compose exec api python -m app.scripts.seed)
```

`make up` builds and starts the database, Mailpit, API, worker and web app, then waits
until the API reports healthy. The API applies migrations when it starts.

| URL | What |
| --- | --- |
| http://localhost:5173 | Tasky web app |
| http://localhost:8000/docs | API docs (Swagger; ReDoc at `/redoc`) |
| http://localhost:8000/health | Health of the database and worker |
| http://localhost:8025 | Mailpit, which catches every email the worker sends |

Other targets: `make down` stops the stack but keeps the data, `make logs` follows the
API and worker logs, and `make ps` shows container status.

### Option B: Without Docker (Windows, macOS, Linux)

**Prerequisites:** Python 3.12, Node.js 20+, and PostgreSQL 16+ with an empty database
that your user owns. The first migration enables the `citext` and `pg_trgm` extensions.

```sql
-- as a PostgreSQL superuser
CREATE ROLE app LOGIN PASSWORD 'app';
CREATE DATABASE incidents OWNER app;
CREATE DATABASE test OWNER app;   -- only needed for the backend tests
```

Copy `.env.example` to `.env` **in the repository root**, because the backend reads
`../.env`. Then set at least:

```dotenv
DATABASE_URL=postgresql+psycopg://app:app@localhost:5432/incidents
EMAIL_PROVIDER=console   # log emails instead of sending, until you set up SMTP
```

**Backend on macOS or Linux:**

```bash
cd backend
python3.12 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/alembic upgrade head
.venv/bin/uvicorn app.main:app --port 8000 --reload

# second terminal, also in backend/: email delivery, SLA checks, Supabase Auth copy
.venv/bin/python -m app.notifications.worker
```

**Backend on Windows (PowerShell):**

```powershell
cd backend
py -3.12 -m venv .venv
.venv\Scripts\pip.exe install -e ".[dev]"
.venv\Scripts\alembic.exe upgrade head
.venv\Scripts\uvicorn.exe app.main:app --port 8000 --reload --loop asyncio:SelectorEventLoop

# second terminal, also in backend\
.venv\Scripts\python.exe -m app.notifications.worker
```

On Windows, you must add `--loop asyncio:SelectorEventLoop` to uvicorn, because async
psycopg cannot use the default Proactor event loop. The worker, seed script and tests
select the right loop automatically.

**Frontend (any OS):**

```bash
cd frontend
npm ci
npm run dev      # http://localhost:5173, with /api proxied to :8000
```

**Optional demo data:** run `python -m app.scripts.seed` from `backend/`, with the venv
Python. It creates five demo accounts (`admin@demo.io`, `mira@demo.io`, `jonas@demo.io`,
`priya@demo.io` and `sam@demo.io`, all with the password `demo1234`) and 25 sample tasks
spread over two weeks. Set `DEMO_MODE=true` to show one-click demo logins on the sign-in
page. Never seed a real database: the script refuses to run when `APP_ENV=production`.

If you have `make` and `bash` (macOS, Linux, or Git Bash/WSL on Windows), the shortcuts
are `make install`, `make dev-api`, `make dev-worker`, `make dev-web` and
`make seed-local`.

### First steps

1. Open http://localhost:5173 and **sign up**, or choose **Continue with Google**
   once it is configured.
2. On the **Create your team** page, name your team. You become its admin.
3. Invite people: they sign up and ask to join, and you approve them under **Team**.
   You can also add existing accounts directly.
4. Create a task (`C`), assign it to one or more people, and watch the emails arrive in
   Mailpit (Docker) or the worker log (`console`).

## Configuration

All settings come from `.env` in the repository root. Every variable is listed with its
default in [`.env.example`](.env.example). The API refuses to start in production with
the default `JWT_SECRET`, a `*` CORS origin, or an email or AI provider that has no key.

| Variable | Purpose |
| --- | --- |
| `DATABASE_URL` | PostgreSQL connection string, which must start with `postgresql+psycopg://`. Docker Compose overrides it with its own database. |
| `JWT_SECRET` | Token signing secret. Use at least 32 random bytes in production (`openssl rand -hex 32`). |
| `APP_BASE_URL` | The public URL of the web app, used for links in emails and the Google redirect. |
| `ALLOW_SELF_REGISTER` | `true` allows public sign-up. With `false`, only team admins create accounts. |
| `EMAIL_PROVIDER` | `smtp`, `brevo`, `resend` or `console` (log only). |
| `EMAIL_FROM` | The sender, for example `"Tasky <noreply@example.com>"`. |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_STARTTLS`, `SMTP_SSL` | SMTP settings. Use `STARTTLS` for port 587 and `SSL` for port 465. |
| `BREVO_API_KEY` / `RESEND_API_KEY` | Keys for the HTTPS email APIs. |
| `STORAGE_BACKEND` | `local` (files in `STORAGE_DIR`) or `s3`. |
| `S3_ENDPOINT`, `S3_BUCKET`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`, `S3_REGION` | Any S3-compatible bucket (Supabase Storage, AWS S3, Cloudflare R2, MinIO). |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | Turn on "Continue with Google". Both must be set. |
| `LLM_PROVIDER`, `LLM_API_KEY`, `LLM_MODEL` | AI engine: `none`, `rules`, `groq`, `gemini` or `ollama`, with its key and an optional model name. |
| `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY` | Optional copying of accounts into Supabase Auth, for display only. |
| `RUN_WORKER_IN_API` | `true` runs the worker loop inside the API process, for single-container hosts. |
| `SLA_CRITICAL`, `SLA_HIGH`, `SLA_MEDIUM`, `SLA_LOW` | Response and resolution minutes for each priority, for example `30,240`. |

For step-by-step setup guides, see:

- [docs/integrations.md](docs/integrations.md) covers the database (your own server,
  Neon, [Supabase](docs/integrations.md#option-c-supabase-postgres)), email
  ([Gmail SMTP](docs/integrations.md#gmail-or-google-workspace-smtp), Outlook, Brevo,
  Resend), storage ([Supabase Storage](docs/integrations.md#supabase-storage-free-1-gb),
  S3, R2), AI, and
  [Google sign-in](docs/integrations.md#5-sign-in-with-google-optional).
- [docs/deploy-ec2.md](docs/deploy-ec2.md) deploys the whole backend (API, worker and
  HTTPS) to one AWS EC2 server with Docker, step by step, building on the server.
- [docs/deployment.md](docs/deployment.md) is a one-time production setup: the web app on
  Vercel, and the API and worker in Docker behind Caddy.
- [docs/runbook.md](docs/runbook.md) covers day-to-day operations and fixes for common
  symptoms.

After changing `.env`, restart the API and the worker, then run `make check` (or
`python -m app.scripts.check_integrations` in `backend/`). It tests the database, email,
storage, AI and Supabase settings. Add `to=you@example.com` to also send a test email.

## Using Supabase

Tasky can use one Supabase project for its database and file storage:

- **Database:** paste the Postgres connection string into `DATABASE_URL`, using the
  `postgresql+psycopg://` prefix and `?sslmode=require`. Use the **direct connection**
  or the **session pooler**, not the transaction pooler on port 6543, because live
  updates rely on `LISTEN/NOTIFY`. Then run `alembic upgrade head`.
- **Attachments and profile photos:** create a **private** bucket, enable Storage's S3
  connection, and set `STORAGE_BACKEND=s3` with the `S3_*` values it gives you.
- **Auth mirroring (optional):** set `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY`, and
  accounts are copied into Authentication → Users. Tasky still handles sign-in itself.

The full walkthrough is in [docs/integrations.md](docs/integrations.md).

## Development

### Project layout

```text
backend/
  app/
    routers/        HTTP only: parse the request, call a service, shape the response
    services/       business rules: lifecycle, permissions, SLA, teams, audit, AI, auth
    models/         SQLAlchemy models (tasks, teams, users, notifications, attachments, AI)
    repositories/   database queries
    schemas/        Pydantic request and response models
    notifications/  worker, outbox delivery, recipients, email templates, SLA checker
    realtime/       NOTIFY on commit, LISTEN broker for server-sent events
    ai/             providers, prompts, rule engine, read-only tools
    storage/        local disk and S3 (a built-in SigV4 signer)
    core/           config, security, errors, rate limits, logging, metrics
    scripts/        seed, check_integrations, export_openapi
  alembic/          migrations
  evals/            triage accuracy harness
  tests/            pytest suite (real PostgreSQL)
frontend/
  src/
    app/            routes and the app shell (sidebar, palette, shortcuts)
    features/       dashboard, incidents (tasks), teams, notifications, ai, admin, auth, settings, ...
    api/            generated OpenAPI types, typed client, TanStack Query hooks
    components/     shared UI pieces
    auth/, team/    session and current-team providers
    lib/, styles/   theme, motion, live updates, formatting, design tokens
  e2e/              Playwright smoke tests
deploy/             Caddyfile and server bootstrap
docs/               integrations, deployment, runbook, security, ADRs
```

Internally, the task model, API routes (`/api/v1/incidents`) and some folders still use
the name "incident" from before the product was renamed. In the UI and in emails, they
are tasks.

### Common commands

Run `make help` to see every target.

| Command | What it does |
| --- | --- |
| `make lint` | Ruff, mypy (strict), ESLint, `tsc` and a Prettier check |
| `make format` | Auto-format the backend and frontend |
| `make test` | Backend and frontend tests |
| `make test-backend` / `make test-frontend` | One suite at a time |
| `make gen-client` | Regenerate `frontend/openapi.json` and the TypeScript API types |
| `make e2e` | Playwright smoke tests against the running dev stack |
| `make check` | Check the database, email, storage and AI settings in `.env` |
| `make migration m="..."` / `make migrate` | Create or apply a migration inside Docker |

### After changing the API

The frontend's API types are generated from the backend's OpenAPI schema. After you
change a router or schema, run:

```bash
make gen-client
```

CI fails if the generated client is out of date.

### Migrations

From `backend/`, with the venv active:

```bash
alembic revision --autogenerate -m "add due date reminders"
alembic upgrade head
```

Review each autogenerated file before committing it.

## Testing

**Backend.** The tests run against a real PostgreSQL database and **truncate its
tables**, so always point them at a separate test database:

```bash
cd backend
DATABASE_URL=postgresql+psycopg://app:app@localhost:5432/test pytest
```

```powershell
cd backend
$env:DATABASE_URL = "postgresql+psycopg://app:app@localhost:5432/test"; .venv\Scripts\pytest.exe
```

If `DATABASE_URL` is not set in the environment, the database tests are skipped and the
pure unit tests still run. With Docker, first create the test database with
`docker compose exec db createdb -U app test`. `make test-fast` skips the slow tests.

**Frontend:**

```bash
cd frontend
npm test -- --run
```

**End-to-end.** Start the API, the worker and `npm run dev` on seeded demo data with
`DEMO_MODE=true`, because the tests sign in with the demo buttons. Also raise
`LOGIN_RATE_LIMIT_PER_MIN` (for example to 100). Then run:

```bash
cd frontend
npx playwright test
```

The tests use any installed Chrome, Edge or Brave, plus a Pixel 7 phone viewport. Set
`PW_ALL_BROWSERS=1` after `npx playwright install firefox webkit` to add Firefox and
WebKit.

## Security

For the full checklist with evidence, see [docs/security.md](docs/security.md). In
short:

- Passwords are hashed with **Argon2id**.
- Access tokens are short-lived (15-minute) JWTs. Refresh tokens **rotate** on every use,
  and reusing an old one revokes all of that user's sessions. The refresh token lives in
  an **httpOnly**, SameSite=Strict cookie.
- Sign-in, registration and password reset requests are **rate-limited** per IP, and AI
  calls per user, with a daily cap.
- **Team isolation:** every query is scoped to the current team, and admin rights end
  at the team boundary.
- Google sign-in uses a **signed, httpOnly state cookie and PKCE**, and only trusts
  emails that Google has verified.
- Uploads are **checked by their content**, not by file name or header. The server
  accepts only an allow-list of types, refuses SVG and HTML, and serves files through
  short-lived signed links.
- Markdown is sanitised, email templates are auto-escaped, and errors never include
  stack traces.
- **Secrets are never committed:** `.env` is git-ignored, and gitleaks, `pip-audit` and
  `npm audit` run in CI.

## Troubleshooting

**"Address already in use" on port 8000 (Windows).** A previous uvicorn or worker
process is still running. Stop them all with:

```powershell
Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*uvicorn*app.main*' -or $_.CommandLine -like '*app.notifications.worker*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
```

**New features or fixes don't show up.** Restart both the API and the worker, because
the worker does not reload on its own. Run uvicorn with `--reload` during development so
the API picks up code changes.

**Emails are not arriving.**
1. Check the spam folder.
2. Make sure the worker is running, because emails are only sent by the worker.
3. Open **Team admin → Email outbox**. It shows whether the worker is healthy, which
   emails failed and why, and a **Retry** button.

If you use Gmail, you need an app password; see
[docs/integrations.md](docs/integrations.md#gmail-or-google-workspace-smtp).

**Google sign-in fails with `redirect_uri_mismatch`.** In the Google Cloud console,
add this exact URI to the OAuth client's *Authorised redirect URIs*:
`http://localhost:5173/api/v1/auth/google/callback` (in production, use your app domain
followed by `/api/v1/auth/google/callback`).

**A psycopg error about `ProactorEventLoop` on Windows.** Start uvicorn with
`--loop asyncio:SelectorEventLoop`, as shown in [Quick start](#option-b-without-docker-windows-macos-linux).

**"Continue with Google" is missing.** Set both `GOOGLE_CLIENT_ID` and
`GOOGLE_CLIENT_SECRET`, then restart the API.
