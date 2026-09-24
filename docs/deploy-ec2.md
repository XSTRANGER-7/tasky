# Deploy the Tasky backend to AWS EC2 with Docker

This guide puts the whole backend (API, background worker and HTTPS) on one EC2 server
using Docker. The frontend is deployed separately (Vercel), and the database and file
storage stay on Supabase.

- [What is containerized, and how](#what-is-containerized-and-how)
- [Before you start](#before-you-start)
- [Step 1: Launch the EC2 server](#step-1-launch-the-ec2-server)
- [Step 2: Give it a fixed IP address](#step-2-give-it-a-fixed-ip-address)
- [Step 3: Point a domain at it](#step-3-point-a-domain-at-it)
- [Step 4: Connect with SSH from Windows](#step-4-connect-with-ssh-from-windows)
- [Step 5: Prepare the server](#step-5-prepare-the-server)
- [Step 6: Upload the backend](#step-6-upload-the-backend)
- [Step 7: Fill in the production settings](#step-7-fill-in-the-production-settings)
- [Step 8: Build and start](#step-8-build-and-start)
- [Step 9: Check that everything works](#step-9-check-that-everything-works)
- [Step 10: Connect the frontend and Google sign-in](#step-10-connect-the-frontend-and-google-sign-in)
- [Updating and rolling back](#updating-and-rolling-back)
- [Everyday commands](#everyday-commands)
- [Troubleshooting](#troubleshooting)
- [Costs](#costs)

## What is containerized, and how

```text
 Browser ──HTTPS──> Vercel (frontend) ──/api/*──> EC2 :443
                                                   │
                         ┌─────────────────────────┴──────────────── Docker on EC2 ─┐
                         │  caddy   HTTPS certificate (Let's Encrypt), reverse proxy │
                         │    │                                                      │
                         │    ▼                                                      │
                         │  api     FastAPI + uvicorn (2 processes), port 8000       │
                         │          runs database migrations on every start          │
                         │  worker  sends queued emails, checks SLA deadlines,       │
                         │          copies accounts to Supabase Auth                 │
                         └──────────┬───────────────────────────┬──────────────────────┘
                                    ▼                           ▼
                         Supabase Postgres (data)     Supabase Storage (files)   Gmail SMTP
```

| Container | Image | What it runs | Exposed |
| --- | --- | --- | --- |
| `api` | `tasky-api` (built from `backend/Dockerfile`) | `alembic upgrade head`, then `uvicorn app.main:app --workers 2` | only inside Docker (port 8000) |
| `worker` | the same `tasky-api` image | `python -m app.notifications.worker` | nothing |
| `caddy` | `caddy:2.8-alpine` (official) | HTTPS for `API_DOMAIN`, proxies to `api:8000` | ports 80 and 443 |
| `db` (optional) | `postgres:16-alpine` | only with `--profile local-db`, if you do not use Supabase | only inside Docker |

**How the image is built** (`backend/Dockerfile`, multi-stage):

1. **Build stage** on `python:3.12-slim`: creates a virtual environment and installs only
   the runtime dependencies listed in `backend/pyproject.toml`. This layer is cached and
   rebuilt only when the dependency list changes, so code-only updates build in seconds.
2. **Runtime stage** on a fresh `python:3.12-slim`: copies the virtual environment, the
   `app/` code and the `alembic/` migrations. It adds `curl` for the health check, and
   runs as an unprivileged user (`app`, uid 10001), never as root.
3. A **health check** calls `GET /health` every 15 seconds. Compose starts the worker and
   Caddy only once the API reports healthy.

**What is deliberately left out of the image** (`backend/.dockerignore`): `.env` files,
the local virtualenv, caches, tests and evals. Secrets reach the containers only at run
time, from `~/tasky/.env` on the server.

**Files involved**

| File | Purpose |
| --- | --- |
| `backend/Dockerfile` | builds the `tasky-api` image |
| `docker-compose.ec2.yml` | the containers above, built on the server |
| `deploy/Caddyfile` | HTTPS and reverse proxy settings (blocks `/metrics` from the internet) |
| `deploy/.env.production.example` | the production settings template |
| `deploy/ec2-bootstrap.sh` | one-time server setup: Docker, swap, log rotation, SSH hardening, automatic security updates |
| `deploy/package.ps1` | Windows: packs (and optionally uploads) exactly what the server needs |
| `deploy/deploy.sh` | on the server: checks `.env`, builds, starts, waits for health, prints the result |

> `docker-compose.prod.yml` is the alternative for a CI setup: GitHub Actions builds the
> image and the server pulls it from GitHub's registry. Use it once the code is on
> GitHub. This guide builds on the server, which needs nothing but the server itself.

## Before you start

Have these ready:

- **An AWS account.**
- **Supabase**:
  - **The Session pooler connection string** (Supabase → **Connect** → **Session pooler**).
    Do not use the direct `db.<ref>.supabase.co` address: Supabase serves it over IPv6
    only, and EC2 and Docker use IPv4 by default.
  - **The database password.**
  - **The Storage S3 keys** (Storage → Settings → S3 access keys).
- **A Gmail app password** (Google Account → Security → 2-Step Verification → App
  passwords), if you send email through Gmail.
- **A domain name for the API**, or use the free `sslip.io` option in step 3.
- **Where your frontend will live** (e.g. `https://tasky-yourname.vercel.app`).

## Step 1: Launch the EC2 server

In the AWS console, open **EC2 → Instances → Launch instances**:

1. **Name**: `tasky-backend`.
2. **Region** (top right): pick the one closest to your Supabase project's region. Every
   database query crosses between them, so nearer is faster.
3. **Application and OS image**: **Ubuntu Server 24.04 LTS**, 64-bit (x86).
4. **Instance type**: **t3.small** (2 GB RAM) is recommended. **t3.micro** (1 GB, free tier)
   also works: the bootstrap adds 2 GB of swap for the image build.
5. **Key pair**: **Create new key pair**, type **ED25519**, format **.pem**. Save the
   downloaded file, e.g. to `C:\keys\tasky.pem`. You cannot download it again.
6. **Network settings → Edit**, create a security group `tasky-backend` with:

   | Type | Port | Source | Why |
   | --- | --- | --- | --- |
   | SSH | 22 | **My IP** | your admin access only |
   | HTTP | 80 | Anywhere (0.0.0.0/0) | Let's Encrypt check and the redirect to HTTPS |
   | HTTPS | 443 | Anywhere (0.0.0.0/0) | the API |

   Do **not** open port 8000: the API is only reachable through Caddy.
7. **Storage**: **20 GiB**, **gp3**.
8. **Launch instance**.

## Step 2: Give it a fixed IP address

A normal EC2 public IP changes when the server stops. Give it a permanent one:

1. **EC2 → Network & Security → Elastic IPs → Allocate Elastic IP address → Allocate**.
2. Select it, **Actions → Associate Elastic IP address**, choose the `tasky-backend`
   instance, **Associate**.
3. Note the address, e.g. `13.201.45.7`. The rest of this guide calls it `<elastic-ip>`.

## Step 3: Point a domain at it

Caddy needs a domain name to get an HTTPS certificate. Pick one option:

- **Your own domain.** At your DNS provider, add an **A record** `api` → `<elastic-ip>`.
  Your API domain is then `api.yourdomain.com`.
- **Free, no signup: sslip.io.** Write the IP with dashes: `13-201-45-7.sslip.io` already
  points to `13.201.45.7`. Nothing to set up.
- **Free subdomain: DuckDNS.** Sign in at duckdns.org, create `yourname.duckdns.org` and
  set its IP to `<elastic-ip>`.

Check it from PowerShell: `nslookup api.yourdomain.com` must show `<elastic-ip>`.

## Step 4: Connect with SSH from Windows

Windows 10 and 11 include `ssh` and `scp`. OpenSSH refuses keys that other users can
read, so lock the key file first (PowerShell):

```powershell
icacls C:\keys\tasky.pem /inheritance:r
icacls C:\keys\tasky.pem /grant:r "$($env:USERNAME):(R)"
ssh -i C:\keys\tasky.pem ubuntu@<elastic-ip>
```

Answer `yes` to the fingerprint question. Type `exit` to leave.

## Step 5: Prepare the server

From the repository folder on Windows, upload and run the bootstrap script once:

```powershell
cd C:\Users\<you>\Desktop\incident-desk
scp -i C:\keys\tasky.pem deploy\ec2-bootstrap.sh ubuntu@<elastic-ip>:~
ssh -i C:\keys\tasky.pem ubuntu@<elastic-ip> "sudo bash ec2-bootstrap.sh"
```

It takes 2–4 minutes and does the following:
- updates Ubuntu
- installs Docker Engine and the Compose plugin
- adds 2 GB of swap
- turns on log rotation and automatic security updates
- switches SSH to key-only logins (no passwords, no root)
- creates `~/tasky`

It is safe to run again.

## Step 6: Upload the backend

On Windows, this packs `backend/`, `deploy/` and `docker-compose.ec2.yml`. It never
includes `.env` files, the virtualenv or caches. It then uploads the archive and unpacks
it into `~/tasky`:

```powershell
powershell -ExecutionPolicy Bypass -File deploy\package.ps1 -Server <elastic-ip> -Key C:\keys\tasky.pem
```

(Without `-Server` and `-Key` it only creates `tasky-backend.tar.gz`. Upload it yourself
with `scp`, then run `mkdir -p ~/tasky && tar -xzf tasky-backend.tar.gz -C ~/tasky` on the
server.)

## Step 7: Fill in the production settings

SSH in. Log out and back in once after step 5, so your user can run Docker without
`sudo`. Then:

```bash
ssh -i C:\keys\tasky.pem ubuntu@<elastic-ip>
cd ~/tasky
cp deploy/.env.production.example .env
openssl rand -hex 32          # copy the output: it is your JWT_SECRET
nano .env                     # fill in every <...>; Ctrl+O, Enter to save, Ctrl+X to exit
chmod 600 .env                # only you can read it
```

The values that matter most:

| Setting | Example | Notes |
| --- | --- | --- |
| `APP_BASE_URL` | `https://tasky-yourname.vercel.app` | where people open Tasky; used in emails and Google sign-in |
| `CORS_ORIGINS` | same as `APP_BASE_URL` | comma-separated if there are several |
| `API_DOMAIN` | `api.yourdomain.com` or `13-201-45-7.sslip.io` | from step 3; no `https://` |
| `JWT_SECRET` | output of `openssl rand -hex 32` | at least 32 characters; the API refuses to start otherwise |
| `DATABASE_URL` | `postgresql+psycopg://postgres.<ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres?sslmode=require` | the **Session pooler** string. Change `postgresql://` to `postgresql+psycopg://`. URL-encode special characters in the password (`@` → `%40`, `#` → `%23`) |
| `S3_ENDPOINT`, `S3_REGION`, `S3_ACCESS_KEY`, `S3_SECRET_KEY` | from Supabase Storage → Settings | bucket `attachments` must exist |
| `SMTP_USERNAME`, `SMTP_PASSWORD`, `EMAIL_FROM` | your Gmail and its app password | `EMAIL_FROM="Tasky <you@gmail.com>"` |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | from Google Cloud | optional; see step 10 |

`deploy.sh` refuses to start while any `<placeholder>` is left, and the API itself refuses
production settings that are unsafe (a short `JWT_SECRET`, `*` in `CORS_ORIGINS`, or open
sign-up with rate limits turned off).

## Step 8: Build and start

```bash
cd ~/tasky
bash deploy/deploy.sh
```

It does the following:
1. checks `.env`
2. builds the `tasky-api` image: about 3–6 minutes the first time, seconds after that
3. starts `api`, `worker` and `caddy`
4. waits until the API is healthy
5. prints the containers and calls `https://<API_DOMAIN>/health` from the outside

The first time, Caddy fetches the HTTPS certificate, which takes 10–60 seconds.

Expected ending:

```text
==> Public health check: https://api.yourdomain.com/health
{"status":"ok","db":"ok","version":"0.1.0", ...}

Tasky backend is live at https://api.yourdomain.com
```

## Step 9: Check that everything works

```bash
cd ~/tasky
docker compose -f docker-compose.ec2.yml ps              # api "healthy", worker and caddy "running"
docker compose -f docker-compose.ec2.yml exec api python -m app.scripts.check_integrations
docker compose -f docker-compose.ec2.yml exec api python -m app.scripts.check_integrations --send-test-email you@gmail.com
```

`check_integrations` tests the database, email login, storage (write, read and delete a
test file), AI and the worker heartbeat with your real settings, and prints `All good.`
at the end.

From your own computer, `https://<API_DOMAIN>/health` should answer, and
`https://<API_DOMAIN>/docs` shows the API documentation.

## Step 10: Connect the frontend and Google sign-in

The frontend forwards every `/api/*` call to this server (see `frontend/vercel.json`).
Browser and API then share one origin, so the sign-in cookie works without cross-site
settings.

1. In `frontend/vercel.json`, set the rewrite destination to your API domain:

   ```json
   { "source": "/api/:path*", "destination": "https://api.yourdomain.com/api/:path*" }
   ```

2. Deploy the frontend to Vercel as usual (import the repository, root directory
   `frontend`). Its URL must match `APP_BASE_URL` and `CORS_ORIGINS` in the server's
   `.env`; if you change them, run `bash deploy/deploy.sh --no-build`.
3. **Google sign-in** (optional): in Google Cloud → APIs & Services → Credentials → your
   OAuth client, add:
   - Authorised JavaScript origin: `https://tasky-yourname.vercel.app`
   - Authorised redirect URI: `https://tasky-yourname.vercel.app/api/v1/auth/google/callback`
4. Open the frontend, sign up, and create your team.

## Updating and rolling back

After changing backend code on Windows:

```powershell
powershell -ExecutionPolicy Bypass -File deploy\package.ps1 -Server <elastic-ip> -Key C:\keys\tasky.pem
ssh -i C:\keys\tasky.pem ubuntu@<elastic-ip> "cd ~/tasky && bash deploy/deploy.sh"
```

Uploading replaces the code but keeps your `.env`. Database migrations run automatically
when the new API starts.

**Rollback**: each deploy keeps the previous image as `tasky-api:previous`:

```bash
cd ~/tasky
TAG=previous docker compose -f docker-compose.ec2.yml up -d --no-build
```

Rolling back the code does not undo database migrations. That is harmless when the newer
release only added tables or columns; if it removed or renamed something, restore from a
Supabase backup instead.

## Everyday commands

Run on the server, in `~/tasky`. Tip: `alias dc='docker compose -f docker-compose.ec2.yml'`.

| Task | Command |
| --- | --- |
| Status and health | `dc ps` |
| Follow API and worker logs | `dc logs -f --tail 100 api worker` |
| Certificate and proxy logs | `dc logs -f caddy` |
| Restart after editing `.env` | `bash deploy/deploy.sh --no-build` |
| Restart one container | `dc restart worker` |
| Stop everything | `dc down` (data in Supabase is untouched) |
| Open a shell in the API | `dc exec api sh` |
| Disk usage | `df -h` and `docker system df` |
| Free old images | `docker image prune -f` |

The server restarts containers automatically after a crash or a reboot
(`restart: unless-stopped`), and rotates logs at 3 × 10 MB per container.

## Troubleshooting

| Symptom | Cause and fix |
| --- | --- |
| `deploy.sh`: API not healthy, logs show `Network is unreachable` or a timeout to the database | `DATABASE_URL` uses the IPv6-only direct address. Use the Supabase **Session pooler** string |
| `password authentication failed` | wrong password, or special characters not URL-encoded in `DATABASE_URL` |
| `https://<API_DOMAIN>` does not answer, `dc logs caddy` shows certificate errors | the domain does not point at the Elastic IP yet (`nslookup`), or ports 80/443 are closed in the security group. Caddy retries by itself |
| `502 Bad Gateway` | the API is down or restarting: `dc logs --tail 100 api` |
| `permission denied ... docker.sock` | log out and SSH in again after the bootstrap (docker group) |
| Build stops, `Killed` | out of memory on a t3.micro: check `swapon --show` shows the 2 GB swap, or use t3.small |
| Emails not arriving | `dc logs worker`; check the Gmail app password; the Email outbox page in the app (Team admin) shows each email's status and last error |
| Sign-in loops back to the login page | `APP_BASE_URL` / `CORS_ORIGINS` do not match the frontend URL exactly, or `vercel.json` still points at another API domain |
| Google says `redirect_uri_mismatch` | add `<APP_BASE_URL>/api/v1/auth/google/callback` exactly in the Google console |
| SSH: `UNPROTECTED PRIVATE KEY FILE` | run the two `icacls` commands from step 4 |
| API refuses to start: `JWT_SECRET must be set ...` | generate one with `openssl rand -hex 32` |

## Costs

Approximate on-demand prices; check AWS pricing for your region:

| Item | Monthly |
| --- | --- |
| t3.micro (1 GB) | free tier for 12 months, then about $8 |
| t3.small (2 GB) | about $15 |
| 20 GB gp3 disk | about $1.60 |
| Elastic IP attached to a running instance | about $3.60 (AWS charges for all public IPv4 addresses) |
| Data transfer | first 100 GB out per month is free |

Supabase's free tier covers the database and storage for a small team.
