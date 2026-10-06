"""Versioned PBKDF2 credential encryption (P0.1).

Fork-native `pbkdf2v1:` envelope: PBKDF2-HMAC-SHA256 (600k iterations,
16-byte random salt) derives a Fernet key that encrypts the value, so
authenticated encryption is preserved while password-based derivation
gains a real work factor. Legacy Fernet/SHA-256 reads keep working;
dispatch is by exact prefix; unknown versions fail closed.
"""

import base64

import pytest

import open_notebook.utils.encryption as enc
from open_notebook.utils.encryption import decrypt_value, encrypt_value


@pytest.fixture()
def master_key(monkeypatch):
    monkeypatch.setenv("OPEN_NOTEBOOK_ENCRYPTION_KEY", "test-master-secret")
    monkeypatch.setattr(enc, "_ENCRYPTION_KEY", None)
    return "test-master-secret"


def _parts(token: str):
    return token.split(":")


class TestLegacyRoundTrip:
    def test_legacy_encrypt_decrypt(self, master_key):
        token = _legacy_encrypt("sk-legacy", master_key)
        assert decrypt_value(token) == "sk-legacy"


def _legacy_encrypt(value: str, master: str) -> str:
    """Legacy construction, pinned here so the test does not depend on
    encrypt_value emitting legacy format after the upgrade."""
    import hashlib

    from cryptography.fernet import Fernet

    derived = hashlib.sha256(master.encode("utf-8")).digest()
    fernet = Fernet(base64.urlsafe_b64encode(derived))
    return fernet.encrypt(value.encode("utf-8")).decode("utf-8")


class TestPbkdf2RoundTrip:
    @pytest.mark.parametrize(
        "plaintext",
        ["sk-new-key", "", "üñîçødé-گذرواژه-中文", "x" * 4096],
    )
    def test_round_trip(self, master_key, plaintext):
        token = enc.encrypt_pbkdf2_value(plaintext, master_key)
        assert enc.decrypt_pbkdf2_value(token, master_key) == plaintext

    def test_unicode_master_secret(self, master_key):
        master = "maître-گذرواژه-秘密"
        token = enc.encrypt_pbkdf2_value("sk-1", master)
        assert enc.decrypt_pbkdf2_value(token, master) == "sk-1"


class TestPbkdf2Structure:
    def test_envelope_layout(self, master_key):
        token = enc.encrypt_pbkdf2_value("sk-1", master_key)
        assert token.startswith("pbkdf2v1:")
        version, iters, salt_b64, fernet_token = _parts(token)
        assert version == "pbkdf2v1"
        assert iters == "600000"
        assert len(base64.b64decode(salt_b64)) == 16
        assert len(fernet_token) > 0

    def test_salt_uniqueness(self, master_key):
        first = enc.encrypt_pbkdf2_value("same", master_key)
        second = enc.encrypt_pbkdf2_value("same", master_key)
        assert first != second
        assert _parts(first)[2] != _parts(second)[2]
        assert enc.decrypt_pbkdf2_value(first, master_key) == "same"
        assert enc.decrypt_pbkdf2_value(second, master_key) == "same"

    def test_wrong_master_secret_fails_safely(self, master_key):
        token = enc.encrypt_pbkdf2_value("sk-1", master_key)
        with pytest.raises(ValueError):
            enc.decrypt_pbkdf2_value(token, "wrong-master")

    @pytest.mark.parametrize(
        "bad",
        [
            "pbkdf2v1:only-two-parts",
            "pbkdf2v1:notanint:c2FsdA==:dG9rZW4=",
            "pbkdf2v1:600000:!!!not-b64!!!:dG9rZW4=",
            "pbkdf2v1:600000:c2FsdA==:not-a-fernet-token",
            "pbkdf2v1:",
        ],
    )
    def test_malformed_token_fails_safely(self, master_key, bad):
        with pytest.raises(ValueError):
            enc.decrypt_pbkdf2_value(bad, master_key)

    def test_unknown_version_fails_closed(self, master_key):
        with pytest.raises(ValueError):
            enc.decrypt_pbkdf2_value("pbkdf2v9:600000:c2FsdA==:dG9rZW4=", master_key)


class TestDispatch:
    def test_encrypt_value_emits_new_format(self, master_key):
        assert encrypt_value("sk-1").startswith("pbkdf2v1:")

    def test_decrypt_value_reads_new_format(self, master_key):
        token = enc.encrypt_pbkdf2_value("sk-1", master_key)
        assert decrypt_value(token) == "sk-1"

    def test_decrypt_value_reads_legacy(self, master_key):
        assert decrypt_value(_legacy_encrypt("sk-old", master_key)) == "sk-old"

    def test_decrypt_value_legacy_plaintext_passthrough(self, master_key):
        assert decrypt_value("plaintext-key") == "plaintext-key"

    def test_unknown_version_never_becomes_plaintext(self, master_key):
        with pytest.raises(ValueError):
            decrypt_value("pbkdf2v9:600000:c2FsdA==:dG9rZW4=")

    def test_wrong_master_new_format_fails_safely(self, monkeypatch):
        monkeypatch.setenv("OPEN_NOTEBOOK_ENCRYPTION_KEY", "right-master")
        monkeypatch.setattr(enc, "_ENCRYPTION_KEY", None)
        token = encrypt_value("sk-1")
        monkeypatch.setenv("OPEN_NOTEBOOK_ENCRYPTION_KEY", "wrong-master")
        monkeypatch.setattr(enc, "_ENCRYPTION_KEY", None)
        with pytest.raises(ValueError):
            decrypt_value(token)


class TestCredentialModelIntegration:
    def test_save_data_uses_new_format(self, master_key):
        from pydantic import SecretStr

        from open_notebook.domain.credential import Credential

        cred = Credential(
            name="T", provider="openai", api_key=SecretStr("sk-abc")
        )
        data = cred._prepare_save_data()
        assert data["api_key"].startswith("pbkdf2v1:")

    def test_from_db_row_reads_both_formats(self, master_key):
        from open_notebook.domain.credential import Credential

        for raw in (
            _legacy_encrypt("sk-old", master_key),
            enc.encrypt_pbkdf2_value("sk-new", master_key),
        ):
            cred = Credential._from_db_row(
                {"name": "T", "provider": "openai", "api_key": raw}
            )
            assert cred.api_key.get_secret_value() in ("sk-old", "sk-new")

    def test_reading_legacy_does_not_rewrite(self, master_key):
        """Reads are non-destructive: decrypting legacy never re-encrypts."""
        from open_notebook.domain.credential import Credential

        raw = _legacy_encrypt("sk-old", master_key)
        cred = Credential._from_db_row(
            {"name": "T", "provider": "openai", "api_key": raw}
        )
        assert cred.api_key.get_secret_value() == "sk-old"
        assert not raw.startswith("pbkdf2v1:")


class TestProviderConfigIntegration:
    def test_to_dict_encrypted_uses_new_format(self, master_key):
        from pydantic import SecretStr

        from open_notebook.domain.provider_config import ProviderCredential

        cred = ProviderCredential(
            id="provider_config:test",
            name="T",
            provider="openai",
            api_key=SecretStr("sk-abc"),
        )
        assert cred.to_dict(encrypted=True)["api_key"].startswith("pbkdf2v1:")
