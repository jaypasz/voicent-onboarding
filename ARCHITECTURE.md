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

`show_if` is stored and ignored until branching ships. The JSON Schema for this document arrives in phase 2 (`app/templates/schema.json`). The GUI builder edits this same document.

## Step types

A registry; each type declares its config schema, response schema, validation, completion rule and side effects. v1: `form`, `upload`, `connect`, `book_call`, `approval`, `internal_task`. Declared but not built: `credential_share`, `info_video`, `payment_link`.

## Integrations (later phases)

- **AIOS:** one project per onboarding and a task per step through the AIOS REST API with a dedicated service token. De-duplicated by the stored task ID and the task `link`. A sync failure never blocks the client.
- **Voicent-App:** a signed webhook on completion to provision a tenant and workspace. Off by default; the receiving endpoint is a separate piece of work in that repo.
