from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

from core.runtime_config import password_min_length

PBKDF2_ALGORITHM = "pbkdf2_sha256"
PBKDF2_ITERATIONS = 260_000


def validate_password_strength(password: str) -> None:
    minimum = password_min_length()
    if not password or len(password) < minimum:
        raise ValueError(f"password must be at least {minimum} characters")


def hash_password(password: str) -> str:
    validate_password_strength(password)
    try:
        import bcrypt  # type: ignore[import-not-found]
    except Exception:
        return _hash_pbkdf2(password)

    password_bytes = password.encode("utf-8")
    digest = bcrypt.hashpw(password_bytes, bcrypt.gensalt()).decode("utf-8")
    return f"bcrypt${digest}"


def verify_password(password: str, stored_hash: str) -> bool:
    if not password or not stored_hash:
        return False
    if stored_hash.startswith("bcrypt$"):
        return _verify_bcrypt(password, stored_hash)
    if stored_hash.startswith(f"{PBKDF2_ALGORITHM}$"):
        return _verify_pbkdf2(password, stored_hash)
    return False


def _hash_pbkdf2(password: str) -> str:
    salt = secrets.token_urlsafe(16)
    digest = _pbkdf2_digest(password, salt, PBKDF2_ITERATIONS)
    return f"{PBKDF2_ALGORITHM}${PBKDF2_ITERATIONS}${salt}${digest}"


def _verify_bcrypt(password: str, stored_hash: str) -> bool:
    try:
        import bcrypt  # type: ignore[import-not-found]

        bcrypt_hash = stored_hash.removeprefix("bcrypt$").encode("utf-8")
        return bool(bcrypt.checkpw(password.encode("utf-8"), bcrypt_hash))
    except Exception:
        return False


def _verify_pbkdf2(password: str, stored_hash: str) -> bool:
    try:
        algorithm, raw_iterations, salt, expected_digest = stored_hash.split("$", 3)
        iterations = int(raw_iterations)
    except ValueError:
        return False
    if algorithm != PBKDF2_ALGORITHM or iterations <= 0 or not salt or not expected_digest:
        return False
    actual_digest = _pbkdf2_digest(password, salt, iterations)
    return hmac.compare_digest(actual_digest, expected_digest)


def _pbkdf2_digest(password: str, salt: str, iterations: int) -> str:
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), iterations)
    return base64.urlsafe_b64encode(digest).decode("ascii")
