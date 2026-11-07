# CLAUDE.md

Guidance for Claude Code (claude.ai/code) when working in this repository.

## What this is

**Voicent Onboarding** is Jay's internal client onboarding app, in the style of Launchpad. Jay creates a client, picks a template, and sends the client a magic link. The client works through steps (forms, uploads, connect an integration, book a call, approve a deliverable) and Jay watches progress. Each onboarding mirrors into the AIOS app as a project with tasks.

One data-driven engine serves a plumber (one question per screen, on a phone) through an agency or MSP (full checklist, several contacts, approvals). The difference lives in the template, never in code.

Plan and rationale: `plans/2026-11-06-client-onboarding-app.md` in the `jaypasz/voicent-aios` workspace repo. It is the source of truth for scope and phases.

## State

Phases 1 to 4 done: scaffold, data model, migrations with row level security, auth, the template schema and YAML loader, four presets, the six v1 step types, services and the admin API (clients, templates, onboardings, steps, comments), `python -m app.cli seed`, the magic-link client portal API (`/api/portal`: exchange, session, view, answer, comment, upload URL), admin link controls, and file uploads to a private Supabase Storage bucket. The client portal UI (focus and checklist layouts, one renderer per step type) and the admin app (onboardings, clients and contacts, templates with YAML import, onboarding detail with answers, files, comments and link controls, new onboarding). Reminders for clients who go quiet (text through Twilio, email through Resend; never at night, a capped number of times, a flag for Jay when they give up) and a one-way sync of each onboarding into the AIOS board (one project, one task per step), both run by a timer inside the web process. Not built yet: the Voicent-App provisioning hook (Step 11), the template GUI builder (v2). **Not verified against the real services: Twilio, Resend, the AIOS app, Supabase login, uploads to Supabase Storage. All of those were tested against fakes of their APIs.**

## Layout

- `backend/` — Python 3.13, FastAPI + SQLAlchemy 2 + Alembic. `app/` holds `main.py` (app factory), `config.py`, `db.py`, `models.py`, `auth.py`, `deps.py` (incl. `current_org`), `redact.py`, `errors.py`, `services.py` (all the rules), `portal.py` (what a client may see and do), `magic_link.py`, `ratelimit.py`, `storage.py`, `notify.py` (Twilio and Resend senders), `nudges.py` (who gets reminded and when), `aios.py` (client for the AIOS REST API), `aios_sync.py` (reconciles an onboarding into AIOS), `jobs.py` (the timer), `schemas.py`, `cli.py`, `steps/` (one file per step type plus `registry.py`), `templates/` (`schema.json`, `loader.py`, `presets/*.yaml`), `routers/`. `alembic/` the migrations. `tests/` the pytest suite. Virtualenv in `backend/.venv`.
- `frontend/` — Vite 8 + React 19 + TypeScript 6, linted with oxlint, tested with Vitest. Own `package.json`. `src/api` (fetch client, types, TanStack Query hooks), `src/auth` (optional Supabase login), `src/portal` (the client's pages: `session.tsx`, `FocusLayout`, `ChecklistLayout`, `StepPanel`, `steps/` one renderer per type), `src/admin` (Jay's pages), `src/components`, `src/lib`.
- One Railway service builds the `Dockerfile`: the SPA is served by FastAPI next to `/api`.

## Commands

Backend (from `backend/`):

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env                      # APP_ENV=local AUTH_DISABLED=1 for local work
uvicorn app.main:create_app --factory --reload   # http://localhost:8000, Swagger at /api/swagger (APP_ENV=local only)
python -m pytest -q
python -m app.cli nudge --dry-run     # who would be reminded right now; sends nothing
python -m app.cli sync                # one AIOS sync pass
python -m app.cli seed --org-name Voicent --org-slug voicent --admin-user-id <supabase user id> --admin-email <email>   # first org, first admin, preset templates
TEST_POSTGRES_URL=postgresql://... python -m pytest -q tests/test_migrations.py   # also checks RLS on a real Postgres
alembic upgrade head
alembic revision --autogenerate -m "what changed"   # then review it; a test fails if models and migrations disagree
```

Frontend (from `frontend/`): `npm install`, `npm run dev` (proxies `/api` to :8000), `npm run lint`, `npm test`, `npm run build`.

## Rules

- **Auth fails closed.** Every `/api` route except `/api/health` needs a Supabase user JWT (admin) or a `SERVICE_TOKENS` entry. `AUTH_DISABLED=1` only works with `APP_ENV=local`; otherwise the app refuses to start.
- **Two audiences, two door sets.** Admin routes live under `/api` and need admin auth. Client routes live under `/api/portal` and need a session token that came from a magic link, scoped to one onboarding and one contact. A portal route must never read outside that scope.
- **Nothing on `/api/portal` takes an onboarding id.** Which onboarding and contact is decided by the session token alone, and `deps.portal_ctx` re-checks the link row on every request, so revoking a link cuts off its sessions at once. Every failure is the same 401 (`portal.UNAVAILABLE`); a step that doesn't exist and one a client may not see are the same 404.
- **Rate limits.** Exchange: per client address and across everyone. Writes: per link. The client address comes from `X-Forwarded-For` and can be spoofed, which is why the global limit and the per-link limit exist. In-process, so per instance: move to Redis if this ever scales out.
- **Internal steps never reach the portal.** A step with `visibility = internal` must not appear in any portal response, comment thread or sync payload visible to a client. A test must prove it.
- **Routers stay thin; `services.py` holds the rules.** Every service function takes `org_id` and filters by it. A row from another org is `NotFound`, never a leak (`tests/test_api.py` proves it with two orgs). Admin requests resolve their org in `deps.current_org` (a person's `org_members` row; `X-Org-Id` for service tokens when there are several orgs).
- **A new step type is one file in `app/steps/` plus an entry in `registry.py`.** It declares its config schema, validates and cleans responses (redacting free text), and says what status an accepted answer leaves the step in. Declared-but-unbuilt types (`credential_share`, `info_video`, `payment_link`) are refused in templates until they are built.
- **Always `Depends(get_db, scope="function")`, never plain `Depends(get_db)`.** The commit then happens when the handler returns, before the response and before any background task. With the default scope a background task (the AIOS sync) runs while the request's changes are still uncommitted and reads stale data. The in-memory test database hides this (all its sessions share one connection), so `tests/test_aios_sync.py` pins it on a file database.
- **Background jobs run inside the web process, so run one instance.** Reminders stay safe if it is ever scaled out (a unique constraint on (onboarding, contact, channel, round) refuses a second send) and so does the sync (it reconciles), but the work would repeat. `Settings.jobs_enabled` is False in code and on by default from the environment, so tests never start a thread.
- **Reminders (`nudges.py`).** Stalled means active, not paused, client steps left, and quiet for the template's `nudge_after_days`. One channel per contact: a text only with recorded consent, otherwise email. Texts and automatic emails never go out between 21:00 and 08:00 in the client's own time zone (`Client.timezone`); a manual reminder skips the email rule but never the texting rule. At most `NUDGE_MAX` automatic rounds, then `Onboarding.attention` is set for Jay; a client acting clears it. Every reminder gets a fresh magic link (links are stored only as hashes) and a link for a failed send is revoked. Provider error text is never shown; the one thing read from Twilio's answer is the numeric code for "this number replied STOP", which withdraws consent. Time is passed in (`now=`, `app.state.clock`) so tests never depend on the clock.
- **AIOS sync (`aios_sync.py`) is one-way and reconciles.** Project id `onb-<onboarding id>` (creating it twice is harmless), one task per step, found again by its `link` if a reply was lost. IDs are saved after every call. Creating a task and adding a comment are attempted once (a retry could duplicate); reads and updates are retried with backoff. `sync_version` goes up on every change and `synced_version` moves only to the version a pass actually read, so a change that lands mid-sync is never lost. **Only titles, statuses, dates and one-line summaries go out, through `redact()`; never a form answer, a file, a client comment or a link token.** A test checks the raw requests for exactly that.
- **Migrations on SQLite** run with foreign keys off (`alembic/env.py`), because SQLite rebuilds a table to alter it and would otherwise cascade-delete child rows. Postgres alters in place.
- **Every row has `org_id`**, and every query filters by it. Row level security is on with no policies, so the Supabase Data API sees nothing; the backend connects as the table owner and enforces org and onboarding scope in code.
- **Magic link tokens are stored only as a hash.** The raw token exists once, when issued. Expired, revoked and unknown links all answer the same way.
- **Templates are versioned JSON in the database** (`template_versions`). YAML is import and export only. An onboarding copies its template version into its own snapshot, so editing a template never changes a live client's flow.
- **Free text is redacted on write** (`app/redact.py`) and again before anything is synced out.
- **Credentials are never collected in v1.** `connect` steps record a status and an account label, never a token. A future `credential_share` step uses Fernet encryption with a one-time reveal and no export or sync path.
- **An optional feature's settings must never stop the app starting.** A half-set variable (uploads, SMS, email, AIOS sync) turns that feature off and logs a warning (`Settings.optional_warnings`). Only settings the whole app depends on (auth, database) are fatal in `validate()`. A variable that exists for another purpose (`VITE_SUPABASE_URL`) must not be read as a signal for an unrelated feature.
- **Provider error text is never passed on.** Messages are our own wording plus a status code.
- **Models and migrations must agree.** Change `models.py`, generate a migration, keep `tests/test_migrations.py` green. Migrations must also run on Postgres.
- **Rate limits are real.** The portal's exchange and write endpoints are enforced, not declared.

## Frontend rules

- **Two apps in one bundle.** `/c/:token` is the client portal and never touches Supabase or admin auth. Everything else is the admin app behind `AuthProvider`. Without `VITE_SUPABASE_*` the admin app runs in local mode (no login), which only works against a backend started with `APP_ENV=local AUTH_DISABLED=1`.
- **The portal session lives in memory only.** The link token in the URL is exchanged once for a short-lived session (`portal/session.tsx`), renewed before it expires, and retried once on a 401. A 401 or any failed exchange shows the same "This link isn't available" page and never says why. `index.html` sets `referrer: no-referrer` and `noindex` because the address of a client page is their key.
- **A client never sees what the server doesn't send.** Do not filter internal steps in the UI as a security measure; the API already omits them. The UI must also not invent counts from data it doesn't have.
- **Links from templates are untrusted.** Only plain https goes into an `href` (`lib/links.ts`), always with `rel="noopener noreferrer"`. A bad one is shown as text, never as a link.
- **Server state lives in TanStack Query**, not component state. Errors show the server's own wording and every problem it listed (`ApiError.problems`), matched back to fields by label (`lib/problems.ts`).
- **Admin screens say what is wrong.** Any admin page that loads data shows `components/LoadError.tsx` on failure, never a bare "couldn't load" (and never an empty-state message when the real problem is an error). It names the setting to fix for a 401, the seed command with the user's own id for a 403, and the logs for a 500. The client portal is the opposite: its messages stay vague on purpose.
- **A new step type needs a portal renderer** in `portal/steps/` registered in `registry.tsx`, and a case in `admin/StepResponse.tsx`. Unknown types render a safe fallback instead of crashing.
- **Uploads are checked on the device first** (`lib/uploads.ts` mirrors the server's allow-list, SVG excluded) and again by the server. The browser PUTs the file straight to the signed storage URL.
- **Phone first.** Touch targets are at least 44px, inputs use the right `type` and `inputmode`, and there is no horizontal scroll at 375px. Check new screens at that width.
- **Colour never carries meaning alone.** Every status is a glyph plus a word (`components/StatusBadge.tsx`), overdue says "Overdue", errors say what is wrong beside the field.
- **Tests:** Vitest with Testing Library. `test/helpers.tsx` has `mockFetch` (answers by `METHOD /path` and fails on anything unexpected) and `renderRoute` (with a fake portal session).

## Conventions

- Python: type hints, `from __future__ import annotations`, small modules, business rules in `services.py` (not in routers).
- TypeScript is strict about unused locals and params, uses `verbatimModuleSyntax` (use `import type`) and `erasableSyntaxOnly` (no enums or namespaces).
- Colour never carries meaning alone: every status ships with a glyph or a word.
- `node_modules/`, `.venv/`, `.env*` and `dist/` are git-ignored. Default branch is `main`.
