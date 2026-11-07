# Architecture

## Shape

```text
client (magic link)          Jay (Supabase login)
        |                           |
   /api/portal/*                /api/*
        \                         /
         FastAPI  (auth, services, redaction)
                 |
        Supabase Postgres (RLS on, no policies; backend is the only reader)
                 |
   Storage (private bucket)   Twilio SMS / Resend email   AIOS app (REST)
```

One Railway service builds the Dockerfile and serves the React SPA and `/api`.

## Entities

`org` > `client` > `contact`s. A `template` has numbered `template_versions` (the document, as JSON). An `onboarding` is a client plus a snapshot of one template version; it owns `steps`. A step has `responses` (revisions), `files`, `step_comments`. `magic_links` give a contact access to one onboarding. `nudges` and `sync_log` record what was sent and what was synced. `org_members` maps a Supabase user to an org.

## Template document (contract with the v2 GUI builder)

```json
{
  "name": "Trades onboarding", "slug": "trades", "version": 1, "layout": "focus",
  "sections": [{"key": "basics", "title": "Your business"}],
  "steps": [{
    "key": "business_basics", "type": "form", "title": "Business basics",
    "section": "basics", "description": "", "visibility": "client",
    "assignee_role": "owner", "due_offset_days": 3,
    "config": {"fields": []}, "show_if": null
  }]
}
```

`show_if` is stored and ignored until branching ships. The JSON Schema for this document is `backend/app/templates/schema.json`; `app/templates/loader.py` validates it (reporting every problem, not just the first), fills defaults, and converts to and from YAML. Saving a changed document adds a `template_versions` row; saving an unchanged one adds nothing. The GUI builder edits this same document, and `POST /api/templates/validate` lets it check a draft with the exact rules the YAML import uses.

## Step types

A registry (`app/steps/registry.py`); each type declares its config schema, validates and cleans responses, and says what status an accepted answer leaves the step in (`resulting_status`). Side effects such as AIOS comments arrive with the sync in a later phase. v1: `form`, `upload`, `connect`, `book_call`, `approval`, `internal_task`. Declared but not built: `credential_share`, `info_video`, `payment_link`.

## Admin API (phase 2)

`/api/clients` (+ contacts), `/api/templates` (list, save JSON, import/export YAML with `dry_run`, validate, step types, install presets, archive), `/api/onboardings` (create from a template version, send, pause, resume, archive, answer or complete or skip or reopen a step, comments). Due dates start when an onboarding is sent, because template offsets are relative to kickoff. Admin link controls: `POST /api/onboardings/{id}/send` issues one link per contact and returns the URLs once; `/links` lists, issues, revokes and extends them; `/files/{id}/url` gives a short-lived download link.

## Client portal API (phase 3a)

`POST /api/portal/exchange {token}` swaps a link token (stored only as a SHA-256 hash) for a 30-minute session (HS256, audience `portal`, signed with `PORTAL_SIGNING_KEY`, never the Supabase secret). Then `GET /api/portal/onboarding`, `PUT /api/portal/steps/{key}`, `POST /steps/{key}/comments`, `POST /steps/{key}/upload-url`, `POST /api/portal/refresh`. A client sees client-visible steps only and nothing derived from internal ones (no counts, sections, comments or template document). In the `focus` layout they see only their own and unassigned steps; in `checklist` they see everyone's but can write only their own and unassigned steps.

Uploads: the server checks name, type, size and step limits, then returns a signed Supabase Storage URL; the browser uploads straight to it. An upload answer is accepted only for files that belong to that step and exist in storage.

## Frontend (phase 3b)

One Vite bundle, two audiences. **Client portal** (`/c/:token`): the link token is exchanged for a 30-minute in-memory session; the page shows either the *focus* layout (one step per screen, dots to jump, the next open step comes up after each save, a finished screen when the client's part is done) or the *checklist* layout (sections, each step collapsible, who it is for, due dates), chosen by the template. Each step type has one renderer (`form`, `upload`, `connect`, `book_call`, `approval`). **Admin** (`/`): onboardings list with status filters, onboarding detail (every step with answers in words, files via short-lived links, comments with a "visible to the client" switch, pause/resume/archive, link controls; links appear once after sending), clients and contacts (text consent needs a recorded source), templates (YAML check/save/download), new onboarding.

## Reminders and the AIOS board (phase 4)

A timer thread in the web process runs `jobs.run_once` every `JOBS_INTERVAL_MINUTES` (15): the reminder pass, then the AIOS sync pass. `python -m app.cli nudge` and `sync` run the same passes by hand.

**Reminders.** An active, unpaused onboarding is *stalled* when the client has steps left and nothing has happened for the template's `nudge_after_days` (counted from the last activity or the last reminder). Each contact is reminded about their own open steps; unassigned steps go to the first contact. A contact gets one channel: a text if they agreed to texts, otherwise an email. Nothing goes out at night in the client's time zone. After `NUDGE_MAX` automatic reminders with no reply it stops and flags the onboarding "needs you". Every attempt is a `nudges` row; `(onboarding, contact, channel, round)` is unique so two overlapping runs can't send the same reminder. Jay can also send one now, pause automatic ones per onboarding, and see the history.

**AIOS.** Each sent onboarding becomes one AIOS project (`onb-<id>`) with a task per step: client steps read "Waiting on client: ..." until done, internal steps are Jay's own. When a client acts, a one-line comment is added to the task (never their answers). The sync compares what we know with what AIOS was last told and fixes the difference, so it is safe to run twice and safe after a failure. Failures are recorded in `sync_log`, shown on the onboarding page, and retried by the timer.

## Integrations (later phases)

- **AIOS:** one project per onboarding and a task per step through the AIOS REST API with a dedicated service token. De-duplicated by the stored task ID and the task `link`. A sync failure never blocks the client.
- **Voicent-App:** a signed webhook on completion to provision a tenant and workspace. Off by default; the receiving endpoint is a separate piece of work in that repo.
