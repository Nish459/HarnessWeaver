"""The harnessd HTTP application: one effective spec, served over ``/v1`` (ADR-0038)."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

import harnessweaver
from harnessweaver import Harness
from harnessweaver.core.errors import ErrorCode, ErrorInfo, HarnessError
from harnessweaver.core.ports import Guardrail
from harnessweaver_sidecar import __version__
from harnessweaver_sidecar.routes import router

__all__ = ["create_app", "openapi_document"]

STATUS: dict[ErrorCode, int] = {
    ErrorCode.SPEC_INVALID: 400,
    ErrorCode.EXPRESSION_ERROR: 400,
    ErrorCode.POLICY_DENIED: 403,
    ErrorCode.NOT_FOUND: 404,
    ErrorCode.VALIDATION_FAILED: 422,
    ErrorCode.BUDGET_EXCEEDED: 429,
    ErrorCode.PROVIDER_ERROR: 502,
    ErrorCode.TOOL_ERROR: 502,
    ErrorCode.DEADLINE_EXCEEDED: 504,
}
"""The HTTP status of a taxonomy error that reaches a route; anything else is a 500."""

_HTTP_CODES: dict[int, ErrorCode] = {
    401: ErrorCode.POLICY_DENIED,
    403: ErrorCode.POLICY_DENIED,
    404: ErrorCode.NOT_FOUND,
}


def _answer(info: ErrorInfo, status: int, headers: dict[str, str] | None = None) -> JSONResponse:
    """An error answer: the ``ErrorInfo`` as the body."""
    return JSONResponse(info.model_dump(mode="json"), status_code=status, headers=headers)


async def _harness_error(request: Request, exc: Exception) -> JSONResponse:
    """A taxonomy error that reached a route, with the status its code maps to."""
    assert isinstance(exc, HarnessError)
    return _answer(exc.to_info(), STATUS.get(exc.code, 500))


async def _invalid_request(request: Request, exc: Exception) -> JSONResponse:
    """A request body or parameter that doesn't match its model: 422."""
    # Locations and messages only: FastAPI's own answer echoes the input, which
    # may be raw content (R9).
    assert isinstance(exc, RequestValidationError)
    problems = [
        f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}" for error in exc.errors()
    ]
    info = ErrorInfo(
        code=ErrorCode.VALIDATION_FAILED,
        type="ValidationFailed",
        message="; ".join(problems),
        details={"problems": list[Any](problems)},
    )
    return _answer(info, 422)


async def _http_error(request: Request, exc: Exception) -> JSONResponse:
    """Starlette's own errors (401 from the auth check, 404 for unknown paths, 405)."""
    assert isinstance(exc, HTTPException)
    code = _HTTP_CODES.get(exc.status_code, ErrorCode.VALIDATION_FAILED)
    info = ErrorInfo(code=code, type="HTTPError", message=str(exc.detail))
    return _answer(info, exc.status_code, dict(exc.headers or {}))


def _app(**options: Any) -> FastAPI:
    """The routes, the health check and the error answers, with no harness bound."""
    app = FastAPI(
        title="harnessd",
        version=__version__,
        description="The HarnessWeaver sidecar: one harness.yaml, served to every language.",
        **options,
    )

    @app.get("/v1/health")
    async def health() -> dict[str, str]:  # pyright: ignore[reportUnusedFunction]
        """Liveness, and the versions served. The only route without a token (S6)."""
        return {"status": "ok", "harnessd": __version__, "harnessweaver": harnessweaver.__version__}

    app.include_router(router)
    app.add_exception_handler(HarnessError, _harness_error)
    app.add_exception_handler(RequestValidationError, _invalid_request)
    app.add_exception_handler(HTTPException, _http_error)
    return app


def create_app(harness: Harness, *, token: str) -> FastAPI:
    """Build harnessd for one harness.

    Args:
        harness: The harness every route uses, built from the served spec.
        token: The bearer token every route except ``/v1/health`` requires (S6).

    Raises:
        ValueError: For an empty token: harnessd never runs open.
    """
    if not token:
        raise ValueError("harnessd needs a bearer token (S6)")

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        yield
        await harness.aclose()

    app = _app(lifespan=lifespan)
    app.state.harness = harness
    app.state.token = token
    app.state.providers = dict[str, Guardrail]()
    return app


def openapi_document() -> dict[str, Any]:
    """The OpenAPI document of the ``/v1`` API, as checked in under ``contracts/openapi``.

    It doesn't depend on any spec: routes are the same for every harness.
    """
    return _app().openapi()
