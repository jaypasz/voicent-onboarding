"""Ask Voicent-App to set up a workspace when an onboarding whose template says so is finished.

One signed webhook per finished onboarding. Off unless VOICENT_PROVISION_URL and VOICENT_PROVISION_SECRET are both set, and
only for onboardings whose own template snapshot says `on_complete: provision_voicent_workspace` (so editing the template
later never changes what a live client's onboarding does).

How a delivery travels:
- Finishing the onboarding queues it (`queue`, called from services when the last step is done): state `pending`, a fresh
  `delivery_id`, due now. Nothing is sent inside the request that finished it.
- `deliver` claims a due delivery with one conditional UPDATE, so two runs (a background task and the timer, or two
  instances) can't both send it. The claim also pushes `provision_next_at` out by a lease, so a crash mid-send is retried.
- A 2xx is delivered. A timeout, 429 or 5xx is retried with backoff by the timer, with the same delivery_id, so the receiver
  can drop a repeat. Any other refusal stops and waits for Jay: asking again would get the same answer.
- "Send again" from the admin page makes a new delivery_id for the same onboarding. The receiver treats it as an update.

What goes out (the full contract is in ARCHITECTURE.md): the org, the client, its contacts, the answers to client form
steps, and the integrations the client connected. Never a file, a comment, an internal step, an approval note or a link
token. Text is passed through redact() again on the way out. The secret is only ever used to sign; it never travels.

Errors are our own wording plus a status code. Nothing the other side says is shown or stored.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import logging
import re
import uuid
from dataclasses import dataclass

import httpx
from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from . import models as m
from .config import Settings
from .redact import redact

log = logging.getLogger("uvicorn.error")

ON_COMPLETE = "provision_voicent_workspace"
EVENT = "onboarding.completed"
SCHEMA_VERSION = 1
# Wait this long after attempt 1, 2, ... before the next one. After the last, the delivery is marked failed.
RETRY_AFTER = (dt.timedelta(minutes=5), dt.timedelta(minutes=30), dt.timedelta(hours=2), dt.timedelta(hours=6), dt.timedelta(hours=24))
MAX_ATTEMPTS = len(RETRY_AFTER) + 1
LEASE = dt.timedelta(minutes=10)  # a claimed delivery that never reports back is tried again after this
SIGNATURE_TOLERANCE_SECONDS = 300
WORKSPACE_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,120}$")


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _aware(t: dt.datetime | None) -> dt.datetime | None:
    return t if t is None or t.tzinfo else t.replace(tzinfo=dt.timezone.utc)


def _iso(t: dt.datetime | None) -> str | None:
    t = _aware(t)
    return t.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z") if t else None


def wants_provisioning(ob: m.Onboarding) -> bool:
    return (ob.document or {}).get("on_complete") == ON_COMPLETE


# ---------------------------------------------------------------- queueing (called from services)

def queue(ob: m.Onboarding, now: dt.datetime) -> bool:
    """Line up a delivery for an onboarding that has just been finished. A delivery that is already waiting or already went
    through is left alone, so finishing, reopening and finishing again doesn't send twice. True if one was queued."""
    if not wants_provisioning(ob) or ob.provision_state in ("pending", "delivered"):
        return False
    _reset(ob, now)
    return True


def _reset(ob: m.Onboarding, now: dt.datetime) -> None:
    ob.provision_state, ob.provision_delivery_id = "pending", str(uuid.uuid4())
    ob.provision_attempts, ob.provision_next_at, ob.provision_error = 0, now, ""


def request_again(ob: m.Onboarding, now: dt.datetime) -> None:
    """Jay asked for it now. A waiting delivery keeps its id (the receiver may have seen it); anything else gets a new one."""
    if ob.provision_state == "pending":
        ob.provision_next_at = now
    else:
        _reset(ob, now)


# ---------------------------------------------------------------- the payload

def build_payload(db: Session, settings: Settings, ob: m.Onboarding, now: dt.datetime) -> dict:
    """Exactly what Voicent-App receives. Only client-visible steps; only form answers and connected integrations."""
    org = db.get(m.Org, ob.org_id)
    client = db.get(m.Client, ob.client_id)
    contacts = list(db.scalars(select(m.Contact).where(m.Contact.client_id == ob.client_id, m.Contact.org_id == ob.org_id).order_by(m.Contact.created_at)))
    defs = {d["key"]: d for d in ob.document["steps"]}
    answers: dict[str, dict] = {}
    integrations: list[dict] = []
    for s in ob.steps:
        if s.visibility != "client":
            continue
        d = defs.get(s.key, {})
        config = d.get("config") or {}
        last = s.responses[-1] if s.responses else None
        if s.type == "form" and last and s.status != "skipped":
            fields = {f["key"]: f for f in config.get("fields", [])}
            out = {}
            for k, v in (last.data.get("answers") or {}).items():
                f = fields.get(k)
                if f is None:
                    continue
                out[k] = {"label": f["label"], "type": f["type"], "value": _clean(v)}
            if out:
                answers[s.key] = out
        elif s.type == "connect":
            data = last.data if last else {}
            integrations.append({
                "step_key": s.key, "provider": config.get("provider", ""), "label": config.get("label", ""),
                "access_mode": config.get("access_mode", "oauth"),
                "status": "skipped" if s.status == "skipped" else data.get("status", "not_started"),
                "account_label": redact(str(data.get("account_label", "")))[:200],
            })
    return {
        "event": EVENT,
        "schema_version": SCHEMA_VERSION,
        "delivery_id": ob.provision_delivery_id or "preview",
        "sent_at": _iso(now),
        "source": "voicent-onboarding",
        "org": {"id": org.id, "slug": org.slug, "name": org.name},
        "onboarding": {
            "id": ob.id, "title": ob.title, "url": f"{settings.app_url}/onboardings/{ob.id}" if settings.app_url else None,
            "template": {"slug": ob.document.get("slug"), "version": ob.document.get("version"), "name": ob.document.get("name")},
            "started_at": _iso(ob.started_at), "completed_at": _iso(ob.completed_at),
        },
        "client": {"id": client.id, "name": client.name, "kind": client.kind, "timezone": client.timezone},
        "contacts": [{
            "id": c.id, "name": c.name, "email": c.email or None, "phone": c.phone or None, "role": c.role or None,
            "sms_consent": c.sms_consent, "sms_consent_at": _iso(c.sms_consent_at),
        } for c in contacts],
        "answers": answers,
        "integrations": integrations,
    }


def _clean(v):
    if isinstance(v, str):
        return redact(v)
    if isinstance(v, list):
        return [redact(x) if isinstance(x, str) else x for x in v]
    return v


def encode(payload: dict) -> bytes:
    """The exact bytes that are signed and sent. The receiver must verify these bytes, not a re-encoding of them."""
    return json.dumps(payload, separators=(",", ":"), sort_keys=True, ensure_ascii=False).encode()


# ---------------------------------------------------------------- signing

def sign(secret: str, timestamp: int, body: bytes) -> str:
    """`v1=` + hex HMAC-SHA256 of `<timestamp>.<body>` with the shared secret."""
    mac = hmac.new(secret.encode(), str(timestamp).encode() + b"." + body, hashlib.sha256).hexdigest()
    return f"v1={mac}"


def verify(secret: str, signature: str, timestamp: str, body: bytes, now: dt.datetime | None = None,
           tolerance: int = SIGNATURE_TOLERANCE_SECONDS) -> bool:
    """The receiver's check, written here so the contract has a reference implementation (and the tests use it)."""
    try:
        ts = int(timestamp)
    except (TypeError, ValueError):
        return False
    if abs((now or _now()).timestamp() - ts) > tolerance:
        return False
    return hmac.compare_digest(sign(secret, ts, body), signature or "")


def headers_for(settings: Settings, payload: dict, body: bytes, now: dt.datetime) -> dict:
    ts = int(now.timestamp())
    return {
        "Content-Type": "application/json",
        "User-Agent": "voicent-onboarding/1",
        "X-Voicent-Event": EVENT,
        "X-Voicent-Delivery": payload["delivery_id"],
        "X-Voicent-Timestamp": str(ts),
        "X-Voicent-Signature": sign(settings.voicent_provision_secret, ts, body),
    }


# ---------------------------------------------------------------- sending

@dataclass
class Reply:
    status: int  # 0 when nothing came back
    workspace_id: str | None = None


class Sender:
    """POSTs one delivery. No retries here (the timer retries, with backoff, from the database) and no redirects."""

    def __init__(self, settings: Settings, http: httpx.Client | None = None):
        self.url = settings.voicent_provision_url
        self.http = http or httpx.Client(timeout=10.0, follow_redirects=False)

    def post(self, body: bytes, headers: dict) -> Reply:
        try:
            r = self.http.post(self.url, content=body, headers=headers)
        except httpx.HTTPError:
            return Reply(0)
        wid = None
        if r.status_code < 300:
            try:
                got = r.json().get("workspace_id")
            except (ValueError, AttributeError):
                got = None
            wid = got if isinstance(got, str) and WORKSPACE_ID.match(got) else None
        return Reply(r.status_code, wid)


@dataclass
class DeliveryResult:
    ok: bool
    state: str  # delivered | retrying | failed | skipped | off
    message: str = ""


def _log(db: Session, ob: m.Onboarding, status: str, detail: str) -> None:
    db.add(m.SyncLog(org_id=ob.org_id, onboarding_id=ob.id, target="voicent", action="provision", status=status, detail=detail[:300]))


def _transient(status: int) -> bool:
    return status == 0 or status in (408, 429) or status >= 500


def deliver(sm: sessionmaker, settings: Settings, org_id: str, onboarding_id: str, sender: Sender | None = None,
            now: dt.datetime | None = None, manual: bool = False) -> DeliveryResult:
    """Send this onboarding's waiting delivery if it is due (or now, when Jay asked). Never raises."""
    if not settings.provisioning_enabled:
        return DeliveryResult(True, "off", "Provisioning isn't switched on.")
    now = now or _now()
    try:
        with sm() as db:
            due = m.Onboarding.provision_next_at <= now
            claimed = db.execute(
                update(m.Onboarding)
                .where(m.Onboarding.id == onboarding_id, m.Onboarding.org_id == org_id, m.Onboarding.status == "completed",
                       m.Onboarding.provision_state == "pending", *(() if manual else (due,)))
                .values(provision_next_at=now + LEASE, provision_attempts=m.Onboarding.provision_attempts + 1)
                .execution_options(synchronize_session=False)
            ).rowcount
            db.commit()
            if not claimed:
                return DeliveryResult(True, "skipped", "Nothing is waiting to go to Voicent-App.")
            ob = db.scalar(select(m.Onboarding).where(m.Onboarding.id == onboarding_id, m.Onboarding.org_id == org_id))
            payload = build_payload(db, settings, ob, now)
            body = encode(payload)
            reply = (sender or Sender(settings)).post(body, headers_for(settings, payload, body, now))
            return _record(db, ob, reply, now)
    except Exception:  # noqa: BLE001 - nothing here may escape into a request or the job loop
        log.error("Provisioning failed for onboarding %s", onboarding_id, exc_info=True)
        return DeliveryResult(False, "failed", "Something unexpected went wrong while asking Voicent-App. See the server logs.")


def _record(db: Session, ob: m.Onboarding, reply: Reply, now: dt.datetime) -> DeliveryResult:
    s = reply.status
    if 200 <= s < 300:
        ob.provision_state, ob.provisioned_at, ob.provision_next_at, ob.provision_error = "delivered", now, None, ""
        if reply.workspace_id:
            ob.voicent_workspace_id = reply.workspace_id
        msg = "Voicent-App accepted it" + (f" (workspace {reply.workspace_id})." if reply.workspace_id else ".")
        _log(db, ob, "ok", msg)
        db.commit()
        return DeliveryResult(True, "delivered", msg)
    if _transient(s):
        what = f"Voicent-App didn't answer{f' (status {s})' if s else ''}."
        if ob.provision_attempts >= MAX_ATTEMPTS:
            ob.provision_state, ob.provision_next_at = "failed", None
            ob.provision_error = f"{what} Gave up after {MAX_ATTEMPTS} tries."
            _log(db, ob, "failed", ob.provision_error)
            db.commit()
            return DeliveryResult(False, "failed", ob.provision_error)
        ob.provision_next_at = now + RETRY_AFTER[ob.provision_attempts - 1]
        ob.provision_error = f"{what} Trying again by itself."
        _log(db, ob, "failed", ob.provision_error)
        db.commit()
        return DeliveryResult(False, "retrying", ob.provision_error)
    ob.provision_state, ob.provision_next_at = "failed", None
    ob.provision_error = f"Voicent-App refused it (status {s}). Fix the cause, then send it again."
    _log(db, ob, "failed", ob.provision_error)
    db.commit()
    return DeliveryResult(False, "failed", ob.provision_error)


def kick(request, background, org_id: str, onboarding_id: str) -> None:
    """After a change that may have finished the onboarding: deliver once the response has gone. If that doesn't happen, the
    timer finds it. Cheap when there is nothing to send (one UPDATE that matches no row)."""
    st = request.app.state
    if st.settings.provisioning_enabled:
        background.add_task(deliver, st.sessionmaker, st.settings, org_id, onboarding_id, st.provisioner)


def deliver_due(sm: sessionmaker, settings: Settings, sender: Sender | None = None, now: dt.datetime | None = None, limit: int = 25) -> dict:
    """The periodic pass: every waiting delivery whose time has come."""
    if not settings.provisioning_enabled:
        return {"enabled": False, "delivered": 0, "failed": 0}
    now = now or _now()
    with sm() as db:
        todo = list(db.execute(select(m.Onboarding.org_id, m.Onboarding.id).where(
            m.Onboarding.status == "completed", m.Onboarding.provision_state == "pending", m.Onboarding.provision_next_at <= now).limit(limit)))
    out = {"enabled": True, "delivered": 0, "failed": 0}
    for org_id, oid in todo:
        r = deliver(sm, settings, org_id, oid, sender, now=now)
        if r.state == "delivered":
            out["delivered"] += 1
        elif r.state in ("retrying", "failed"):
            out["failed"] += 1
    return out


def status_for(db: Session, settings: Settings, ob: m.Onboarding) -> dict:
    """What the admin page shows about the Voicent workspace for one onboarding."""
    rows = list(db.scalars(select(m.SyncLog).where(m.SyncLog.onboarding_id == ob.id, m.SyncLog.target == "voicent").order_by(m.SyncLog.created_at.desc()).limit(5)))
    if not wants_provisioning(ob):
        state = "not_wanted"
    elif not settings.provisioning_enabled:
        state = "off"
    elif ob.provision_state in ("pending", "delivered", "failed"):
        state = ob.provision_state
    else:
        state = "waiting"  # the client hasn't finished yet
    return {
        "enabled": settings.provisioning_enabled, "wanted": wants_provisioning(ob), "state": state,
        "workspace_id": ob.voicent_workspace_id, "attempts": ob.provision_attempts,
        "next_attempt_at": ob.provision_next_at if ob.provision_state == "pending" else None,
        "delivered_at": ob.provisioned_at, "error": ob.provision_error or "",
        "log": [{"at": r.created_at, "status": r.status, "detail": r.detail} for r in rows],
    }
