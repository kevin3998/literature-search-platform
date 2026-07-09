from __future__ import annotations

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
