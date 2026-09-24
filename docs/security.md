# Security checklist (spec section 13), walked

Every item checked against the code on 2026-09-22. **Done** means it is implemented and
covered by a test or config you can read. **Deploy** means it is a one-time step in
[deployment.md](deployment.md). **Open** means it is not done yet, with the reason.

## Application

| Item | Status | Evidence |
| --- | --- | --- |
| Parameterised queries only; no raw SQL outside migrations | Done | SQLAlchemy ORM/Core everywhere; the only `text()` calls are constant SQL (index predicates, `SELECT 1` health probe, the test/seed `TRUNCATE`) |
| CORS restricted to `CORS_ORIGINS`; credentials only for that origin | Done | `app/main.py`; production refuses `*` (`Settings._production_guards`, `tests/test_config.py`) |
| Rate limits: login 5/min per IP, register 3/min | Done | `app/core/rate_limit.py`, `tests/test_auth.py` |
| Rate limit: AI 10/min per user, plus a daily cap | Done | `app/routers/ai.py` `ai_guard`, `DailyBudget`; `tests/test_ai.py::test_rate_limit_and_daily_budget` |
| Rate limit: everything else 120/min | **Open** | Not implemented. The per-process limiter is the seam; a global per-IP limit needs a carve-out for the long-lived SSE stream. Caddy's rate-limit module is the alternative |
| Security headers: CSP, nosniff, Referrer-Policy, HSTS in production | Done | `app/core/security_headers.py`, `tests/test_request_context.py` |
| Attachments: allow-list (png, jpg, gif, pdf, txt, log, json), 10 MB, random key, presigned URL, never executed | Done | Type sniffed from content (`attachment_service.sniff`); SVG/HTML refused; `sandbox` CSP + `nosniff` + `attachment` disposition; `tests/test_attachments.py` (26 tests); [ADR 0006](adr/0006-attachments-storage.md) |
| User content HTML-escaped in emails | Done | Jinja2 autoescape for `.html.j2`, CR/LF stripped from subjects; `tests/test_email_templates.py` |
| Markdown rendered with a sanitiser | Done | `rehype-sanitize` in `frontend/src/components/MarkdownRenderer.tsx`; a test posts a `<script>` comment and checks that no script element renders |
| Secrets only in env; `.env.example` committed; `.env` ignored | Done | `.gitignore`; production refuses the default `JWT_SECRET` |
| gitleaks in CI | Done (CI) | `.github/workflows/ci.yml` job `security`; `.gitleaks.toml` allowlists only AWS's published SigV4 example key used as a test vector |
| Scan before the first push | Done (manual) | Pattern scan of every file to be committed (AWS/GitHub/Groq/OpenAI/Slack/Resend/Brevo/Google key shapes, private-key headers, hard-coded passwords): no findings. gitleaks itself was not run locally (not installed) |
| Dependency scanning: `pip-audit`, `npm audit --audit-level=high`, Dependabot | Done | CI steps + `.github/dependabot.yml` |
| Non-root user in Docker images | Done | `backend/Dockerfile` (`USER app`, uid 10001); the web image is nginx-unprivileged |
| Read-only filesystem where possible | **Open** | Not set yet. The API only writes to `/data/attachments` (a volume); `read_only: true` with a `tmpfs` for `/tmp` is the next hardening step, but needs testing on the instance first |
| `/metrics` and `/admin/*` not public | Done | Caddy answers 404 for `/metrics` from outside; every `/admin/*` route requires the admin role (`tests/test_notifications.py`, `tests/test_admin_settings_and_watching.py`) |
| Error responses never include stack traces, only `request_id` | Done | `app/core/errors.py`, `tests/test_request_context.py::test_unhandled_error_returns_envelope_with_request_id` |
| Auth: argon2id, 15-min JWT access, rotating refresh with reuse detection, HttpOnly SameSite=Strict cookie | Done | `app/core/security.py`, `app/services/auth_service.py`, `tests/test_auth.py`; [ADR 0003](adr/0003-jwt-access-and-rotating-refresh.md) |
| No demo credentials on real deployments | Done | Demo buttons (public password) only with `DEMO_MODE=true`; the demo seed refuses `APP_ENV=production`; there is no platform-wide admin account at all: each team's creator is its admin, and admin rights stop at that team (`tests/test_teams.py`) |
| Deactivation takes effect at once | Done | Refresh tokens revoked on deactivate; access tokens re-check `is_active` on every request |

## AI (spec 10.3)

| Risk | Status | Control |
| --- | --- | --- |
| Prompt injection in incident text | Done | User text fenced as data with the fence markers escaped; read-only tools only; schema-validated output. Test: `test_prompts_fence_user_text_and_carry_no_secrets` |
| Hallucinated assignee or incident IDs | Done | Checked against the database before display; unknown categories dropped. Test: `test_garbage_and_unknown_ids_never_reach_the_user` |
| Data leakage | Done | No emails, tokens, hashes or attachments sent; internal notes only for users allowed to see them. Test: `test_summary_respects_internal_note_visibility` |
| Cost blow-up | Done | 10/min per user, daily cap (then rules), ~4k-token input cap |
| Provider outage | Done | 20 s timeout, one retry, rule-based fallback with an "AI unavailable" chip |
| Silent wrong suggestions | Done | Confidence shown (warning tone below 0.5); nothing applied without Accept; accept rate per feature on the admin page |

## EC2 hardening (Deploy)

| Item | Where |
| --- | --- |
| Security group 80/443/22 only; API and DB never exposed | deployment.md step 2; the compose file `expose`s 8000 on the Docker network only |
| SSH key-only, no password or root login | `deploy/ec2-bootstrap.sh` writes `sshd_config.d/99-incident-desk.conf` |
| IMDSv2 required; no IAM role on the instance | deployment.md step 2 |
| unattended-upgrades; Docker on boot; `restart: unless-stopped`; memory limits | bootstrap script; `docker-compose.prod.yml` |
| Log rotation 10 MB x 3 | `docker-compose.prod.yml` `logging` |
| Secrets only in the instance `.env` (mode 600) and GitHub Actions secrets | deployment.md steps 6 and 8 |
| Root MFA, IAM user, zero-spend budget | deployment.md step 1 |

The two open items are the next hardening work. Neither is an exposure in the current
deployment: login and AI, the abuse-prone endpoints, are limited, and the containers
already run as non-root.
