from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass


DEFAULT_PIN_ITERATIONS = 180_000
PIN_HASH_ALGORITHM = "pbkdf2_sha256"


@dataclass(frozen=True)
class RoleConfig:
    name: str
    enabled: bool = False
    pin_hash: str = ""


def hash_pin(pin: str, salt: str = "", *, iterations: int = DEFAULT_PIN_ITERATIONS) -> str:
    pin = str(pin)
    if not pin:
        raise ValueError("PIN is required.")
    clean_salt = salt.strip() or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        pin.encode("utf-8"),
        clean_salt.encode("utf-8"),
        int(iterations),
    ).hex()
    return f"{PIN_HASH_ALGORITHM}${int(iterations)}${clean_salt}${digest}"


def verify_pin(pin: str, stored_hash: str) -> bool:
    try:
        algorithm, iterations_text, salt, expected_digest = stored_hash.split("$", 3)
        iterations = int(iterations_text)
    except ValueError:
        return False
    if algorithm != PIN_HASH_ALGORITHM or not salt or not expected_digest:
        return False
    actual = hash_pin(pin, salt, iterations=iterations).split("$", 3)[3]
    return hmac.compare_digest(actual, expected_digest)

