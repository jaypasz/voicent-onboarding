"""What actually goes to Twilio and Resend, and how their answers are read. httpx.MockTransport stands in for both."""
import json
from urllib.parse import parse_qs

import httpx

from app.config import Settings
from app.notify import Notifier, to_e164
from tests.helpers4 import BASE


def notifier(handler):
    s = Settings(**BASE)
    return Notifier(s, httpx.Client(transport=httpx.MockTransport(handler)))


def test_phone_numbers():
    assert to_e164("(555) 123-4567") == "+15551234567"
    assert to_e164("555.123.4567") == "+15551234567"
    assert to_e164("1 555 123 4567") == "+15551234567"
    assert to_e164("+44 20 7946 0958") == "+442079460958"
    for bad in ("", "12-34", "abcdefghij", "+123", "555123456", "+1" + "5" * 20):
        assert to_e164(bad) is None, bad


def test_a_text_goes_to_twilio_with_basic_auth_and_form_fields():
    seen = {}

    def handler(req):
        seen.update(url=str(req.url), auth=req.headers["authorization"], form=parse_qs(req.content.decode()))
        return httpx.Response(201, json={"sid": "SM1"})

    r = notifier(handler).send_sms("+15551234567", "Hello there")
    assert r.ok
    assert seen["url"] == "https://api.twilio.com/2010-04-01/Accounts/AC123/Messages.json"
    assert seen["auth"].startswith("Basic ")
    assert seen["form"] == {"To": ["+15551234567"], "From": ["+15550001111"], "Body": ["Hello there"]}


def test_twilio_stop_is_recognised_by_its_code_and_other_text_is_never_passed_on():
    r = notifier(lambda req: httpx.Response(400, json={"code": 21610, "message": "SECRET PROVIDER TEXT"})).send_sms("+1555", "x")
    assert not r.ok and r.opted_out and "STOP" in r.reason and "SECRET" not in r.reason
    r = notifier(lambda req: httpx.Response(400, json={"code": 21211, "message": "SECRET PROVIDER TEXT"})).send_sms("+1555", "x")
    assert not r.opted_out and "can't receive text messages" in r.reason and "SECRET" not in r.reason
    r = notifier(lambda req: httpx.Response(503, text="SECRET PROVIDER TEXT")).send_sms("+1555", "x")
    assert not r.ok and "status 503" in r.reason and "SECRET" not in r.reason
    r = notifier(lambda req: httpx.Response(401, json=["not", "a", "dict"])).send_sms("+1555", "x")
    assert not r.ok and "status 401" in r.reason  # an odd answer doesn't crash it


def test_an_unreachable_service_is_reported_in_our_words():
    def boom(req):
        raise httpx.ConnectError("secret internal detail")

    r = notifier(boom).send_sms("+1555", "x")
    assert not r.ok and r.reason == "The text message service didn't answer."
    r = notifier(boom).send_email("a@b.co", "s", "t", "<p>h</p>")
    assert not r.ok and r.reason == "The email service didn't answer."


def test_an_email_goes_to_resend_with_a_bearer_key_in_the_header_only():
    seen = {}

    def handler(req):
        seen.update(url=str(req.url), auth=req.headers["authorization"], body=json.loads(req.content), raw=req.content.decode())
        return httpx.Response(200, json={"id": "e1"})

    r = notifier(handler).send_email("pat@acme.test", "Subject", "plain", "<p>html</p>")
    assert r.ok and seen["url"] == "https://api.resend.com/emails" and seen["auth"] == "Bearer re_test"
    assert seen["body"] == {"from": "Voicent <hi@onboard.test>", "to": ["pat@acme.test"], "subject": "Subject", "text": "plain", "html": "<p>html</p>"}
    assert "re_test" not in seen["raw"]  # the key is not in the body


def test_email_failures_carry_only_a_status_code():
    r = notifier(lambda req: httpx.Response(422, json={"message": "SECRET PROVIDER TEXT"})).send_email("a@b.co", "s", "t", "h")
    assert not r.ok and "status 422" in r.reason and "SECRET" not in r.reason
