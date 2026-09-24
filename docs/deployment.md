# Deployment runbook (one-time setup, ~45 minutes)

Target: SPA on Vercel, API + worker + Caddy on one AWS EC2 t3.micro, Postgres on Neon,
images on GHCR. Out-of-pocket cost 0 (EC2 is covered by new-account credits).

```
Browser --HTML/JS, /api/* REST + cookie--> Vercel --rewrite--> Caddy :443 (EC2) --> api :8000
Browser --SSE (Phase 4, Bearer token)---------------------->  Caddy :443
api, worker --> Neon Postgres          worker --> Brevo (Phase 4)
```

Work through the steps in order; each ends with a check.

## 1. AWS account guardrails

1. Sign up on the AWS **Free plan**.
2. Enable **MFA on the root user**; create an **IAM user** for daily work and stop using root.
3. **AWS Budgets**: create a *zero-spend budget* and a separate **$1 budget** with email alerts.
4. Add a calendar reminder one month before the credit / Free-plan window ends.

Check: both budgets show *OK* in the Budgets console.

## 2. Launch the instance

| Setting | Value |
| --- | --- |
| Region | `ap-south-1` (Mumbai) |
| AMI | Ubuntu Server 24.04 LTS |
| Type | `t3.micro` - confirm the *Free tier eligible* label |
| Storage | 20 GB gp3 |
| Key pair | new, download the `.pem` (never commit it) |
| Advanced -> Metadata | **IMDSv2 required** |
| IAM role | **none** (the app calls no AWS APIs, so a compromised container gets no credentials) |

**Security group** - inbound only:

| Port | Source | Why |
| --- | --- | --- |
| 22/tcp | your IP (preferred) or anywhere, key-only | SSH / deploy |
| 80/tcp | 0.0.0.0/0, ::/0 | Let's Encrypt HTTP challenge + redirect |
| 443/tcp | 0.0.0.0/0, ::/0 | HTTPS |

8000 and 5432 are never opened.

**Elastic IP**: allocate one and associate it with the instance. (It is billed against
credits; release it when the project ends.)

Check: `ssh -i key.pem ubuntu@<elastic-ip>` works.

## 3. Domain (DuckDNS)

1. Sign in at duckdns.org, create a subdomain, e.g. `incident-desk`.
2. Point it at the Elastic IP.

Check: `nslookup incident-desk.duckdns.org` returns the Elastic IP.

## 4. Database (Neon)

1. Create a project (region close to Mumbai, e.g. `aws-ap-southeast-1`).
2. Copy the connection string and convert it to the SQLAlchemy/psycopg form:
   `postgresql+psycopg://<user>:<password>@<host>/<db>?sslmode=require`
3. Nothing else: the baseline migration enables `citext` and `pg_trgm` itself.

Check: from your machine, `psql "<neon url without +psycopg>" -c 'select 1'`.

## 5. Bootstrap the instance

```bash
scp -i key.pem deploy/ec2-bootstrap.sh ubuntu@<elastic-ip>:~
ssh -i key.pem ubuntu@<elastic-ip> 'sudo bash ec2-bootstrap.sh'
```

Installs Docker Engine + compose plugin, rotates container logs (10 MB x 3), creates a
2 GB swap file, enables unattended security upgrades and disables SSH passwords / root
login. Safe to re-run.

Check: log out and back in, then `docker run --rm hello-world`.

## 6. Configure and start

```bash
scp -i key.pem docker-compose.prod.yml ubuntu@<elastic-ip>:~/incident-desk/
scp -i key.pem deploy/Caddyfile ubuntu@<elastic-ip>:~/incident-desk/deploy/
ssh -i key.pem ubuntu@<elastic-ip>
cd ~/incident-desk && nano .env && chmod 600 .env
```

Minimum production `.env`:

```dotenv
APP_ENV=production
GHCR_OWNER=<lowercase github user>
API_DOMAIN=incident-desk.duckdns.org
APP_BASE_URL=https://<app>.vercel.app
CORS_ORIGINS=https://<app>.vercel.app
FORWARDED_ALLOW_IPS=*
DATABASE_URL=postgresql+psycopg://<user>:<password>@<neon-host>/<db>?sslmode=require
JWT_SECRET=<output of: openssl rand -hex 32>
DEMO_MODE=false                  # real data: no demo logins on the sign-in page
ALLOW_SELF_REGISTER=false        # only team admins can create accounts
LOG_LEVEL=info
METRICS_ENABLED=true

# Email (Phase 4): Brevo free tier, 300/day
EMAIL_PROVIDER=brevo
BREVO_API_KEY=<from Brevo -> SMTP & API -> API keys>
EMAIL_FROM="Tasky <alerts@your-verified-sender>"

# Attachments (Phase 6): Supabase Storage via its S3 endpoint (1 GB free)
STORAGE_BACKEND=s3
S3_ENDPOINT=https://<project-ref>.supabase.co/storage/v1/s3
S3_REGION=<the project's region, e.g. ap-south-1>
S3_BUCKET=attachments            # create it as a *private* bucket
S3_ACCESS_KEY=<Storage -> S3 connection -> access key id>
S3_SECRET_KEY=<secret access key>

# AI (Phase 7): rules needs nothing; groq's free tier is the upgrade
LLM_PROVIDER=rules               # or: groq + LLM_API_KEY=<gsk_...>
```

Without `STORAGE_BACKEND=s3`, attachments go to the `attachments` Docker volume on the
instance, which is fine for a demo but lives and dies with that disk.

The first image exists after the first tagged release (step 8). To start before that,
build and push once from your machine, or run step 8 first and come back.

```bash
docker compose -f docker-compose.prod.yml up -d
docker compose -f docker-compose.prod.yml ps
```

Caddy requests the certificate on the first HTTPS request.

Create your admin account and prove every connection (database, email, storage, AI):

```bash
# No admin to create: open the app, sign up, and create your team (you become its admin).
docker compose -f docker-compose.prod.yml exec api python -m app.scripts.check_integrations --send-test-email you@company.com
```

Provider-by-provider setup (Neon, Brevo, Supabase Storage, Groq, ...) is in
[integrations.md](integrations.md). Do not run the demo seed here: it refuses production
unless you pass `--allow-production` for a public demo.

Check: `curl -fsS https://incident-desk.duckdns.org/health` returns
`{"status":"ok","db":"ok",...}` and `curl -I https://.../metrics` returns 404.

## 7. Frontend (Vercel)

1. Import the GitHub repo; **Root Directory** `frontend`; framework preset **Vite**.
2. Edit `frontend/vercel.json` so the `/api/:path*` rewrite points at your `API_DOMAIN`.
3. Environment variables: `VITE_API_URL=/api/v1` and (Phase 4)
   `VITE_STREAM_URL=https://<API_DOMAIN>/api/v1/events/stream`.

Check: the Vercel URL shows the status page with *All systems operational*
(it calls `/api/v1/health` through the rewrite).

## 8. CI deploy access

Repository -> Settings -> Secrets and variables -> Actions:

| Secret | Value |
| --- | --- |
| `EC2_HOST` | the Elastic IP |
| `EC2_SSH_KEY` | a **deploy-only** private key whose public half is in `~/.ssh/authorized_keys` on the instance |
| `API_DOMAIN` | e.g. `incident-desk.duckdns.org` |

Also create a `production` environment (Settings -> Environments) - the deploy job uses it.
If the GHCR package is private, `docker login ghcr.io` on the instance once with a
read-only token (or make the package public: it contains no secrets).

```bash
git tag v0.1.0 && git push origin v0.1.0
```

Check: the *deploy* workflow is green and its last step printed the public `/health`.

## 9. Uptime monitor

cron-job.org (free): GET `https://<API_DOMAIN>/health` every 5 minutes, email on failure.

## Phase 0 exit checklist

- [ ] `docker compose up` works locally; http://localhost:5173 shows *All systems operational*
- [ ] CI green on `main` (backend, frontend, secret scan, compose smoke)
- [ ] `https://<API_DOMAIN>/health` returns 200 from the internet
- [ ] Vercel URL reaches the API through the rewrite
- [ ] AWS budget alerts active
- [ ] Instance rebooted once; every container came back on its own

## Operations

| Task | Command (on the instance, in `~/incident-desk`) |
| --- | --- |
| Status | `docker compose -f docker-compose.prod.yml ps` |
| Logs | `docker compose -f docker-compose.prod.yml logs -f --tail=100 api worker` |
| Find one request | `docker compose -f docker-compose.prod.yml logs api \| grep req_<id>` |
| Roll back | `TAG=<previous tag> docker compose -f docker-compose.prod.yml up -d` |
| Restart | `docker compose -f docker-compose.prod.yml restart api worker` |
