import secrets
from typing import Optional

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

from open_notebook.utils.encryption import get_secret_from_env


class PasswordAuthMiddleware(BaseHTTPMiddleware):
    """
    Middleware to check password authentication for all API requests.
    Auth is fully disabled (no hardcoded default password) if
    OPEN_NOTEBOOK_PASSWORD is not set.
    Supports Docker secrets via OPEN_NOTEBOOK_PASSWORD_FILE.
    """

    def __init__(
        self, app: ASGIApp, excluded_paths: Optional[list[str]] = None
    ) -> None:
        super().__init__(app)
        self.password = get_secret_from_env("OPEN_NOTEBOOK_PASSWORD")
        self.excluded_paths: list[str] = excluded_paths or [
            "/",
            "/health",
            "/docs",
            "/openapi.json",
            "/redoc",
        ]

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        # Skip authentication if no password is set
        if not self.password:
            return await call_next(request)

        # Skip authentication for excluded paths
        if request.url.path in self.excluded_paths:
            return await call_next(request)

        # Skip authentication for CORS preflight requests (OPTIONS)
        if request.method == "OPTIONS":
            return await call_next(request)

        # Check authorization header
        auth_header = request.headers.get("Authorization")

        if not auth_header:
            return JSONResponse(
                status_code=401,
                content={"detail": "Missing authorization header"},
                headers={"WWW-Authenticate": "Bearer"},
            )

        # Expected format: "Bearer {password}"
        try:
            scheme, credentials = auth_header.split(" ", 1)
            if scheme.lower() != "bearer":
                raise ValueError("Invalid authentication scheme")
        except ValueError:
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid authorization header format"},
                headers={"WWW-Authenticate": "Bearer"},
            )

        # Check password (constant-time to avoid a timing side-channel).
        # Both sides are compared as UTF-8 bytes: Starlette surfaces the raw
        # header as latin-1 str, so re-encoding recovers the exact wire bytes,
        # which are decoded as UTF-8 (the only encoding clients can send a
        # non-ASCII password in). Undecodable input is a 401, never a 500.
        try:
            presented = credentials.encode("latin-1").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid password"},
                headers={"WWW-Authenticate": "Bearer"},
            )
        if not secrets.compare_digest(
            presented.encode("utf-8"), self.password.encode("utf-8")
        ):
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid password"},
                headers={"WWW-Authenticate": "Bearer"},
            )

        # Password is correct, proceed with the request
        response = await call_next(request)
        return response
