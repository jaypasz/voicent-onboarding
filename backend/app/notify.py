"""Sending a text or an email. Credentials travel in headers only. Messages we show are our own wording plus a status
code; the provider's error text is never passed on. The one thing read from a provider's answer is Twilio's numeric
code for "this number has opted out", so we can stop texting them."""
from __future__ import annotations

import re
from dataclasses import dataclass

import httpx

from .config import Settings

TWILIO_OPTED_OUT = 21610
TWILIO_BAD_NUMBER = (21211, 21614, 21408)


@dataclass
class SendResult:
    ok: bool
    reason: str = ""  # our own wording, safe to show
    opted_out: bool = False


def to_e164(phone: str, default_country_code: str = "1") -> str | None:
    """+15551234567 from whatever was typed, or None if it isn't a number we can text."""
    p = (phone or "").strip()
    digits = re.sub(r"\D", "", p)
    if p.startswith("+"):
        return f"+{digits}" if 8 <= len(digits) <= 15 else None
    if len(digits) == 10:
        return f"+{default_country_code}{digits}"
    if len(digits) == 11 and digits.startswith(default_country_code):
        return f"+{digits}"
    return None


class Notifier:
    def __init__(self, settings: Settings, client: httpx.Client | None = None):
        self.s = settings
        self.http = client or httpx.Client(timeout=15.0)

    def send_sms(self, to: str, body: str) -> SendResult:
        s = self.s
        try:
            r = self.http.post(
                f"https://api.twilio.com/2010-04-01/Accounts/{s.twilio_account_sid}/Messages.json",
                data={"To": to, "From": s.twilio_from_number, "Body": body},
                auth=(s.twilio_account_sid, s.twilio_auth_token),
            )
        except httpx.HTTPError:
            return SendResult(False, "The text message service didn't answer.")
        if r.status_code < 300:
            return SendResult(True)
        code = None
        try:
            code = r.json().get("code")
        except (ValueError, AttributeError):
            pass
        if code == TWILIO_OPTED_OUT:
            return SendResult(False, "This person has replied STOP, so no more texts.", opted_out=True)
        if code in TWILIO_BAD_NUMBER:
            return SendResult(False, "That phone number can't receive text messages.")
        return SendResult(False, f"The text message service refused it (status {r.status_code}).")

    def send_email(self, to: str, subject: str, text: str, html: str) -> SendResult:
        s = self.s
        try:
            r = self.http.post(
                "https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {s.resend_api_key}"},
                json={"from": s.resend_from, "to": [to], "subject": subject, "text": text, "html": html},
            )
        except httpx.HTTPError:
            return SendResult(False, "The email service didn't answer.")
        if r.status_code < 300:
            return SendResult(True)
        return SendResult(False, f"The email service refused it (status {r.status_code}).")
