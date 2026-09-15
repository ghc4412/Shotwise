from __future__ import annotations

import base64
import os

import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from server.services.publishing_crypto import (
    KEY_ENV,
    PublishingEncryptionKeyError,
    decrypt_secret,
    encrypt_secret,
)

pytestmark = pytest.mark.unit


def _key() -> str:
    return base64.urlsafe_b64encode(b"k" * 32).decode("ascii")


def test_encrypt_and_decrypt_round_trip(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(KEY_ENV, _key())

    token = encrypt_secret("refresh-token-秘密")

    assert token.startswith("v1.")
    assert "refresh-token" not in token
    assert decrypt_secret(token) == "refresh-token-秘密"


def test_encryption_uses_a_random_nonce(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(KEY_ENV, _key())

    first = encrypt_secret("same-secret")
    second = encrypt_secret("same-secret")

    assert first != second
    assert decrypt_secret(first) == decrypt_secret(second) == "same-secret"


def test_missing_or_invalid_key_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(KEY_ENV, raising=False)
    with pytest.raises(PublishingEncryptionKeyError, match="not configured"):
        encrypt_secret("secret")

    monkeypatch.setenv(KEY_ENV, "not-base64###")
    with pytest.raises(PublishingEncryptionKeyError, match="urlsafe-base64"):
        encrypt_secret("secret")

    monkeypatch.setenv(KEY_ENV, base64.urlsafe_b64encode(b"short").decode("ascii"))
    with pytest.raises(PublishingEncryptionKeyError, match="32 bytes"):
        encrypt_secret("secret")


def test_wrong_key_and_tampered_ciphertext_are_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(KEY_ENV, _key())
    token = encrypt_secret("secret")

    monkeypatch.setenv(KEY_ENV, base64.urlsafe_b64encode(b"z" * 32).decode("ascii"))
    with pytest.raises(PublishingEncryptionKeyError, match="invalid encrypted"):
        decrypt_secret(token)

    monkeypatch.setenv(KEY_ENV, _key())
    version, nonce, ciphertext = token.split(".")
    replacement = "A" if ciphertext[0] != "A" else "B"
    tampered = f"{version}.{nonce}.{replacement}{ciphertext[1:]}"
    with pytest.raises(PublishingEncryptionKeyError, match="invalid encrypted"):
        decrypt_secret(tampered)


def test_malformed_base64_and_invalid_utf8_are_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(KEY_ENV, _key())

    with pytest.raises(PublishingEncryptionKeyError, match="invalid encrypted"):
        decrypt_secret("v1.%%%.$$$")

    with pytest.raises(PublishingEncryptionKeyError, match="invalid encrypted"):
        decrypt_secret("v1.abc.def")

    nonce = os.urandom(12)
    ciphertext = AESGCM(b"k" * 32).encrypt(nonce, b"\xff", b"v1")

    def encoded(value: bytes) -> str:
        return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")

    invalid_utf8_token = f"v1.{encoded(nonce)}.{encoded(ciphertext)}"
    with pytest.raises(PublishingEncryptionKeyError, match="invalid encrypted"):
        decrypt_secret(invalid_utf8_token)


def test_unsupported_version_and_empty_secret_are_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(KEY_ENV, _key())

    with pytest.raises(ValueError, match="must not be empty"):
        encrypt_secret("")
    with pytest.raises(PublishingEncryptionKeyError, match="invalid encrypted"):
        decrypt_secret("v2.abc.def")
