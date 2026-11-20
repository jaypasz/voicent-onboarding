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
   Storage (private bucket)   Twilio SMS / Resend email   AIOS app (REST)   Voicent-App (signed webhook)
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

Uploads: the server checks name, type, size and step limits, then returns a signed Supabase Storage URL; the browser uploads straight to it. An upload answer is accepted only for files that belong to that step and exist in storage, whose stored content type is the one the step allows for that name, and whose first bytes look like that kind of file (the browser picks the content type when it uploads, so the one declared for the URL proves nothing). The cap on issued URLs per step counts only files in the latest answer and reservations younger than two hours (a signed upload URL's lifetime), so abandoned uploads can't lock a client out.

## Frontend (phase 3b)

One Vite bundle, two audiences. **Client portal** (`/c/:token`): the link token is exchanged for a 30-minute in-memory session; the page shows either the *focus* layout (one step per screen, dots to jump, the next open step comes up after each save, a finished screen when the client's part is done) or the *checklist* layout (sections, each step collapsible, who it is for, due dates), chosen by the template. Each step type has one renderer (`form`, `upload`, `connect`, `book_call`, `approval`). **Admin** (`/`): onboardings list with status filters, onboarding detail (every step with answers in words, files via short-lived links, comments with a "visible to the client" switch, pause/resume/archive, link controls; links appear once after sending), clients and contacts (text consent needs a recorded source), templates (YAML check/save/download), new onboarding.

## Reminders and the AIOS board (phase 4)

A timer thread in the web process runs `jobs.run_once` every `JOBS_INTERVAL_MINUTES` (15): the reminder pass, then the AIOS sync pass, then any Voicent provisioning that is due. `python -m app.cli nudge` and `sync` run the same passes by hand.

**Reminders.** An active, unpaused onboarding is *stalled* when the client has steps left and nothing has happened for the template's `nudge_after_days` (counted from the last activity or the last reminder). Each contact is reminded about their own open steps; unassigned steps go to the first contact. A contact gets one channel: a text if they agreed to texts, otherwise an email. Nothing goes out at night in the client's time zone. After `NUDGE_MAX` automatic reminders with no reply it stops and flags the onboarding "needs you". Every attempt is a `nudges` row; `(onboarding, contact, channel, round)` is unique so two overlapping runs can't send the same reminder. Jay can also send one now, pause automatic ones per onboarding, and see the history.

**AIOS.** Each sent onboarding becomes one AIOS project (`onb-<id>`) with a task per step: client steps read "Waiting on client: ..." until done, internal steps are Jay's own. When a client acts, a one-line comment is added to the task (never their answers). The sync compares what we know with what AIOS was last told and fixes the difference, so it is safe to run twice and safe after a failure. Failures are recorded in `sync_log`, shown on the onboarding page, and retried by the timer.

## Voicent-App provisioning (Step 11)

When an onboarding is finished and its own template snapshot says `on_complete: provision_voicent_workspace`, this service sends Voicent-App one signed webhook asking it to set up the client's workspace. It is off until `VOICENT_PROVISION_URL` and `VOICENT_PROVISION_SECRET` are set (see DEPLOY.md). The code is `backend/app/provision.py`. **The receiving endpoint in Voicent-App is separate work.** What follows is the contract it must meet.

**How this side sends it.** Finishing the last step queues a delivery in the database; it goes out after the response (and from the timer if that didn't happen). One conditional `UPDATE` claims it, so it goes out once even if two runs overlap. A timeout, a `408`, a `429` or a `5xx` is retried by the timer after 5 minutes, 30 minutes, 2 hours, 6 hours and 24 hours, always with the same `delivery_id`. Then it is marked failed. Any other `4xx` is not retried: it is marked failed at once and waits for Jay. Redirects are not followed. Jay can send it again from the onboarding page, which makes a new `delivery_id` for the same onboarding (for example after the client's answers were corrected). Finishing, reopening and finishing again does not send a second time by itself.

### Request

`POST <VOICENT_PROVISION_URL>` with the body below as UTF-8 JSON, and these headers:

| Header | Value |
|---|---|
| `Content-Type` | `application/json` |
| `X-Voicent-Event` | `onboarding.completed` |
| `X-Voicent-Delivery` | the `delivery_id` (a UUID). The same on every retry of one delivery |
| `X-Voicent-Timestamp` | Unix seconds when this attempt was signed |
| `X-Voicent-Signature` | `v1=` + lowercase hex HMAC-SHA256 of `<timestamp>.<raw body bytes>`, keyed with the shared secret |

```json
{
  "event": "onboarding.completed",
  "schema_version": 1,
  "delivery_id": "6f1c…",
  "sent_at": "2026-11-19T15:04:05Z",
  "source": "voicent-onboarding",
  "org": {"id": "…", "slug": "voicent", "name": "Voicent"},
  "onboarding": {
    "id": "…", "title": "MSP onboarding: Acme IT", "url": "https://<this service>/onboardings/<id>",
    "template": {"slug": "msp", "version": 3, "name": "MSP onboarding"},
    "started_at": "2026-11-01T14:00:00Z", "completed_at": "2026-11-19T15:04:00Z"
  },
  "client": {"id": "…", "name": "Acme IT", "kind": "msp", "timezone": "America/Chicago"},
  "contacts": [
    {"id": "…", "name": "Pat Owner", "email": "pat@acme.example", "phone": "+15551234567", "role": "owner",
     "sms_consent": true, "sms_consent_at": "2026-11-01T14:00:00Z"}
  ],
  "answers": {
    "business_basics": {
      "business_name": {"label": "Business name", "type": "text", "value": "Acme IT"},
      "services": {"label": "Services", "type": "multiselect", "value": ["Managed IT", "VoIP"]}
    }
  },
  "integrations": [
    {"step_key": "phone_system", "provider": "ringcentral", "label": "RingCentral", "access_mode": "delegated",
     "status": "connected", "account_label": "acme-main"}
  ]
}
```

- `answers` holds the latest answer to each client **form** step that wasn't skipped, keyed by step key then field key. `type` is the form field type (`text`, `textarea`, `select`, `multiselect`, `phone`, `email`, `url`, `date`, `checkbox`); `value` is a string, a list of strings (multiselect) or a boolean (checkbox). Unanswered optional fields are absent. Text has been through `redact()` twice (on write and on the way out).
- `integrations` has one entry per client **connect** step. `status` is `connected`, `pending` (the client asked for help), `not_started` or `skipped`. `account_label` is what the client typed to say which account; it is never a token.
- Missing values are `null` (`email`, `phone`, `role`, `sms_consent_at`, `onboarding.url` when `APP_URL` is unset, `started_at`).
- **Never in the payload:** uploaded files or their names, comments, approval decisions or notes, booked-call details, internal steps and their checklists, magic link tokens, or any credential. The shared secret only signs; it is never sent.
- `schema_version` goes up only for a change a receiver must handle. New optional keys can appear without a bump, so ignore keys you don't know.

### What the receiver must do

1. Read the raw body bytes before parsing. Reject (`401`) unless `X-Voicent-Signature` matches and `X-Voicent-Timestamp` is within 5 minutes of now. Compare in constant time. Reference check, the same one the tests here use (`provision.verify`):

   ```python
   import hashlib, hmac, time

   def verify(secret: str, signature: str, timestamp: str, body: bytes, tolerance: int = 300) -> bool:
       try:
           ts = int(timestamp)
       except (TypeError, ValueError):
           return False
       if abs(time.time() - ts) > tolerance:
           return False
       mac = hmac.new(secret.encode(), str(ts).encode() + b"." + body, hashlib.sha256).hexdigest()
       return hmac.compare_digest(f"v1={mac}", signature or "")
   ```

2. Be idempotent. A repeated `delivery_id` must return the same answer without doing the work again. A new `delivery_id` for an `onboarding.id` it has already seen is an update ("send again"): apply the newer answers to the same workspace, never create a second one.
3. Answer within 10 seconds. If setting up the workspace takes longer, store the request and return `202`, then do the work.
4. Reply `2xx` when it has the request, with an optional JSON body `{"workspace_id": "<id>", "status": "created" | "updated" | "queued"}`. `workspace_id` (1 to 120 of `A–Z a–z 0–9 _ . : -`) is shown on the onboarding page; anything else in it is ignored.
5. Reply `4xx` (not `408` or `429`) only when sending the same thing again can never work: a bad signature, a payload it can't use, an unknown template. That stops the retries and shows Jay a failure. Use `5xx` or `429` for anything temporary.
6. Treat contacts' email addresses and phone numbers as personal data. Text only those with `sms_consent: true`.

Nothing the receiver says in a response body is shown or stored here, apart from a valid `workspace_id`. Errors on this side are our own wording plus the status code.

## Integrations

- **AIOS:** one project per onboarding and a task per step through the AIOS REST API with a dedicated service token. De-duplicated by the stored task ID and the task `link`. A sync failure never blocks the client.
- **Voicent-App:** the signed webhook above. Off by default; the receiving endpoint is a separate piece of work in that repo.
