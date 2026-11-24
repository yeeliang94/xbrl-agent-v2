"""Mask secrets in any text the app keeps: the server log, a model call's
error, a page record's error and everything in a traces zip.

Two guards. First, the exact value of every secret read from the
environment (`.env` holds only secrets, so each key, password, token and the
gateway address) is replaced wherever it appears. Second, anything shaped
like a key is masked even when its value is not known here: `sk-` keys,
Bearer and Basic authorisation, `api_key=...` and JSON fields such as
`"api_key": "..."`, and a password inside an address.
"""
from __future__ import annotations

import os
import re

MASK = "[masked]"
# Environment names whose values are secrets.
_SECRET_NAME = re.compile(r"(?i)(_API_KEY|_KEY|_SECRET|_PASSWORD|_TOKEN|^LLM_PROXY_URL|_PROXY)$")
# A value shorter than this is too common to replace safely (and is no real secret).
_MIN_SECRET_LENGTH = 8

_SHAPES = (
    (re.compile(r"\b(sk-[A-Za-z0-9_-]{4})[A-Za-z0-9_-]{8,}"), r"\1" + MASK),
    (re.compile(r"(?i)\b(bearer\s+)[A-Za-z0-9._~+/=-]{8,}"), r"\1" + MASK),
    (re.compile(r"(?i)\b(basic\s+)[A-Za-z0-9+/=]{8,}"), r"\1" + MASK),
    (re.compile(r'(?i)("(?:[a-z_-]*api[_-]?key|authorization|x-api-key|password|secret|token|access_token)"\s*:\s*")'
                r'[^"]+(")'), r"\1" + MASK + r"\2"),
    (re.compile(r"(?i)\b((?:api[_-]?key|password|secret|token)\s*[=:]\s*)[^\s\"',;&]+"), r"\1" + MASK),
    (re.compile(r"(?i)(\b[a-z][a-z0-9+.-]*://[^\s/:@]+:)[^\s/@]+(@)"), r"\1" + MASK + r"\2"),
)


def secret_values() -> list[str]:
    """The values of the secrets in the environment, longest first."""
    values = {value.strip() for name, value in os.environ.items()
              if _SECRET_NAME.search(name) and name.upper() != "NO_PROXY"
              and len(value.strip()) >= _MIN_SECRET_LENGTH}
    return sorted(values, key=len, reverse=True)


def mask(text: str) -> str:
    if not text:
        return text
    for value in secret_values():
        if value in text:
            text = text.replace(value, MASK)
    for pattern, replacement in _SHAPES:
        text = pattern.sub(replacement, text)
    return text
