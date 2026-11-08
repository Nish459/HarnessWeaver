"""The support desk as a web service: one harness, loaded at start-up, serves every request.

Run it from the tutorial's ``support-desk/`` project, offline:
``HARNESSWEAVER_ENV=offline uv run fastapi dev app.py``.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Literal

from fastapi import Body, Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from helpdesk.models import Ticket

import harnessweaver as hw
from harnessweaver.errors import NotFound, PolicyDenied

# A stand-in for your authentication: a verified token says who is calling and which
# roles they hold. Never take a principal, or its roles, from what the client claims.
USERS = {
    "token-ann": hw.Principal(id="ann", roles=("support",)),
    "token-fiona": hw.Principal(id="fiona", roles=("finance",)),
}

# The HTTP status for each way a run can end. A run that waits for a person is
# accepted, not finished: 202, with the approval it is waiting for in the body.
HTTP_STATUS = {
    hw.RunStatus.COMPLETED: 200,
    hw.RunStatus.AWAITING_APPROVAL: 202,
    hw.RunStatus.ESCALATED: 202,
    hw.RunStatus.BLOCKED: 422,
    hw.RunStatus.FAILED: 502,
    hw.RunStatus.CANCELLED: 503,
}


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Load the harness once, at start-up, and close its state store at shut-down.

    A spec that doesn't load stops the service here, before it takes a request.
    """
    async with hw.load("harness.yaml") as harness:
        app.state.harness = harness
        yield


app = FastAPI(lifespan=lifespan)


def get_harness(request: Request) -> hw.Harness:
    """The harness the service loaded at start-up."""
    return request.app.state.harness


def get_user(authorization: Annotated[str, Header()]) -> hw.Principal:
    """Who is calling, from the token in their ``Authorization`` header.

    Raises:
        HTTPException: 401, for a token nobody holds.
    """
    user = USERS.get(authorization.removeprefix("Bearer "))
    if user is None:
        raise HTTPException(401, "unknown token")
    return user


Desk = Annotated[hw.Harness, Depends(get_harness)]
User = Annotated[hw.Principal, Depends(get_user)]
IdempotencyKey = Annotated[str | None, Header()]


def own_key(user: hw.Principal, key: str | None) -> str | None:
    """The client's ``Idempotency-Key``, made the caller's own.

    The harness keeps one run per tenant, task and key, so the same key sent by two
    callers must not hand one of them the other's result.
    """
    return f"{user.id}:{key}" if key is not None else None


def reply(result: hw.RunResult) -> JSONResponse:
    """The run's result as JSON, under the HTTP status for how it ended.

    The trace stays out: it is for your logs and telemetry, not for the caller.
    """
    body = result.model_dump(mode="json", exclude={"trace"})
    return JSONResponse(body, status_code=HTTP_STATUS[result.status])


@app.post("/triage")
async def triage(
    ticket: Ticket, desk: Desk, user: User, idempotency_key: IdempotencyKey = None
) -> JSONResponse:
    """Triage one ticket. A retry with the same ``Idempotency-Key`` gets the first result."""
    key = own_key(user, idempotency_key)
    return reply(await desk.run("triage", ticket, principal=user, idempotency_key=key))


@app.post("/orders")
async def orders(
    ticket: Ticket, desk: Desk, user: User, idempotency_key: IdempotencyKey = None
) -> JSONResponse:
    """Look an order up, or refund it. A large refund answers 202 and waits for finance."""
    key = own_key(user, idempotency_key)
    return reply(await desk.run("orders", ticket.text, principal=user, idempotency_key=key))


@app.post("/runs/{run_id}/approvals/{approval_id}")
async def answer(
    run_id: str,
    approval_id: str,
    decision: Annotated[Literal["approve", "reject"], Body(embed=True)],
    desk: Desk,
    user: User,
) -> JSONResponse:
    """Answer a pending approval as the caller: the run goes on, or ends blocked.

    Raises:
        HTTPException: 404 when there is no such pending approval (or another answer
            won it), 403 when the caller lacks the role it needs.
    """
    try:
        result = await desk.approve(run_id, approval_id, decision, approver=user)
    except NotFound as exc:
        raise HTTPException(404, str(exc)) from exc
    except PolicyDenied as exc:
        raise HTTPException(403, str(exc)) from exc
    return reply(result)
