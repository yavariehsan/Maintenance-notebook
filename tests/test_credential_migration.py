"""Credential encryption migration: operation + endpoint (P0.1).

Per-record legacy -> pbkdf2v1 migration with dry-run, backup-confirm gate,
idempotent skips, failure preservation, and resume. All persistence is
mocked (repo layer); only synthetic secrets are used.
"""

import base64
import hashlib
from unittest.mock import AsyncMock, patch

import pytest

MASTER = "migration-test-master"
LEGACY_WRONG_MASTER = "other-master"


def _legacy_token(plaintext: str, master: str = MASTER) -> str:
    from cryptography.fernet import Fernet

    derived = hashlib.sha256(master.encode("utf-8")).digest()
    fernet = Fernet(base64.urlsafe_b64encode(derived))
    return fernet.encrypt(plaintext.encode("utf-8")).decode("utf-8")


def _row(record_id: str, api_key):
    return {"id": record_id, "api_key": api_key}


def _op_kwargs(**overrides):
    params = {"dry_run": False, "require_backup_confirm": True}
    params.update(overrides)
    return params


class TestMigrateOperation:
    pytestmark = pytest.mark.asyncio

    @pytest.fixture(autouse=True)
    def master_key(self, monkeypatch):
        import open_notebook.utils.encryption as enc

        monkeypatch.setenv("OPEN_NOTEBOOK_ENCRYPTION_KEY", MASTER)
        monkeypatch.setattr(enc, "_ENCRYPTION_KEY", None)
        return MASTER

    async def _run(self, rows, **kwargs):
        from api import credentials_service as svc

        with (
            patch(
                "open_notebook.database.repository.repo_query",
                new=AsyncMock(return_value=[dict(r) for r in rows]),
            ),
            patch(
                "open_notebook.database.repository.repo_update",
                new=AsyncMock(return_value=[]),
            ) as mock_update,
        ):
            result = await svc.migrate_credential_encryption(
                **_op_kwargs(**kwargs)
            )
        return result, mock_update

    async def test_legacy_row_migrated(self):
        from open_notebook.utils import encryption as enc

        result, mock_update = await self._run(
            [_row("credential:a", _legacy_token("sk-a"))]
        )
        assert result["total"] == 1
        assert result["migrated"] == 1
        assert result["failed"] == 0
        assert mock_update.await_count == 1
        new_value = mock_update.await_args.args[2]["api_key"]
        assert new_value.startswith("pbkdf2v2:")
        assert new_value.split(":")[1] == "default"
        assert enc.decrypt_value(new_value) == "sk-a"

    async def test_already_new_skipped_byte_identical(self):
        from open_notebook.utils import encryption as enc

        token = enc.encrypt_pbkdf2v2_value("sk-a", MASTER, "default")
        result, mock_update = await self._run([_row("credential:a", token)])
        assert result["skipped"] == 1
        assert result["migrated"] == 0
        mock_update.assert_not_awaited()
        assert result["records"][0]["status"] == "skipped"

    async def test_idempotent_rerun_changes_nothing(self):
        from open_notebook.utils import encryption as enc

        token = enc.encrypt_pbkdf2v2_value("sk-a", MASTER, "default")
        first, _ = await self._run([_row("credential:a", token)])
        second, mock_update = await self._run([_row("credential:a", token)])
        assert first["records"][0]["status"] == "skipped"
        assert second["records"][0]["status"] == "skipped"
        mock_update.assert_not_awaited()

    async def test_dry_run_writes_nothing(self):
        result, mock_update = await self._run(
            [_row("credential:a", _legacy_token("sk-a"))],
            dry_run=True,
            require_backup_confirm=False,
        )
        assert result["dry_run"] is True
        assert result["migrated"] == 1
        mock_update.assert_not_awaited()

    async def test_backup_gate_refused(self):
        from api import credentials_service as svc

        with pytest.raises(ValueError, match="[Bb]ackup"):
            await svc.migrate_credential_encryption(
                dry_run=False, require_backup_confirm=False
            )

    async def test_decrypt_failure_preserves_original(self):
        bad = _legacy_token("sk-a", LEGACY_WRONG_MASTER)
        result, mock_update = await self._run([_row("credential:a", bad)])
        assert result["failed"] == 1
        assert result["migrated"] == 0
        mock_update.assert_not_awaited()
        assert result["records"][0]["status"] == "failed"

    async def test_unknown_version_preserved_and_failed(self):
        result, mock_update = await self._run(
            [_row("credential:a", "pbkdf2v9:600000:c2FsdA==:dG9rZW4=")]
        )
        assert result["failed"] == 1
        mock_update.assert_not_awaited()

    async def test_empty_api_key_skipped(self):
        result, mock_update = await self._run([_row("credential:a", None)])
        assert result["skipped"] == 1
        mock_update.assert_not_awaited()

    async def test_partial_migration_and_resume(self):

        good1 = _row("credential:1", _legacy_token("sk-1"))
        bad = _row(
            "credential:2", _legacy_token("sk-2", LEGACY_WRONG_MASTER)
        )
        good2 = _row("credential:3", _legacy_token("sk-3"))
        result, mock_update = await self._run([good1, bad, good2])
        assert result["migrated"] == 2
        assert result["failed"] == 1
        assert mock_update.await_count == 2

        migrated_ids = {
            call.args[1] for call in mock_update.await_args_list
        }
        assert migrated_ids == {"credential:1", "credential:3"}

        # Resume: already-migrated rows are skipped, the failure stays failed.
        from api import credentials_service as svc

        new_values = {
            call.args[1]: call.args[2]["api_key"]
            for call in mock_update.await_args_list
        }
        resumed_rows = [
            _row("credential:1", new_values["credential:1"]),
            _row("credential:2", bad["api_key"]),
            _row("credential:3", new_values["credential:3"]),
        ]
        with (
            patch(
                "open_notebook.database.repository.repo_query",
                new=AsyncMock(return_value=resumed_rows),
            ),
            patch(
                "open_notebook.database.repository.repo_update",
                new=AsyncMock(return_value=[]),
            ) as mock_update2,
        ):
            resumed = await svc.migrate_credential_encryption(
                **_op_kwargs()
            )
        assert resumed["migrated"] == 0
        assert resumed["skipped"] == 2
        assert resumed["failed"] == 1
        mock_update2.assert_not_awaited()
        for record in resumed["records"]:
            if record["status"] == "skipped":
                assert "error" not in record

    async def test_database_error_propagates_not_recorded(self):
        from api import credentials_service as svc

        with (
            patch(
                "open_notebook.database.repository.repo_query",
                new=AsyncMock(side_effect=RuntimeError("connection refused")),
            ),
            patch(
                "open_notebook.database.repository.repo_update",
                new=AsyncMock(return_value=[]),
            ),
        ):
            with pytest.raises(RuntimeError):
                await svc.migrate_credential_encryption(**_op_kwargs())

    async def test_no_secret_material_in_result(self):
        result, _ = await self._run(
            [_row("credential:a", _legacy_token("sk-super-secret"))],
            dry_run=True,
        )
        blob = repr(result)
        assert "sk-super-secret" not in blob
        assert MASTER not in blob


class TestMigrateEndpoint:
    pytestmark = pytest.mark.asyncio

    async def _call(self, monkeypatch, body, migrate_result=None):
        from api.routers import credentials as router

        monkeypatch.setenv("OPEN_NOTEBOOK_PASSWORD", "pw")
        with patch.object(
            router, "svc_migrate_encryption",
            new=AsyncMock(return_value=migrate_result or {
                "total": 0, "migrated": 0, "skipped": 0, "failed": 0,
                "dry_run": False, "target_key_id": "default", "records": [],
            }),
        ):
            return await router.migrate_credential_encryption(body)

    async def test_auth_disabled_refuses(self, monkeypatch):
        from fastapi import HTTPException

        from api.models import MigrateEncryptionRequest
        from api.routers import credentials as router

        monkeypatch.delenv("OPEN_NOTEBOOK_PASSWORD", raising=False)
        monkeypatch.delenv("OPEN_NOTEBOOK_PASSWORD_FILE", raising=False)
        with pytest.raises(HTTPException) as exc_info:
            await router.migrate_credential_encryption(
                MigrateEncryptionRequest(
                    dry_run=False, require_backup_confirm=True
                )
            )
        assert exc_info.value.status_code == 403

    async def test_backup_gate_maps_to_client_error(self, monkeypatch):
        from fastapi import HTTPException

        from api.models import MigrateEncryptionRequest
        from api.routers import credentials as router

        monkeypatch.setenv("OPEN_NOTEBOOK_PASSWORD", "pw")
        with pytest.raises(HTTPException) as exc_info:
            await router.migrate_credential_encryption(
                MigrateEncryptionRequest(
                    dry_run=False, require_backup_confirm=False
                )
            )
        assert exc_info.value.status_code == 400

    async def test_dry_run_passthrough_no_secrets(self, monkeypatch):
        from api.models import MigrateEncryptionRequest

        body = MigrateEncryptionRequest(
            dry_run=True, require_backup_confirm=False
        )
        result = await self._call(monkeypatch, body, {
            "total": 1, "migrated": 1, "skipped": 0, "failed": 0,
            "dry_run": True, "target_key_id": "default",
            "records": [{"id": "credential:a", "status": "migrated"}],
        })
        assert result["dry_run"] is True
        assert "sk-super-secret" not in repr(result)


class TestRotationMigration:
    pytestmark = pytest.mark.asyncio

    @pytest.fixture(autouse=True)
    def rotation_keys(self, monkeypatch):
        import json

        import open_notebook.utils.encryption as enc

        monkeypatch.setenv("OPEN_NOTEBOOK_ENCRYPTION_KEY", "new-active")
        monkeypatch.setenv("OPEN_NOTEBOOK_ENCRYPTION_KEY_ID", "2026q4")
        monkeypatch.setenv(
            "OPEN_NOTEBOOK_ENCRYPTION_PREVIOUS_KEYS",
            json.dumps({"2024": "old-secret"}),
        )
        monkeypatch.delenv("OPEN_NOTEBOOK_PASSWORD_FILE", raising=False)
        monkeypatch.setattr(enc, "_ENCRYPTION_KEY", None)

    async def _run(self, rows, **kwargs):
        from api import credentials_service as svc

        params = {"dry_run": False, "require_backup_confirm": True}
        params.update(kwargs)
        with (
            patch(
                "open_notebook.database.repository.repo_query",
                new=AsyncMock(return_value=[dict(r) for r in rows]),
            ),
            patch(
                "open_notebook.database.repository.repo_update",
                new=AsyncMock(return_value=[]),
            ) as mock_update,
        ):
            result = await svc.migrate_credential_encryption(**params)
        return result, mock_update

    async def test_old_key_row_migrated_to_active(self):
        from open_notebook.utils import encryption as enc

        old_token = enc.encrypt_pbkdf2v2_value("sk-old", "old-secret", "2024")
        result, mock_update = await self._run([_row("credential:a", old_token)])
        assert result["migrated"] == 1
        assert result["target_key_id"] == "2026q4"
        new_value = mock_update.await_args.args[2]["api_key"]
        assert new_value.split(":")[1] == "2026q4"
        assert enc.decrypt_value(new_value) == "sk-old"

    async def test_v1_row_migrated_to_active(self):
        from open_notebook.utils import encryption as enc

        v1_token = enc.encrypt_pbkdf2_value("sk-v1", "old-secret")
        result, mock_update = await self._run([_row("credential:a", v1_token)])
        assert result["migrated"] == 1
        new_value = mock_update.await_args.args[2]["api_key"]
        assert new_value.startswith("pbkdf2v2:2026q4:")

    async def test_on_target_skipped_byte_identical(self):
        from open_notebook.utils import encryption as enc

        token = enc.encrypt_pbkdf2v2_value("sk-a", "new-active", "2026q4")
        result, mock_update = await self._run([_row("credential:a", token)])
        assert result["skipped"] == 1
        mock_update.assert_not_awaited()

    async def test_explicit_other_configured_target(self):
        from open_notebook.utils import encryption as enc

        token = enc.encrypt_pbkdf2v2_value("sk-a", "new-active", "2026q4")
        result, mock_update = await self._run(
            [_row("credential:a", token)], target_key_id="2024"
        )
        assert result["migrated"] == 1
        assert result["target_key_id"] == "2024"
        new_value = mock_update.await_args.args[2]["api_key"]
        assert new_value.split(":")[1] == "2024"

    async def test_unknown_target_rejected(self):
        from api import credentials_service as svc

        with pytest.raises(ValueError, match="[Uu]nknown target"):
            await svc.migrate_credential_encryption(
                dry_run=False, require_backup_confirm=True,
                target_key_id="nope",
            )

    async def test_retired_key_row_failed_and_preserved(self):
        from open_notebook.utils import encryption as enc

        token = enc.encrypt_pbkdf2v2_value("sk-x", "gone-secret", "gone")
        result, mock_update = await self._run([_row("credential:a", token)])
        assert result["failed"] == 1
        mock_update.assert_not_awaited()
        assert result["records"][0]["status"] == "failed"

    async def test_mixed_rotation_run(self):
        from open_notebook.utils import encryption as enc

        rows = [
            _row("credential:1",
                 enc.encrypt_pbkdf2v2_value("sk-1", "old-secret", "2024")),
            _row("credential:2",
                 enc.encrypt_pbkdf2v2_value("sk-2", "new-active", "2026q4")),
            _row("credential:3", _legacy_token("sk-3", "old-secret")),
        ]
        result, mock_update = await self._run(rows)
        assert result["migrated"] == 2
        assert result["skipped"] == 1
        assert result["failed"] == 0
        assert mock_update.await_count == 2

    async def test_rotation_dry_run_writes_nothing(self):
        from open_notebook.utils import encryption as enc

        rows = [_row("credential:1",
                     enc.encrypt_pbkdf2v2_value("sk-1", "old-secret", "2024"))]
        result, mock_update = await self._run(
            rows, dry_run=True, require_backup_confirm=False
        )
        assert result["dry_run"] is True
        assert result["migrated"] == 1
        mock_update.assert_not_awaited()

    async def test_endpoint_rejects_unknown_target(self, monkeypatch):
        from fastapi import HTTPException

        from api.models import MigrateEncryptionRequest
        from api.routers import credentials as router

        monkeypatch.setenv("OPEN_NOTEBOOK_PASSWORD", "pw")
        with pytest.raises(HTTPException) as exc_info:
            await router.migrate_credential_encryption(
                MigrateEncryptionRequest(
                    dry_run=False, require_backup_confirm=True,
                    target_key_id="nope",
                )
            )
        assert exc_info.value.status_code == 400
