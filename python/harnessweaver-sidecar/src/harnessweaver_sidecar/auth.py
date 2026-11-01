"""Bearer-token auth for every route except ``/v1/health`` (RULES S6)."""

import hmac
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

__all__ = ["authorized", "check_token"]

_BEARER = HTTPBearer(auto_error=False, description="The token harnessd was started with (S6).")


async def check_token(request: Request) -> None:
    """Refuse a request without the server's token. It reads headers only, never the body.

    The comparison takes the same time however much of the token matches, so it
    can't be guessed a character at a time.

    Raises:
        HTTPException: 401, with ``WWW-Authenticate: Bearer``.
    """
    credentials = await _BEARER(request)
    expected: str = request.app.state.token
    given = credentials.credentials if credentials is not None else ""
    if not hmac.compare_digest(given.encode("utf-8"), expected.encode("utf-8")):
        raise HTTPException(
            status_code=401,
            detail="a valid bearer token is required",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def authorized(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_BEARER)],
) -> None:
    """The route-level check: a second layer behind the app's gate, and what puts the
    bearer scheme in the OpenAPI document.

    Raises:
        HTTPException: 401, with ``WWW-Authenticate: Bearer``.
    """
    await check_token(request)
