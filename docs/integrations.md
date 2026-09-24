# Connecting real services

How to run Tasky on a real database, real email, real file storage and (optionally)
a real LLM instead of the local defaults. Every service below has a free tier.

Everything is configured in `.env` at the repo root (copy `.env.example`). After each
change, restart the API and the worker, then prove the connection:

```bash
cd backend
python -m app.scripts.check_integrations
python -m app.scripts.check_integrations --send-test-email you@company.com
```

It prints `ok` / `warn` / `FAIL` per service with the reason, cleans up after itself, and
exits with 1 on any failure, so it also works in a deploy script.

| Area | Local default | Real options (this guide) |
| --- | --- | --- |
| Database | PostgreSQL on localhost | Your own PostgreSQL, **Neon**, **Supabase** |
| Email | `console` (logged only) or Mailpit | **Gmail**, **Outlook / Microsoft 365**, any SMTP, **Brevo** API, **Resend** API |
| Attachments | Local disk (`.data/attachments`) | **Supabase Storage**, **AWS S3**, **Cloudflare R2**, MinIO |
| AI | `rules` (offline) or off | **Groq**, **Google Gemini**, **Ollama** |
| Errors | logs only | **Sentry** |

---

## 1. Database (PostgreSQL 16)

The app needs PostgreSQL 14 or newer with the `citext` and `pg_trgm` extensions (the
first migration enables them; managed providers allow both). The URL always uses the
`postgresql+psycopg://` driver prefix.

### Option A: your own server

```sql
-- as a superuser
CREATE ROLE incident_desk LOGIN PASSWORD 'a-long-random-password';
CREATE DATABASE incident_desk OWNER incident_desk;
```

```dotenv
DATABASE_URL=postgresql+psycopg://incident_desk:a-long-random-password@db.internal:5432/incident_desk
```

### Option B: Neon (free, serverless)

1. Create a project at neon.tech, in a region near your API server.
2. Dashboard -> **Connection string** -> copy the `postgresql://...` URL.
3. Change the scheme to `postgresql+psycopg://`, keep `?sslmode=require`, and drop
   `&channel_binding=require` if it is present:

```dotenv
DATABASE_URL=postgresql+psycopg://user:password@ep-cool-name-123456.ap-southeast-1.aws.neon.tech/neondb?sslmode=require
```

Use the **direct** host, not the `-pooler` one. The app keeps its own pool, and
live updates use `LISTEN/NOTIFY`, which a transaction pooler does not support.

### Option C: Supabase Postgres

Project -> **Connect** -> **Direct connection** (or the **Session pooler** on IPv4-only
networks; never the transaction pooler on port 6543, for the same `LISTEN` reason):

```dotenv
DATABASE_URL=postgresql+psycopg://postgres:your-db-password@db.abcdefghijkl.supabase.co:5432/postgres?sslmode=require
```

### Create the schema, then sign up

```bash
cd backend
alembic upgrade head                      # creates every table
```

There is no platform-wide admin. Open the app, **sign up** (or continue with Google), and
**create a team**: whoever creates a team is its admin. Others sign up and ask to join; the
team's admins get an email, approve them as members or viewers (or make co-admins), and
can add existing accounts directly under **Team -> Members**. Each team's admins also see
its email outbox and configuration.

> The **demo seed** (`make seed`) creates five accounts with the public password
> `demo1234` and 25 made-up incidents. It is for demos only, and it refuses to run
> against `APP_ENV=production` without `--allow-production`. Use a separate, empty
> database for real data; do not seed it.

**Backups:** Neon and Supabase keep point-in-time history (Neon's free tier: 24 hours).
For your own server, schedule `pg_dump --format=custom`.

---

## 2. Email

Tasky sends email on assignment, resolution, comments, `@mentions` and SLA
breaches, through a transactional outbox: the worker (`python -m
app.notifications.worker`) delivers it and retries failures for about 15 minutes. **The
worker must be running**, or emails wait in Admin -> Email outbox.

Common to every provider:

```dotenv
EMAIL_FROM="Tasky <alerts@yourdomain.com>"   # must be allowed by the provider
APP_BASE_URL=https://incidents.yourdomain.com       # links in emails point here
```

### Gmail or Google Workspace (SMTP)

1. Turn on **2-Step Verification** for the Google account.
2. Create an **App password**: Google Account -> Security -> App passwords.
3. Configure it; `EMAIL_FROM` must be that Gmail address or a verified alias:

```dotenv
EMAIL_PROVIDER=smtp
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_STARTTLS=true
SMTP_SSL=false
SMTP_USERNAME=you@gmail.com
SMTP_PASSWORD=abcd efgh ijkl mnop        # the 16-character app password
EMAIL_FROM="Tasky <you@gmail.com>"
```

Port 465 also works with `SMTP_PORT=465`, `SMTP_SSL=true`, `SMTP_STARTTLS=false`. Gmail
allows about 500 recipients per day on a personal account.

### Outlook.com / Microsoft 365 (SMTP)

```dotenv
EMAIL_PROVIDER=smtp
SMTP_HOST=smtp.office365.com
SMTP_PORT=587
SMTP_STARTTLS=true
SMTP_USERNAME=alerts@yourcompany.com
SMTP_PASSWORD=...
EMAIL_FROM="Tasky <alerts@yourcompany.com>"
```

Microsoft 365 tenants often disable **SMTP AUTH** for mailboxes. An admin has to enable
it for the sending mailbox (Microsoft 365 admin center -> user -> Mail -> Manage email
apps -> Authenticated SMTP), and accounts with MFA need an app password. If your tenant
does not allow it, use Brevo or Resend below.

### Any other SMTP server

Set `SMTP_HOST`, `SMTP_PORT` (587 with `SMTP_STARTTLS=true`, or 465 with `SMTP_SSL=true`),
and `SMTP_USERNAME` / `SMTP_PASSWORD`. For local testing, Mailpit
(`docker compose up mailpit`, UI at http://localhost:8025) accepts anything on port 1025
with no login.

### Brevo (HTTPS API; recommended for servers)

AWS EC2 blocks outbound port 25 by default, and some hosts block SMTP ports altogether.
An HTTPS API needs no open mail ports at all.

1. Sign up at brevo.com (free: 300 emails/day).
2. **Senders, domains & dedicated IPs** -> add and verify the sender address in `EMAIL_FROM`
   (or authenticate your whole domain for better deliverability).
3. **SMTP & API -> API keys** -> create a key.

```dotenv
EMAIL_PROVIDER=brevo
BREVO_API_KEY=xkeysib-...
EMAIL_FROM="Tasky <alerts@yourdomain.com>"
```

### Resend (HTTPS API)

1. Sign up at resend.com (free: 3,000 emails/month, 100/day).
2. **Domains** -> add your domain and create the DNS records it shows. Until then you can
   only send from `onboarding@resend.dev` to your own address.
3. **API keys** -> create one. A "Sending access" key is enough; the check then needs
   `--send-test-email` to verify it.

```dotenv
EMAIL_PROVIDER=resend
RESEND_API_KEY=re_...
EMAIL_FROM="Tasky <alerts@yourdomain.com>"
```

### Deliverability with your own domain

When sending from `@yourdomain.com`, publish the **SPF** and **DKIM** records the provider
gives you (and a `DMARC` record, e.g. `v=DMARC1; p=none`). Without them, mail lands in
spam. The app already sets `Date` and `Message-ID`, sends text + HTML, and escapes user
content.

---

## 3. Attachment storage

Local disk is fine for one server with a persistent volume (`STORAGE_DIR`, or the
`attachments` Docker volume). For anything else, use an S3-compatible bucket; the app
signs requests itself (AWS SigV4), so no SDK is needed. **Keep the bucket private.**
Downloads always go through short-lived signed links.

### Supabase Storage (free: 1 GB)

1. Project -> **Storage** -> **New bucket** `attachments`, **Public: off**.
2. **Storage -> Settings -> S3 connection**: enable it, note the **endpoint** and
   **region**, and create an **access key**.

```dotenv
STORAGE_BACKEND=s3
S3_ENDPOINT=https://abcdefghijkl.supabase.co/storage/v1/s3
S3_REGION=ap-south-1
S3_BUCKET=attachments
S3_ACCESS_KEY=...
S3_SECRET_KEY=...
```

### AWS S3

1. Create a bucket with **Block all public access** on.
2. Create an IAM user (or role) with only this policy:

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": ["s3:PutObject", "s3:GetObject", "s3:DeleteObject"],
    "Resource": "arn:aws:s3:::your-bucket/*"
  }]
}
```

```dotenv
STORAGE_BACKEND=s3
S3_ENDPOINT=https://s3.ap-south-1.amazonaws.com
S3_REGION=ap-south-1
S3_BUCKET=your-bucket
S3_ACCESS_KEY=AKIA...
S3_SECRET_KEY=...
```

### Cloudflare R2 (free: 10 GB, no egress fees)

R2 -> create bucket -> **Manage R2 API tokens** -> "Object Read & Write" for that bucket.

```dotenv
STORAGE_BACKEND=s3
S3_ENDPOINT=https://<account-id>.r2.cloudflarestorage.com
S3_REGION=auto
S3_BUCKET=attachments
S3_ACCESS_KEY=...
S3_SECRET_KEY=...
```

Files already uploaded to local disk are not copied automatically when you switch. Move
them with any S3 tool (e.g. `aws s3 sync .data/attachments s3://your-bucket`); the object
keys are the same.

---

## 4. AI (optional)

| `LLM_PROVIDER` | What it needs | Notes |
| --- | --- | --- |
| `none` | nothing | AI panels hidden; everything else works |
| `rules` | nothing | Offline rule engine; no data leaves the server |
| `groq` | `LLM_API_KEY` from console.groq.com (free) | Default model `llama-3.3-70b-versatile` |
| `gemini` | `LLM_API_KEY` from aistudio.google.com (free tier) | Default `gemini-2.0-flash`; set `LLM_MODEL` to change |
| `ollama` | `ollama serve` + `ollama pull llama3.1` | `LLM_BASE_URL=http://localhost:11434/v1`; fully local |

```dotenv
LLM_PROVIDER=groq
LLM_API_KEY=gsk_...
# LLM_MODEL=llama-3.3-70b-versatile   # optional override
```

With a model configured, the rule engine still answers whenever the model is slow,
rate-limited or returns something invalid. To see the difference on your data, run
`python -m evals.triage_eval --engine llm`.

---

## 5. Sign in with Google (optional)

The sign-in page shows **Continue with Google** once both keys are set. The server runs
the OAuth code flow itself (with PKCE and a signed state cookie); no Google script loads
in the browser. Google accounts are matched by Google's id, then by a *verified* email,
so someone who registered with a password can later use Google for the same account.

1. [console.cloud.google.com](https://console.cloud.google.com) -> create (or pick) a project.
2. **APIs & Services -> OAuth consent screen**: user type **External**, app name
   "Tasky", your support email. Scopes: `openid`, `email`, `profile` (no sensitive
   scopes, so no verification review). While in **Testing**, add your testers' Gmail
   addresses under *Test users*; choose **Publish app** when everyone should be able to sign in.
3. **APIs & Services -> Credentials -> Create credentials -> OAuth client ID**, type
   **Web application**. Under *Authorised redirect URIs* add exactly:
   - local: `http://localhost:5173/api/v1/auth/google/callback`
   - production: `https://<your app domain>/api/v1/auth/google/callback`
4. Copy the client ID and secret into `.env`, then restart the API:

```dotenv
GOOGLE_CLIENT_ID=1234567890-abc.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=GOCSPX-...
# GOOGLE_REDIRECT_URI=...   # only if it is not APP_BASE_URL + /api/v1/auth/google/callback
```

New Google users are created only while `ALLOW_SELF_REGISTER=true`; otherwise an admin
adds them first. Failures come back to `/login?error=<code>` with a readable message.

### Show accounts in Supabase -> Authentication -> Users (optional)

The app does its own sign-in and keeps accounts in its `users` table (Supabase: **Table
Editor -> public -> users**). To also list them on Supabase's **Authentication -> Users**
page, set:

```dotenv
SUPABASE_URL=https://<project-ref>.supabase.co
SUPABASE_SERVICE_ROLE_KEY=...   # Project Settings -> API Keys -> service_role (secret)
```

Every new account (email or Google) is then copied right after sign-up, and the worker
copies anything missing every `SUPABASE_AUTH_SYNC_SECONDS` (60), including accounts that
existed before. The copies are **for display only**: no password is sent, they cannot sign
in, and edits or deletions in the Supabase dashboard do not change the app's accounts.
`make check` confirms the key works.

---

## 6. Error tracking (optional)

Create a Python project at sentry.io and set `SENTRY_DSN=https://...@o0.ingest.sentry.io/0`.
Unhandled errors are reported there as well as in the logs.

---

## 7. Going live with real data: checklist

```dotenv
APP_ENV=production
JWT_SECRET=<openssl rand -hex 32>
DEMO_MODE=false                  # no demo buttons, no public password on the login page
ALLOW_SELF_REGISTER=false        # only admins add people (or true for an open team)
CORS_ORIGINS=https://incidents.yourdomain.com
APP_BASE_URL=https://incidents.yourdomain.com
DATABASE_URL=postgresql+psycopg://...          # section 1, an empty database
EMAIL_PROVIDER=brevo                           # section 2
STORAGE_BACKEND=s3                             # section 3
```

1. `alembic upgrade head` (the API also runs it on start).
2. Sign up in the app and create your team (you become its admin).
3. Start the API **and** the worker.
4. `python -m app.scripts.check_integrations --send-test-email you@company.com`: everything `ok`.
5. As the team's admin, open **Configuration** to confirm the SLA targets and features,
   and add people under **Team -> Members** (or approve their join requests).

The app refuses to start in production with the default `JWT_SECRET`, a `*` CORS
origin, or a provider without its key, so a half-configured deploy fails loudly
instead of quietly.
