from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Request
from pydantic import BaseModel

from .. import provision, services
from ..deps import Db, Org, Session
from ..schemas import ClientIn, ClientOut, ClientPatch, ContactIn, ContactOut, ContactPatch

router = APIRouter(prefix="/clients", tags=["clients"])


@router.get("", response_model=list[ClientOut])
def list_clients(status: str | None = None, db: Session = Db, org: str = Org):
    return services.list_clients(db, org, status)


@router.post("", response_model=ClientOut, status_code=201)
def create_client(body: ClientIn, request: Request, db: Session = Db, org: str = Org):
    tz = body.timezone or request.app.state.settings.default_timezone
    return services.create_client(db, org, name=body.name, kind=body.kind, notes=body.notes, timezone=tz)


@router.get("/{client_id}", response_model=ClientOut)
def get_client(client_id: str, db: Session = Db, org: str = Org):
    return services.get_client(db, org, client_id)


@router.patch("/{client_id}", response_model=ClientOut)
def update_client(client_id: str, body: ClientPatch, db: Session = Db, org: str = Org):
    return services.update_client(db, org, client_id, **body.model_dump(exclude_unset=True))


@router.post("/{client_id}/contacts", response_model=ContactOut, status_code=201)
def add_contact(client_id: str, body: ContactIn, db: Session = Db, org: str = Org):
    return services.add_contact(db, org, client_id, **body.model_dump())


@router.patch("/{client_id}/contacts/{contact_id}", response_model=ContactOut)
def update_contact(client_id: str, contact_id: str, body: ContactPatch, db: Session = Db, org: str = Org):
    return services.update_contact(db, org, client_id, contact_id, **body.model_dump(exclude_unset=True))


class PayingIn(BaseModel):
    paying: bool


@router.post("/{client_id}/paying", response_model=ClientOut)
def set_paying(client_id: str, body: PayingIn, request: Request, background: BackgroundTasks, db: Session = Db, org: str = Org):
    """Mark the client as a paying customer, or not. Paying is what lets a finished onboarding ask Voicent-App for a
    workspace; any that are waiting for it are sent once the response has gone."""
    client, queued = services.set_client_paying(db, org, client_id, body.paying, request.app.state.clock())
    for oid in queued:
        provision.kick(request, background, org, oid)
    return client
