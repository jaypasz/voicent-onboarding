from __future__ import annotations

from fastapi import APIRouter, Request, Response

from .. import services
from ..deps import Db, Org, Session
from ..schemas import TaskIn, TaskOut, TaskPatch

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.get("", response_model=list[TaskOut])
def list_tasks(client_id: str | None = None, onboarding_id: str | None = None, assignee_id: str | None = None,
               done: bool | None = None, db: Session = Db, org: str = Org):
    return services.list_tasks(db, org, client_id=client_id, onboarding_id=onboarding_id, assignee_id=assignee_id, done=done)


@router.post("", response_model=TaskOut, status_code=201)
def create_task(body: TaskIn, db: Session = Db, org: str = Org):
    return services.create_task(db, org, **body.model_dump())


@router.patch("/{task_id}", response_model=TaskOut)
def update_task(task_id: str, body: TaskPatch, request: Request, db: Session = Db, org: str = Org):
    return services.update_task(db, org, task_id, body.model_dump(exclude_unset=True), request.app.state.clock())


@router.delete("/{task_id}", status_code=204)
def delete_task(task_id: str, db: Session = Db, org: str = Org):
    services.delete_task(db, org, task_id)
    return Response(status_code=204)
