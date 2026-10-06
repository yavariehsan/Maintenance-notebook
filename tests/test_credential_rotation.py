"""Multi-key encryption and key rotation (Batch A).

Envelope v2: ``pbkdf2v2:<key_id>:<iterations>:<salt_b64>:<fernet_token>``.
New writes always carry the active key id; reads dispatch exactly (no
cross-key guessing); identity-less legacy formats fall back over configured
keys in deterministic order; unknown key ids fail closed. Synthetic secrets
only; the configured-key cache is reset per test.
"""

import base64
import hashlib
import json

import pytest

import open_notebook.utils.encryption as enc

NEW_MASTER = "new-active-secret"
OLD_MASTER = "old-secret-2024"
ACTIVE_ID = "2026q4"
OLD_ID = "2024"


@pytest.fixture()
def two_keys(monkeypatch):
    monkeypatch.setenv("OPEN_NOTEBOOK_ENCRYPTION_KEY", NEW_MASTER)
    monkeypatch.setenv("OPEN_NOTEBOOK_ENCRYPTION_KEY_ID", ACTIVE_ID)
    monkeypatch.setenv(
        "OPEN_NOTEBOOK_ENCRYPTION_PREVIOUS_KEYS",
        json.dumps({OLD_ID: OLD_MASTER}),
    )
    monkeypatch.setattr(enc, "_ENCRYPTION_KEY", None)
    return {"active": (ACTIVE_ID, NEW_MASTER), "old": (OLD_ID, OLD_MASTER)}


def _legacy_token(plaintext: str, master: str) -> str:
    from cryptography.fernet import Fernet

    derived = hashlib.sha256(master.encode("utf-8")).digest()
    fernet = Fernet(base64.urlsafe_b64encode(derived))
    return fernet.encrypt(plaintext.encode("utf-8")).decode("utf-8")


class TestKeyConfig:
    def test_active_and_previous_loaded(self, two_keys):
        keys = enc.get_configured_keys()
        assert list(keys) == [ACTIVE_ID, OLD_ID]
        assert keys[ACTIVE_ID] == NEW_MASTER
        assert enc.get_active_key_id() == ACTIVE_ID

    def test_default_active_id(self, monkeypatch):
        monkeypatch.setenv("OPEN_NOTEBOOK_ENCRYPTION_KEY", NEW_MASTER)
        monkeypatch.delenv("OPEN_NOTEBOOK_ENCRYPTION_KEY_ID", raising=False)
        monkeypatch.delenv(
            "OPEN_NOTEBOOK_ENCRYPTION_PREVIOUS_KEYS", raising=False
        )
        monkeypatch.setattr(enc, "_ENCRYPTION_KEY", None)
        assert enc.get_active_key_id() == "default"
        assert list(enc.get_configured_keys()) == ["default"]

    def test_duplicate_key_id_rejected(self, monkeypatch):
        monkeypatch.setenv("OPEN_NOTEBOOK_ENCRYPTION_KEY", NEW_MASTER)
        monkeypatch.setenv("OPEN_NOTEBOOK_ENCRYPTION_KEY_ID", "dup")
        monkeypatch.setenv(
            "OPEN_NOTEBOOK_ENCRYPTION_PREVIOUS_KEYS",
            json.dumps({"dup": "other-secret"}),
        )
        monkeypatch.setattr(enc, "_ENCRYPTION_KEY", None)
        with pytest.raises(ValueError):
            enc.get_configured_keys()

    def test_colon_in_key_id_rejected(self, monkeypatch):
        monkeypatch.setenv("OPEN_NOTEBOOK_ENCRYPTION_KEY", NEW_MASTER)
        monkeypatch.setenv("OPEN_NOTEBOOK_ENCRYPTION_KEY_ID", "bad:id")
        monkeypatch.delenv(
            "OPEN_NOTEBOOK_ENCRYPTION_PREVIOUS_KEYS", raising=False
        )
        monkeypatch.setattr(enc, "_ENCRYPTION_KEY", None)
        with pytest.raises(ValueError):
            enc.get_configured_keys()

    def test_malformed_previous_keys_rejected(self, monkeypatch):
        monkeypatch.setenv("OPEN_NOTEBOOK_ENCRYPTION_KEY", NEW_MASTER)
        monkeypatch.delenv("OPEN_NOTEBOOK_ENCRYPTION_KEY_ID", raising=False)
        monkeypatch.setenv(
            "OPEN_NOTEBOOK_ENCRYPTION_PREVIOUS_KEYS", "not-json{{{"
        )
        monkeypatch.setattr(enc, "_ENCRYPTION_KEY", None)
        with pytest.raises(ValueError):
            enc.get_configured_keys()

    def test_missing_active_secret_rejected(self, monkeypatch):
        monkeypatch.delenv("OPEN_NOTEBOOK_ENCRYPTION_KEY", raising=False)
        monkeypatch.delenv("OPEN_NOTEBOOK_ENCRYPTION_KEY_FILE", raising=False)
        monkeypatch.setattr(enc, "_ENCRYPTION_KEY", None)
        with pytest.raises(ValueError):
            enc.get_configured_keys()


class TestV2Envelope:
    def test_round_trip_active(self, two_keys):
        token = enc.encrypt_pbkdf2v2_value("sk-1", NEW_MASTER, ACTIVE_ID)
        assert enc.decrypt_pbkdf2v2_value(
            token, {ACTIVE_ID: NEW_MASTER, OLD_ID: OLD_MASTER}
        ) == "sk-1"

    def test_identity_embedded(self, two_keys):
        token = enc.encrypt_pbkdf2v2_value("sk-1", NEW_MASTER, ACTIVE_ID)
        parts = token.split(":")
        assert parts[0] == "pbkdf2v2"
        assert parts[1] == ACTIVE_ID
        assert parts[2] == "600000"
        assert len(base64.b64decode(parts[3])) == 16

    def test_old_ciphertext_reads_with_previous_key(self, two_keys):
        token = enc.encrypt_pbkdf2v2_value("sk-old", OLD_MASTER, OLD_ID)
        assert enc.decrypt_pbkdf2v2_value(
            token, {ACTIVE_ID: NEW_MASTER, OLD_ID: OLD_MASTER}
        ) == "sk-old"

    def test_unknown_key_id_fails_safely(self, two_keys):
        token = enc.encrypt_pbkdf2v2_value("sk-1", "retired-secret", "retired")
        with pytest.raises(ValueError):
            enc.decrypt_pbkdf2v2_value(token, {ACTIVE_ID: NEW_MASTER})

    def test_wrong_secret_fails_safely(self, two_keys):
        token = enc.encrypt_pbkdf2v2_value("sk-1", NEW_MASTER, ACTIVE_ID)
        with pytest.raises(ValueError):
            enc.decrypt_pbkdf2v2_value(
                token, {ACTIVE_ID: "wrong-secret", OLD_ID: OLD_MASTER}
            )

    @pytest.mark.parametrize(
        "bad",
        [
            "pbkdf2v2:only",
            "pbkdf2v2::600000:c2FsdA==:dG9rZW4=",
            "pbkdf2v2:k:notanint:c2FsdA==:dG9rZW4=",
            "pbkdf2v2:k:600000:!!!:dG9rZW4=",
            "pbkdf2v2:k:600000:c2FsdA==:bogus",
            "pbkdf2v2:",
        ],
    )
    def test_malformed_v2_fails_safely(self, two_keys, bad):
        with pytest.raises(ValueError):
            enc.decrypt_pbkdf2v2_value(bad, {ACTIVE_ID: NEW_MASTER})

    def test_salt_uniqueness(self, two_keys):
        first = enc.encrypt_pbkdf2v2_value("same", NEW_MASTER, ACTIVE_ID)
        second = enc.encrypt_pbkdf2v2_value("same", NEW_MASTER, ACTIVE_ID)
        assert first != second


class TestDispatchWithKeys:
    def test_new_writes_carry_active_id(self, two_keys):
        token = enc.encrypt_value("sk-1")
        assert token.split(":")[1] == ACTIVE_ID

    def test_dispatch_reads_v1_v2_legacy(self, two_keys):
        v1_old = enc.encrypt_pbkdf2_value("v1-old", OLD_MASTER)
        legacy = _legacy_token("legacy-old", OLD_MASTER)
        assert enc.decrypt_value(v1_old) == "v1-old"
        assert enc.decrypt_value(legacy) == "legacy-old"
        assert enc.decrypt_value("plaintext-key") == "plaintext-key"

    def test_retired_key_id_fails_with_clear_error(self, two_keys):
        token = enc.encrypt_pbkdf2v2_value("sk-1", "retired-secret", "retired")
        with pytest.raises(ValueError, match="[Kk]ey"):
            enc.decrypt_value(token)
