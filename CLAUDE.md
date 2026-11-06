# CLAUDE.md

Guidance for Claude Code (claude.ai/code) when working in this repository.

## What this is

**Voicent Onboarding** is Jay's internal client onboarding app, in the style of Launchpad. Jay creates a client, picks a template, and sends the client a magic link. The client works through steps (forms, uploads, connect an integration, book a call, approve a deliverable) and Jay watches progress. Each onboarding mirrors into the AIOS app as a project with tasks.

One data-driven engine serves a plumber (one question per screen, on a phone) through an agency or MSP (full checklist, several contacts, approvals). The difference lives in the template, never in code.

Plan and rationale: `plans/2026-11-06-client-onboarding-app.md` in the `jaypasz/voicent-aios` workspace repo. It is the source of truth for scope and phases.

## State

Phases 1 and 2 done: scaffold, data model, migrations with row level security, auth, the template schema and YAML loader, four presets, the six v1 step types, services and the admin API (clients, templates, onboardings, steps, comments), and `python -m app.cli seed`. Not built yet: the magic-link client portal API, file uploads, nudges, AIOS sync, the admin and portal UIs (phases 3 and 4). **Not verified: a Railway deploy, real Supabase login.**

## Layout

- `backend/` — Python 3.13, FastAPI + SQLAlchemy 2 + Alembic. `app/` holds `main.py` (app factory), `config.py`, `db.py`, `models.py`, `auth.py`, `deps.py` (incl. `current_org`), `redact.py`, `errors.py`, `services.py` (all the rules), `schemas.py`, `cli.py`, `steps/` (one file per step type plus `registry.py`), `templates/` (`schema.json`, `loader.py`, `presets/*.yaml`), `routers/`. `alembic/` the migrations. `tests/` the pytest suite. Virtualenv in `backend/.venv`.
- `frontend/` — Vite 8 + React 19 + TypeScript 6, linted with oxlint, tested with Vitest. Own `package.json`.
- One Railway service builds the `Dockerfile`: the SPA is served by FastAPI next to `/api`.

## Commands

Backend (from `backend/`):

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env                      # APP_ENV=local AUTH_DISABLED=1 for local work
uvicorn app.main:create_app --factory --reload   # http://localhost:8000, Swagger at /api/swagger (APP_ENV=local only)
python -m pytest -q
python -m app.cli seed --org-name Voicent --org-slug voicent --admin-user-id <supabase user id> --admin-email <email>   # first org, first admin, preset templates
TEST_POSTGRES_URL=postgresql://... python -m pytest -q tests/test_migrations.py   # also checks RLS on a real Postgres
alembic upgrade head
alembic revision --autogenerate -m "what changed"   # then review it; a test fails if models and migrations disagree
```

Frontend (from `frontend/`): `npm install`, `npm run dev` (proxies `/api` to :8000), `npm run lint`, `npm test`, `npm run build`.

## Rules

- **Auth fails closed.** Every `/api` route except `/api/health` needs a Supabase user JWT (admin) or a `SERVICE_TOKENS` entry. `AUTH_DISABLED=1` only works with `APP_ENV=local`; otherwise the app refuses to start.
- **Two audiences, two door sets.** Admin routes live under `/api` and need admin auth. Client routes live under `/api/portal` and need a session token that came from a magic link, scoped to one onboarding and one contact. A portal route must never read outside that scope.
- **Internal steps never reach the portal.** A step with `visibility = internal` must not appear in any portal response, comment thread or sync payload visible to a client. A test must prove it.
- **Routers stay thin; `services.py` holds the rules.** Every service function takes `org_id` and filters by it. A row from another org is `NotFound`, never a leak (`tests/test_api.py` proves it with two orgs). Admin requests resolve their org in `deps.current_org` (a person's `org_members` row; `X-Org-Id` for service tokens when there are several orgs).
- **A new step type is one file in `app/steps/` plus an entry in `registry.py`.** It declares its config schema, validates and cleans responses (redacting free text), and says what status an accepted answer leaves the step in. Declared-but-unbuilt types (`credential_share`, `info_video`, `payment_link`) are refused in templates until they are built.
- **Every row has `org_id`**, and every query filters by it. Row level security is on with no policies, so the Supabase Data API sees nothing; the backend connects as the table owner and enforces org and onboarding scope in code.
- **Magic link tokens are stored only as a hash.** The raw token exists once, when issued. Expired, revoked and unknown links all answer the same way.
- **Templates are versioned JSON in the database** (`template_versions`). YAML is import and export only. An onboarding copies its template version into its own snapshot, so editing a template never changes a live client's flow.
- **Free text is redacted on write** (`app/redact.py`) and again before anything is synced out.
- **Credentials are never collected in v1.** `connect` steps record a status and an account label, never a token. A future `credential_share` step uses Fernet encryption with a one-time reveal and no export or sync path.
- **An optional feature's settings must never stop the app starting.** A half-set variable (uploads, SMS, email, AIOS sync) turns that feature off and logs a warning (`Settings.optional_warnings`). Only settings the whole app depends on (auth, database) are fatal in `validate()`. A variable that exists for another purpose (`VITE_SUPABASE_URL`) must not be read as a signal for an unrelated feature.
- **Provider error text is never passed on.** Messages are our own wording plus a status code.
- **Models and migrations must agree.** Change `models.py`, generate a migration, keep `tests/test_migrations.py` green. Migrations must also run on Postgres.
- **Rate limits are real.** The portal's exchange and write endpoints are enforced, not declared.

## Conventions

- Python: type hints, `from __future__ import annotations`, small modules, business rules in `services.py` (not in routers).
- TypeScript is strict about unused locals and params, uses `verbatimModuleSyntax` (use `import type`) and `erasableSyntaxOnly` (no enums or namespaces).
- Colour never carries meaning alone: every status ships with a glyph or a word.
- `node_modules/`, `.venv/`, `.env*` and `dist/` are git-ignored. Default branch is `main`.
