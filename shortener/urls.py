"""URL validation and short-code generation."""

from __future__ import annotations

import re
import secrets
from urllib.parse import urlparse

ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
CODE_LENGTH = 7
RESERVED = {"api", "admin", "stats", "health", "docs", "redoc", "openapi.json"}
BLOCKED_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "::1"}
BLOCKED_SCHEMES = {"javascript", "data", "file", "ftp"}


class UrlRejected(ValueError):
    """The URL is not something we are willing to redirect to."""


def normalise(raw: str, *, allow_local: bool = False) -> str:
    """Validates and canonicalises. Rejects the schemes that enable XSS or SSRF."""
    if not raw or not raw.strip():
        raise UrlRejected("url must not be empty")
    candidate = raw.strip()
    if len(candidate) > 2048:
        raise UrlRejected("url is longer than 2048 characters")
    if "://" not in candidate:
        candidate = "https://" + candidate
    parsed = urlparse(candidate)
    if parsed.scheme.lower() in BLOCKED_SCHEMES:
        raise UrlRejected(f"scheme {parsed.scheme!r} is not allowed")
    if parsed.scheme.lower() not in {"http", "https"}:
        raise UrlRejected("only http and https URLs can be shortened")
    host = (parsed.hostname or "").lower()
    if not host:
        raise UrlRejected("url has no host")
    if not allow_local and (host in BLOCKED_HOSTS or host.endswith(".local")):
        raise UrlRejected("local addresses are not allowed")
    if not re.fullmatch(r"[a-z0-9.-]+|\[[0-9a-f:]+\]", host):
        raise UrlRejected(f"invalid host {host!r}")
    if "." not in host and not host.startswith("[") and not allow_local:
        raise UrlRejected("host must be a public domain name")
    path = parsed.path or "/"
    return parsed._replace(scheme=parsed.scheme.lower(), netloc=parsed.netloc.lower(), path=path, fragment="").geturl()


def generate_code(length: int = CODE_LENGTH) -> str:
    """secrets, not random: codes are public identifiers and must be unpredictable."""
    if length < 4:
        raise ValueError("codes shorter than 4 characters collide too easily")
    while True:
        code = "".join(secrets.choice(ALPHABET) for _ in range(length))
        if code.lower() not in RESERVED and not code.isdigit():
            return code


def is_valid_code(code: str) -> bool:
    return bool(re.fullmatch(r"[0-9A-Za-z]{4,16}", code)) and code.lower() not in RESERVED
