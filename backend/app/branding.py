"""An org's brand: what its clients see in the portal, in reminders and in the admin app.

Logo and colours come from the org's Voicent tenant (Voicent-App stays the one place a reseller sets them), or are set here
for an org with no tenant. Everything is checked on the way in, whatever its source: a logo is a plain https address, a
colour is #rrggbb. Anything else is dropped, never passed on, because the portal puts these in front of clients.

A reseller's clients never see "Voicent": with no brand name set, a reseller's own name is used.
"""
from __future__ import annotations

import re
from email.utils import parseaddr

from . import models as m
from .config import Settings

COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")
HTTPS = re.compile(r"^https://[^\s\"'<>]{1,490}$")
EMAIL = re.compile(r"^[^@\s<>\"]+@[^@\s<>\"]+\.[^@\s<>\"]+$")
E164 = re.compile(r"^\+[1-9][0-9]{7,14}$")
LOGO_MAX = 500


def clean(raw) -> dict:
    """Only the brand fields we use, each only if it is safe to put in a page."""
    raw = raw if isinstance(raw, dict) else {}
    out = {}
    logo = raw.get("logo_url")
    if isinstance(logo, str) and HTTPS.match(logo.strip()) and len(logo.strip()) <= LOGO_MAX:
        out["logo_url"] = logo.strip()
    for key in ("primary_color", "accent_color"):
        v = raw.get(key)
        if isinstance(v, str) and COLOR.match(v.strip()):
            out[key] = v.strip().lower()
    return out


def display_name(org: m.Org, settings: Settings) -> str:
    """The name clients see. A reseller is never shown as Voicent."""
    if org.brand_name.strip():
        return org.brand_name.strip()
    return org.name if org.account_type == "reseller" else settings.brand_name


def public(org: m.Org, settings: Settings) -> dict:
    """What the portal and the admin app may show. Never a sender address."""
    b = clean(org.brand)
    return {"name": display_name(org, settings), "logo_url": b.get("logo_url"), "primary_color": b.get("primary_color"),
            "accent_color": b.get("accent_color")}


def email_from(org: m.Org, settings: Settings) -> str:
    """'<org's name> <our verified address>'. The address stays ours (it is the one the email service has verified); only the
    name shown changes, so a reseller doesn't need to set up their own domain."""
    _, address = parseaddr(settings.resend_from)
    name = (org.email_from_name.strip() or display_name(org, settings)).replace('"', "").replace("<", "").replace(">", "")
    return f"{name} <{address}>" if address else settings.resend_from


def reply_to(org: m.Org) -> str | None:
    return org.reply_to_email if org.reply_to_email and EMAIL.match(org.reply_to_email) else None


def sms_from(org: m.Org, settings: Settings) -> str:
    return org.sms_from if org.sms_from and E164.match(org.sms_from) else settings.twilio_from_number


def settings_problems(fields: dict) -> list[str]:
    """Checks for what an admin types into the brand settings."""
    out = []
    if fields.get("reply_to_email") and not EMAIL.match(fields["reply_to_email"]):
        out.append("Reply-to: that isn't an email address.")
    if fields.get("sms_from") and not E164.match(fields["sms_from"]):
        out.append("Text messages from: use the full number with country code, like +15551234567.")
    brand = fields.get("brand")
    if isinstance(brand, dict):
        if brand.get("logo_url") and "logo_url" not in clean(brand):
            out.append("Logo: use an https:// address of an image.")
        for k, label in (("primary_color", "Main colour"), ("accent_color", "Accent colour")):
            if brand.get(k) and k not in clean(brand):
                out.append(f"{label}: use a colour like #0b5cff.")
    return out
