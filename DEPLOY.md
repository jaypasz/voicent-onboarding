# Deploy: Railway + Supabase

One Railway service builds the `Dockerfile` (React build, then FastAPI serving the app and `/api`). Supabase supplies Postgres, admin login and file storage. `railway.json` sets the health check (`/api/health`). Not deployed yet.

## Variables (Railway service > Variables)

| Variable | Value |
|---|---|
| `APP_ENV` | `production` (never set `AUTH_DISABLED`) |
| `DATABASE_URL` | Supabase Postgres pooler URI (transaction mode, port 6543, or session mode, port 5432). `postgresql://` is fine |
| `SUPABASE_JWKS_URL` | `https://<project>.supabase.co/auth/v1/.well-known/jwks.json` |
| `SUPABASE_JWT_SECRET` | Only for projects still on the legacy HS256 secret. Either this or the JWKS URL is enough |
| `SERVICE_TOKENS` | random, 24+ chars each, comma-separated |
| `APP_URL` | the service's public URL (Railway default domain for now). Builds client links |
| `CORS_ORIGINS` | same URL as `APP_URL` |
| `VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY` | Build-time, baked into the frontend for admin login. The anon or publishable key is public by design |

Optional (each switches off with a warning when half-set):

| Variable | Feature |
|---|---|
| `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `UPLOAD_BUCKET` | File uploads to a **private** bucket (default name `onboarding-files`). Create the bucket first, and set its file size limit and allowed types there as a second line of defence. Not verified against live Supabase yet |
| `PORTAL_SIGNING_KEY` | Random, 24+ chars. Signs client sessions. Without it a random key is used and clients reopen their link after every restart |
| `LINK_TTL_DAYS`, `SESSION_TTL_MINUTES` | Magic link lifetime (default 30 days) and client session lifetime (default 30 minutes) |
| `RATE_EXCHANGE_PER_IP`, `RATE_EXCHANGE_GLOBAL`, `RATE_WRITES_PER_LINK` | Portal rate limits per minute (defaults 20, 300, 60) |
| `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM_NUMBER` | SMS nudges. Needs a number registered for A2P 10DLC before real clients |
| `RESEND_API_KEY`, `RESEND_FROM` | Email nudges. `RESEND_FROM` must use a domain verified in Resend |
| `AIOS_API_URL`, `AIOS_SERVICE_TOKEN` | Sync into the AIOS app. Give this service its own entry in the AIOS app's `SERVICE_TOKENS` so it can be rotated alone |

Railway passes service variables to the Docker build as build args, so the two `VITE_` ones reach the frontend build. Changing them needs a redeploy.

## First run

1. Create the Supabase project. Note the pooler connection string and JWKS URL.
2. Set the variables above on a new Railway service from this repo. The container runs `alembic upgrade head` before starting.
3. Check `https://<domain>/api/health` returns `{"ok": true}`.
4. In Supabase, create Jay's user (Authentication > Users) and copy their user id. Then run once, against the production database:
   `python -m app.cli seed --org-name Voicent --org-slug voicent --admin-user-id <that id> --admin-email <email>`
   (from a Railway shell, or locally with `DATABASE_URL` set). It creates the org, links the user to it and installs the four preset templates. Safe to run twice.
5. Confirm row level security: the Supabase Data API with the publishable key must return no rows from any table.
