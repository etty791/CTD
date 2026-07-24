"""Password hashing via stdlib scrypt with a per-user random salt."""

import hashlib
import hmac
import os
from dataclasses import dataclass

from server.persistence.persistence_config import (
    SALT_BYTES,
    SCRYPT_DKLEN,
    SCRYPT_N,
    SCRYPT_P,
    SCRYPT_R,
)


@dataclass(frozen=True)
class PasswordRecord:
    salt: bytes
    password_hash: bytes


def _derive(password: str, salt: bytes) -> bytes:
    return hashlib.scrypt(
        password.encode(),
        salt=salt,
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
        dklen=SCRYPT_DKLEN,
    )


def hash_password(password: str) -> PasswordRecord:
    """Hash a password with a fresh random salt."""
    salt = os.urandom(SALT_BYTES)
    return PasswordRecord(salt=salt, password_hash=_derive(password, salt))


def verify_password(password: str, salt: bytes, expected_hash: bytes) -> bool:
    """Constant-time check that ``password`` matches the stored salt+hash."""
    return hmac.compare_digest(_derive(password, salt), expected_hash)
