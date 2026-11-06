from __future__ import annotations

from fastapi import APIRouter

from .. import services
from ..deps import Db, Org, Session
from ..schemas import ClientIn, ClientOut, ClientPatch, ContactIn, ContactOut, ContactPatch

router = APIRouter(prefix="/clients", tags=["clients"])


@router.get("", response_model=list[ClientOut])
def list_clients(status: str | None = None, db: Session = Db, org: str = Org):
    return services.list_clients(db, org, status)


@router.post("", response_model=ClientOut, status_code=201)
def create_client(body: ClientIn, db: Session = Db, org: str = Org):
    return services.create_client(db, org, name=body.name, kind=body.kind, notes=body.notes)


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
