from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body
from fastapi.responses import PlainTextResponse

from .. import services
from ..deps import Actor, Auth, Db, Org, Session
from ..errors import TemplateInvalid
from ..schemas import TemplateSummary, TemplateYamlIn, template_out
from ..steps import registry
from ..templates import loader

router = APIRouter(prefix="/templates", tags=["templates"])


def _detail(db: Session, org: str, t, version: int | None = None) -> dict:
    return template_out(t, services.template_document(db, org, t, version), sorted(v.version for v in t.versions))


@router.get("/step-types")
def step_types(_: Actor = Auth):
    """What the template builder (and YAML authors) can use. Unimplemented types are listed but marked."""
    return [t.describe() for t in registry.all_types()]


@router.get("", response_model=list[TemplateSummary])
def list_templates(include_archived: bool = False, db: Session = Db, org: str = Org):
    return services.list_templates(db, org, include_archived)


@router.post("/install-presets")
def install_presets(db: Session = Db, org: str = Org, actor: Actor = Auth):
    return {"added": services.install_presets(db, org, created_by=actor.label)}


@router.post("/validate")
def validate(document: Any = Body(...), _: Actor = Auth):
    problems = loader.validate_document(document)
    return {"ok": not problems, "problems": problems}


@router.post("", status_code=201)
def save(document: Any = Body(...), db: Session = Db, org: str = Org, actor: Actor = Auth):
    t, v, new_version = services.save_template(db, org, document, created_by=actor.label)
    return _detail(db, org, t, v.version) | {"new_version": new_version}


@router.post("/import")
def import_yaml(body: TemplateYamlIn, db: Session = Db, org: str = Org, actor: Actor = Auth):
    """YAML in, JSON stored. With dry_run, report problems (or the normalised document) and save nothing."""
    try:
        doc = loader.check(loader.parse_yaml(body.yaml))
    except TemplateInvalid as e:
        if body.dry_run:
            return {"ok": False, "problems": e.problems}
        raise
    if body.dry_run:
        return {"ok": True, "problems": [], "document": doc}
    t, v, new_version = services.save_template(db, org, doc, created_by=actor.label)
    return {"ok": True, "problems": []} | _detail(db, org, t, v.version) | {"new_version": new_version}


@router.get("/{template_id}")
def get_template(template_id: str, version: int | None = None, db: Session = Db, org: str = Org):
    return _detail(db, org, services.get_template(db, org, template_id), version)


@router.get("/{template_id}/export", response_class=PlainTextResponse)
def export(template_id: str, version: int | None = None, db: Session = Db, org: str = Org):
    t = services.get_template(db, org, template_id)
    return PlainTextResponse(loader.export_yaml(services.template_document(db, org, t, version).document), media_type="text/yaml")


@router.post("/{template_id}/archive")
def archive(template_id: str, archived: bool = True, db: Session = Db, org: str = Org):
    t = services.archive_template(db, org, template_id, archived)
    return {"id": t.id, "archived": t.archived}
