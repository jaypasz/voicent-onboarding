"""Strip secrets from text before it is stored or shown.

A pasted webhook URL or API key in a form answer would otherwise be readable by
anyone who can open the onboarding. Redacting on write means it never lands in the
database or in a backup.
"""
from __future__ import annotations

import re

_PATTERNS = [
    re.compile(r"https?://[^\s\"'<>)]*/webhook(?:-test)?/[0-9a-fA-F-]{16,}"),
    re.compile(r"\b(?:sk|pk|rk|xox[abp])[-_][A-Za-z0-9_-]{16,}"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{20,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bghp_[A-Za-z0-9]{30,}"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),  # JWTs
]


def redact(text: str) -> str:
    for pat in _PATTERNS:
        text = pat.sub("[redacted]", text)
    return text
