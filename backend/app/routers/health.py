from __future__ import annotations

from fastapi import APIRouter

from ..deps import Actor, Auth

router = APIRouter(tags=["health"])


@router.get("/health")
def health():
    return {"ok": True}


@router.get("/me")
def me(actor: Actor = Auth):
    """Who the server thinks is calling. Behind auth, so it doubles as the check that login works."""
    return {"id": actor.id, "label": actor.label, "kind": actor.kind}
