"""Focused UTF-8 password-auth tests (P1.6).

Middleware byte path: Persian/CJK passwords sent as UTF-8 wire bytes must
authenticate (correct -> 200, wrong -> 401). This path was fixed upstream by
#1344 and is locked here as characterization coverage.

_FILE path: a UTF-8 secret file holding a non-ASCII password must be read as
UTF-8 regardless of platform locale. `Path.read_text()` without an encoding
uses the locale preferred encoding (POSIX/ASCII on minimal Docker images,
cp1256 on Windows): CJK bytes raise, Persian bytes decode to the wrong string,
and the loader silently falls back — misconfigured auth instead of working
auth. These tests fail until the loader pins UTF-8.
"""

import locale

import pytest
from fastapi import Request
from starlette.responses import Response
from starlette.types import Receive, Scope, Send

from api.auth import PasswordAuthMiddleware
from open_notebook.utils.encryption import get_secret_from_env

PERSIAN_PASSWORD = "گذرواژه-محرمانه"
CJK_PASSWORD = "密码-テスト"
MIXED_PASSWORD = "pässwörd-گذرواژه-中文"


async def _allow_request(_: Request) -> Response:
    return Response(status_code=200)


async def _request_with_env_password(
    monkeypatch: pytest.MonkeyPatch, *, password: str, presented: bytes
) -> int:
    monkeypatch.setenv("OPEN_NOTEBOOK_PASSWORD", password)
    monkeypatch.delenv("OPEN_NOTEBOOK_PASSWORD_FILE", raising=False)
    scope: Scope = {
        "type": "http",
        "method": "GET",
        "path": "/protected",
        "headers": [(b"authorization", b"Bearer " + presented)],
    }
    middleware = PasswordAuthMiddleware(lambda *_: None)
    response = await middleware.dispatch(Request(scope), _allow_request)
    return response.status_code


def _write_secret_file(path, text: str) -> str:
    path.write_bytes(text.encode("utf-8"))
    return str(path)


def _force_ascii_locale(monkeypatch: pytest.MonkeyPatch) -> None:
    """Simulate POSIX/ASCII-locale runtimes deterministically on any host."""
    monkeypatch.setattr(
        locale, "getpreferredencoding", lambda *args, **kwargs: "ascii"
    )


class TestNonAsciiMiddlewareAuth:
    pytestmark = pytest.mark.asyncio

    async def test_persian_password_succeeds(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        status = await _request_with_env_password(
            monkeypatch,
            password=PERSIAN_PASSWORD,
            presented=PERSIAN_PASSWORD.encode("utf-8"),
        )
        assert status == 200

    async def test_persian_wrong_password_is_unauthorized(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        status = await _request_with_env_password(
            monkeypatch,
            password=PERSIAN_PASSWORD,
            presented="گذرواژه-اشتباه".encode("utf-8"),
        )
        assert status == 401

    async def test_cjk_password_succeeds(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        status = await _request_with_env_password(
            monkeypatch,
            password=CJK_PASSWORD,
            presented=CJK_PASSWORD.encode("utf-8"),
        )
        assert status == 200

    async def test_mixed_password_succeeds(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        status = await _request_with_env_password(
            monkeypatch,
            password=MIXED_PASSWORD,
            presented=MIXED_PASSWORD.encode("utf-8"),
        )
        assert status == 200


class TestSecretFileUtf8:
    def test_utf8_file_password_returned_exactly_under_ascii_locale(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        secret_file = _write_secret_file(tmp_path / "pw", MIXED_PASSWORD)
        monkeypatch.setenv("OPEN_NOTEBOOK_PASSWORD_FILE", secret_file)
        monkeypatch.delenv("OPEN_NOTEBOOK_PASSWORD", raising=False)
        _force_ascii_locale(monkeypatch)

        assert get_secret_from_env("OPEN_NOTEBOOK_PASSWORD") == MIXED_PASSWORD

    def test_ascii_file_password_still_works(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        secret_file = _write_secret_file(tmp_path / "pw", "secret")
        monkeypatch.setenv("OPEN_NOTEBOOK_PASSWORD_FILE", secret_file)
        monkeypatch.delenv("OPEN_NOTEBOOK_PASSWORD", raising=False)

        assert get_secret_from_env("OPEN_NOTEBOOK_PASSWORD") == "secret"

    @pytest.mark.asyncio
    async def test_file_configured_persian_password_rejects_wrong(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Guards fail-open: a misread _FILE must not silently disable auth."""
        secret_file = _write_secret_file(tmp_path / "pw", PERSIAN_PASSWORD)
        monkeypatch.setenv("OPEN_NOTEBOOK_PASSWORD_FILE", secret_file)
        monkeypatch.delenv("OPEN_NOTEBOOK_PASSWORD", raising=False)
        _force_ascii_locale(monkeypatch)

        scope: Scope = {
            "type": "http",
            "method": "GET",
            "path": "/protected",
            "headers": [
                (b"authorization", "Bearer wrong".encode("utf-8"))
            ],
        }
        middleware = PasswordAuthMiddleware(lambda *_: None)
        response = await middleware.dispatch(Request(scope), _allow_request)
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_file_configured_persian_password_accepts_correct(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        secret_file = _write_secret_file(tmp_path / "pw", PERSIAN_PASSWORD)
        monkeypatch.setenv("OPEN_NOTEBOOK_PASSWORD_FILE", secret_file)
        monkeypatch.delenv("OPEN_NOTEBOOK_PASSWORD", raising=False)
        _force_ascii_locale(monkeypatch)

        scope: Scope = {
            "type": "http",
            "method": "GET",
            "path": "/protected",
            "headers": [
                (b"authorization", b"Bearer " + PERSIAN_PASSWORD.encode("utf-8"))
            ],
        }
        middleware = PasswordAuthMiddleware(lambda *_: None)
        response = await middleware.dispatch(Request(scope), _allow_request)
        assert response.status_code == 200


async def _unused_app(_: Scope, __: Receive, ___: Send) -> None:
    raise AssertionError("unreachable")
