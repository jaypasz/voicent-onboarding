from __future__ import annotations

from fastapi import APIRouter, Request

from ..deps import Actor, Auth

router = APIRouter(tags=["health"])


@router.get("/health")
def health():
    return {"ok": True}


@router.get("/features")
def features(request: Request, _: Actor = Auth):
    """Which optional parts are switched on, so the admin pages can say so instead of silently doing nothing."""
    s = request.app.state.settings
    return {"sms": s.sms_enabled, "email": s.email_enabled, "reminders": s.reminders_enabled, "aios_sync": s.aios_sync_enabled,
            "uploads": s.uploads_enabled, "jobs": s.jobs_enabled, "provisioning": s.provisioning_enabled}


