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
| `AIOS_API_URL`, `AIOS_SERVICE_TOKEN` | Sync into the AIOS app. `AIOS_API_URL` is the app's address without `/api` (for example `https://voicent-aios-app-production.up.railway.app`) and must be `https://`. Give this service its own entry in the AIOS app's `SERVICE_TOKENS` so it can be rotated alone |
| `JOBS_ENABLED`, `JOBS_INTERVAL_MINUTES` | The timer for reminders and the AIOS sync. On by default, every 15 minutes. `JOBS_ENABLED=0` turns it off. **Run one instance of this service.** |
| `NUDGE_MAX`, `NUDGE_QUIET_START`, `NUDGE_QUIET_END`, `NUDGE_RETRY_HOURS` | Automatic reminders per onboarding before giving up (3), the night window in the client's local hours (21 to 8), and how long to wait before retrying a failed send (6) |
| `DEFAULT_TIMEZONE`, `BRAND_NAME` | The time zone given to a new client (`America/New_York`) and the name used in reminder messages (`Voicent`) |

Railway passes service variables to the Docker build as build args, so the two `VITE_` ones reach the frontend build. Changing them needs a redeploy.

## First run

1. Create the Supabase project. Note the pooler connection string and JWKS URL.
2. Set the variables above on a new Railway service from this repo. The container runs `alembic upgrade head` before starting.
3. Check `https://<domain>/api/health` returns `{"ok": true}`.
4. In Supabase, create Jay's user (Authentication > Users) and copy their user id. Then run once, against the production database:
   `python -m app.cli seed --org-name Voicent --org-slug voicent --admin-user-id <that id> --admin-email <email>`
   (from a Railway shell, or locally with `DATABASE_URL` set). It creates the org, links the user to it and installs the four preset templates. Safe to run twice.
5. Confirm row level security: the Supabase Data API with the publishable key must return no rows from any table.

## If the admin pages say "Couldn't load ..."

The page now says why. The three usual causes, in the order to check them:

1. **The top right of the page says "local mode".** The site was built without `VITE_SUPABASE_URL` and `VITE_SUPABASE_ANON_KEY`, so it has no sign-in and the server refuses it (401). Set both on the Railway service and **redeploy**; they are baked in at build time, so a restart does nothing.
2. **You signed in but it says the account isn't linked to an organization (403).** Run the seed command in step 4 above with your own Supabase user id. The error message shows your id and the exact command.
3. **It says the server didn't accept your sign-in (401) while a login form was shown.** `SUPABASE_JWKS_URL` (or `SUPABASE_JWT_SECRET` for a legacy project) on Railway doesn't match the Supabase project the site signs in to.

Anything else (status 500, "didn't answer") is in the Railway deploy logs. A wrong `DATABASE_URL` or migrations that didn't finish are the usual causes; the service runs `alembic upgrade head` when it starts.

## Turning reminders and the AIOS sync on

Both are optional and switch themselves off, with a warning in the logs, until their settings are complete.

**Reminders** need `APP_URL` (so a reminder can carry a link) plus Twilio, Resend, or both.
- *Texts:* `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM_NUMBER`. The number must be registered for A2P 10DLC (or be a toll-free number that has passed verification) before real clients are texted. Only contacts with a recorded consent are texted; record it on the client page. Twilio itself stops texts to a number that has replied STOP; the app notices the refusal and withdraws that contact's consent.
- *Email:* `RESEND_API_KEY`, `RESEND_FROM` (an address on a domain verified in Resend).
- Try it without sending anything: `python -m app.cli nudge --dry-run`.
- Each client has a time zone (client page). Nobody is reminded between 9pm and 8am there.

**The AIOS sync** needs `AIOS_API_URL` and `AIOS_SERVICE_TOKEN`, and the same token added to `SERVICE_TOKENS` on the AIOS service. The first time it runs it creates a project for every onboarding that has already been sent. Each onboarding page shows whether it is up to date and has a "Sync now" button.
