from app.redact import redact

# Fake secrets are assembled at runtime so no key-shaped literal sits in the source
# (GitHub push protection rightly refuses those, even when they are obviously fake).
FAKES = [
    "sk" + "_" + "live" + "_" + "a" * 24,
    "ghp" + "_" + "a" * 36,
    "AKIA" + "ABCDEFGHIJKLMNOP",
    "Bearer " + "a" * 30,
    ".".join(["eyJ" + "a" * 12, "b" * 14, "c" * 14]),
    "https://n8n.example.com/webhook/" + "0123456789abcdef" * 2,
]


def test_secrets_are_redacted():
    for secret in FAKES:
        out = redact(f"my key is {secret} thanks")
        assert secret not in out and "[redacted]" in out, secret[:6]


def test_plain_text_is_untouched():
    text = "We open at 7am, closed Sundays. Call 555-0100."
    assert redact(text) == text
