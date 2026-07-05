"""Fernet at-rest encryption and the stable Plex client identifier.

Both derive from TASTERR_SECRET_KEY: the Fernet key via SHA-256 → urlsafe
base64, the client identifier via a domain-separated one-way hash into UUIDv5.
Stable across restarts; no key material is recoverable from either output.
Rotating the key orphans encrypted Plex tokens and re-registers the Plex
device — both simply force a fresh login.
"""

import base64
import hashlib
import uuid

from cryptography.fernet import Fernet


def _fernet(secret_key: str) -> Fernet:
    digest = hashlib.sha256(secret_key.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_token(secret_key: str, token: str) -> str:
    return _fernet(secret_key).encrypt(token.encode()).decode()


def decrypt_token(secret_key: str, ciphertext: str) -> str:
    return _fernet(secret_key).decrypt(ciphertext.encode()).decode()


def plex_client_identifier(secret_key: str) -> str:
    digest = hashlib.sha256(b"tasterr:plex-client-identifier:" + secret_key.encode()).hexdigest()
    return str(uuid.uuid5(uuid.NAMESPACE_URL, digest))
