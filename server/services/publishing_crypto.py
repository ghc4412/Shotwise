"""Encrypted storage helpers for publishing OAuth credentials."""

from __future__ import annotations

import base64
import binascii
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

KEY_ENV = "PUBLISHING_ENCRYPTION_KEY"
KEY_VERSION = "v1"
_NONCE_BYTES = 12
_KEY_BYTES = 32


class PublishingEncryptionKeyError(RuntimeError):
    """Raised when a publishing credential cannot be encrypted or decrypted."""


def _decode_base64(value: str) -> bytes:
    """Decode strict URL-safe base64 without leaking the encoded value."""
    try:
        padded = value + "=" * (-len(value) % 4)
        return base64.b64decode(padded, altchars=b"-_", validate=True)
    except (ValueError, binascii.Error, TypeError) as exc:
        raise PublishingEncryptionKeyError("invalid encrypted publishing credential") from exc


def _encode_base64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _key() -> bytes:
    raw = os.environ.get(KEY_ENV, "").strip()
    if not raw:
        raise PublishingEncryptionKeyError(f"{KEY_ENV} is not configured")
    try:
        decoded = _decode_base64(raw)
    except PublishingEncryptionKeyError as exc:
        raise PublishingEncryptionKeyError(f"{KEY_ENV} must be urlsafe-base64 encoded") from exc
    if len(decoded) != _KEY_BYTES:
        raise PublishingEncryptionKeyError(f"{KEY_ENV} must decode to exactly {_KEY_BYTES} bytes")
    return decoded


def encrypt_secret(value: str) -> str:
    """Encrypt one OAuth secret using AES-256-GCM and return a versioned token."""
    if not value:
        raise ValueError("secret must not be empty")
    nonce = os.urandom(_NONCE_BYTES)
    ciphertext = AESGCM(_key()).encrypt(nonce, value.encode("utf-8"), KEY_VERSION.encode("ascii"))
    return f"{KEY_VERSION}.{_encode_base64(nonce)}.{_encode_base64(ciphertext)}"


def decrypt_secret(token: str) -> str:
    """Decrypt a versioned OAuth secret without exposing credential details in errors."""
    try:
        version, nonce_text, ciphertext_text = token.split(".", 2)
        if version != KEY_VERSION:
            raise ValueError("unsupported encryption key version")
        nonce = _decode_base64(nonce_text)
        ciphertext = _decode_base64(ciphertext_text)
        if len(nonce) != _NONCE_BYTES:
            raise ValueError("invalid nonce")
        plaintext = AESGCM(_key()).decrypt(nonce, ciphertext, version.encode("ascii"))
        return plaintext.decode("utf-8")
    except (InvalidTag, UnicodeDecodeError, ValueError, TypeError, AttributeError) as exc:
        raise PublishingEncryptionKeyError("invalid encrypted publishing credential") from exc


__all__ = ["KEY_ENV", "KEY_VERSION", "PublishingEncryptionKeyError", "decrypt_secret", "encrypt_secret"]
