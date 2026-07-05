import pytest
from cryptography.fernet import InvalidToken

from tasterr.auth.crypto import decrypt_token, encrypt_token, plex_client_identifier

SECRET = "unit-test-secret-key"


def test_encrypt_decrypt_round_trip() -> None:
    ciphertext = encrypt_token(SECRET, "plex-token-123")

    assert ciphertext != "plex-token-123"
    assert "plex-token-123" not in ciphertext
    assert decrypt_token(SECRET, ciphertext) == "plex-token-123"


def test_wrong_key_cannot_decrypt() -> None:
    ciphertext = encrypt_token(SECRET, "plex-token-123")

    with pytest.raises(InvalidToken):
        decrypt_token("a-different-secret", ciphertext)


def test_client_identifier_is_stable_per_key() -> None:
    first = plex_client_identifier(SECRET)
    second = plex_client_identifier(SECRET)
    other = plex_client_identifier("a-different-secret")

    assert first == second
    assert first != other


def test_client_identifier_is_a_uuid_and_leaks_no_key_material() -> None:
    import uuid

    identifier = plex_client_identifier(SECRET)

    assert uuid.UUID(identifier).version == 5
    assert SECRET not in identifier
