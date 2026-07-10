from __future__ import annotations

import builtins

import pytest


def test_password_hash_round_trip():
    from core.passwords import hash_password, verify_password

    password = "correct horse battery staple"

    stored_hash = hash_password(password)

    assert stored_hash != password
    assert verify_password(password, stored_hash)
    assert not verify_password("wrong password", stored_hash)


def test_password_minimum_length(monkeypatch):
    from core.passwords import validate_password_strength

    monkeypatch.setenv("PASSWORD_MIN_LENGTH", "8")

    with pytest.raises(ValueError, match="at least 8"):
        validate_password_strength("short")

    validate_password_strength("12345678")


def test_malformed_or_unknown_password_hash_returns_false():
    from core.passwords import verify_password

    for stored_hash in ["", "unknown$hash", "pbkdf2_sha256$bad", "pbkdf2_sha256$0$salt$digest"]:
        assert not verify_password("password123", stored_hash)


def test_pbkdf2_fallback_hash_round_trip(monkeypatch):
    from core.passwords import hash_password, verify_password

    real_import = builtins.__import__

    def import_without_bcrypt(name, *args, **kwargs):
        if name == "bcrypt":
            raise ImportError("bcrypt disabled for test")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", import_without_bcrypt)

    stored_hash = hash_password("password123")

    assert stored_hash.startswith("pbkdf2_sha256$")
    assert verify_password("password123", stored_hash)
    assert not verify_password("wrong-password", stored_hash)


def test_bcrypt_is_preferred_when_available():
    pytest.importorskip("bcrypt")

    from core.passwords import hash_password, verify_password

    stored_hash = hash_password("password123")

    assert stored_hash.startswith("bcrypt$")
    assert verify_password("password123", stored_hash)
