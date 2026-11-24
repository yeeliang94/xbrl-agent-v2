"""argon2id password hashing. Ported from v1 `auth/passwords.py`."""
from __future__ import annotations

import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

_ph = PasswordHasher()

MIN_PASSWORD_LEN = 8

# Verified on the unknown-email path so it takes as long as a real check and
# timing does not reveal which emails have accounts.
_DUMMY_HASH = _ph.hash(secrets.token_urlsafe(32))

# No 0/O or 1/l/I, so a temporary password can be read aloud or copied by hand.
_TEMP_ALPHABET = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    """True if the password matches. Never raises."""
    if not password_hash:
        return False
    try:
        return _ph.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    try:
        return _ph.check_needs_rehash(password_hash)
    except InvalidHashError:
        return False


def dummy_verify(password: str) -> None:
    verify_password(_DUMMY_HASH, password)


def generate_temporary_password() -> str:
    """For example `k7Qm-2xP9-vRaT`: three groups of four (about 69 bits)."""
    return "-".join(
        "".join(secrets.choice(_TEMP_ALPHABET) for _ in range(4)) for _ in range(3)
    )
