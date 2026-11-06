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
| `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `UPLOAD_BUCKET` | File uploads to a **private** bucket. Create the bucket first |
| `LINK_TTL_DAYS` | Magic link lifetime, default 30 |
| `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM_NUMBER` | SMS nudges. Needs a number registered for A2P 10DLC before real clients |
| `RESEND_API_KEY`, `RESEND_FROM` | Email nudges. `RESEND_FROM` must use a domain verified in Resend |
| `AIOS_API_URL`, `AIOS_SERVICE_TOKEN` | Sync into the AIOS app. Give this service its own entry in the AIOS app's `SERVICE_TOKENS` so it can be rotated alone |

Railway passes service variables to the Docker build as build args, so the two `VITE_` ones reach the frontend build. Changing them needs a redeploy.

## First run

1. Create the Supabase project. Note the pooler connection string and JWKS URL.
2. Set the variables above on a new Railway service from this repo. The container runs `alembic upgrade head` before starting.
3. Check `https://<domain>/api/health` returns `{"ok": true}`.
4. In Supabase, create Jay's user, then insert the first `orgs` row and an `org_members` row linking that user. (A seed command arrives with the admin API in phase 2.)
5. Confirm row level security: the Supabase Data API with the publishable key must return no rows from any table.
