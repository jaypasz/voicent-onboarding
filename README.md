# Voicent Onboarding

Internal client onboarding app (Launchpad-style) for Voicent AI. Templates in, a magic link out, client progress back, mirrored into the AIOS board.

See `CLAUDE.md` for rules and commands, `ARCHITECTURE.md` for the model, and `DEPLOY.md` for Railway and Supabase setup.

```bash
# backend
cd backend && python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env
uvicorn app.main:create_app --factory --reload
# frontend (second terminal)
cd frontend && npm install && npm run dev
```

Status: phases 1 and 2 (scaffold, data model, auth; template engine, step types, admin API). The client portal, nudges, AIOS sync and the UIs follow.
