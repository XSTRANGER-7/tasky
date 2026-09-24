# Operations runbook

What to do when something is wrong with Tasky itself. One-time setup is in
[deployment.md](deployment.md). All commands run on the instance in `~/incident-desk`;
`dc` below means `docker compose -f docker-compose.prod.yml`.

## First look (2 minutes, any problem)

1. `curl -fsS https://<API_DOMAIN>/health`: `db` must be `ok`; `worker.status` should be
   `ok` (`stale` means the worker has not written a heartbeat for 2 minutes).
2. `dc ps`: every service `running` / `healthy`.
3. `dc logs --tail=200 api worker`: errors are JSON lines with `level=error` and a
   `request_id`. A user's error toast shows the same `req_...`, so
   `dc logs api | grep req_<id>` finds their exact request.

## Symptoms

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| `/health` 503, `db` not ok | Neon suspended or unreachable; bad `DATABASE_URL` | Check the Neon console (free projects wake on the first connection, a few seconds); verify `sslmode=require`; `dc restart api worker` |
| Emails not arriving | Worker down, provider rejecting, daily quota used | Admin -> Email outbox: *Worker* card and *Failed* tab show the last error. `stale` -> `dc restart worker`. `HTTP 401` -> rotate `BREVO_API_KEY`. After fixing, press **Retry** on failed rows (they are kept, never lost) |
| Outbox *Pending* keeps growing | Provider rate limit or outage | Nothing to do: rows retry with backoff (1, 2, 4, 8 min) and fail after 5 tries, then **Retry**. Brevo's free limit is 300/day |
| No live updates ("Live updates paused") | SSE blocked by a proxy, API restarting | Check the Caddyfile still has `flush_interval -1` (SSE must not be buffered); the page still works and refetches on reconnect |
| Uploads fail with `storage_error` | Bucket credentials, bucket deleted, disk full (local) | `dc logs api \| grep attachment_store_failed`; check `S3_*`; for local storage `df -h` and `docker system df` |
| AI chip says "AI unavailable" | Provider timeout, 429, or the daily budget | Nothing breaks: the rule engine answers. Check `dc logs api \| grep ai_unavailable`; lower usage or wait for the quota; `LLM_PROVIDER=rules` removes the dependency |
| Everyone signed out at once | `JWT_SECRET` changed, or refresh-token reuse detected for an account | Expected after a secret rotation; otherwise look for `refresh_token_reuse_detected` in the logs (possible token theft) |
| Disk filling up | Docker images, logs | `docker image prune -af` (old tags); logs are already capped at 10 MB x 3 per container |

## Routine tasks

| Task | How |
| --- | --- |
| Deploy a release | Push a `v*` tag; CI builds the image and runs `dc pull && dc up -d` over SSH. Migrations run on API start |
| Roll back | `TAG=<previous tag> dc up -d`. Migrations are additive; to undo one: `dc exec api alembic downgrade -1` **before** rolling the image back |
| Take someone's access away | A team admin removes them under Team -> Members; they lose that team's incidents at once. To lock an account everywhere: `UPDATE users SET is_active = false WHERE email = '...'` (their tokens stop working within 15 minutes) |
| Rotate `JWT_SECRET` | Set a new value in `.env`, then `dc up -d`. Everyone signs in again; signed file links issued before the rotation stop working |
| Rotate provider keys | Update `.env` (`BREVO_API_KEY`, `S3_*`, `LLM_API_KEY`), then `dc up -d api worker` |
| Restore the database | Neon -> Branches -> restore to a point in time (free tier: 24 h history), or create a branch from that point and switch `DATABASE_URL` to it |
| A team lost its admins | Promote a member in SQL: `UPDATE team_memberships SET role = 'admin' WHERE team_id = '...' AND user_id = '...'` (the app itself never lets the last admin leave) |
| Check every integration | `dc exec api python -m app.scripts.check_integrations --send-test-email you@company.com` |
| Reset a public demo | `dc exec api python -m app.scripts.seed --reset --allow-production` (**deletes all incidents**; never on real data) |
| Check AI quality | Admin -> Configuration -> *AI assistance* shows the accept rate per feature; offline: `python -m evals.triage_eval` |

## Escalation

This is a single-instance deployment. If the EC2 instance itself is gone, launch a new
one from [deployment.md](deployment.md) steps 2, 5 and 6 (about 15 minutes). All state is
in Neon, and attachments are in Supabase Storage, so nothing is lost with the instance.
