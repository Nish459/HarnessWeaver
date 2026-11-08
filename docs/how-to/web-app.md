# Serve it from a web app

Most apps run their tasks behind an HTTP API. This recipe serves the [Tutorial](../tutorial/index.md)'s support desk with [FastAPI](https://fastapi.tiangolo.com): one harness, loaded at start-up, serves every request; each run acts for the user who sent the request; and a refund that needs a person answers `202` and is approved by a second request. Any ASGI framework works the same way.

## Add FastAPI

In your `support-desk/` project, as it stands at the end of the tutorial:

```console
$ uv add "fastapi[standard]"
```

## The app

Save this as `app.py`, next to `harness.yaml`:

```python title="app.py"
--8<-- "docs_src/web_app/app.py"
```

## Run it

```console
$ HARNESSWEAVER_ENV=offline uv run fastapi dev app.py
```

The offline overlay answers, as it does in the tutorial. From another terminal, triage a ticket, ask for a refund that needs finance, and approve it as someone from finance:

```bash
AUTH="Authorization: Bearer token-ann"
JSON="Content-Type: application/json"

curl -s localhost:8000/triage -H "$AUTH" -H "$JSON" -d '{"text": "I was charged twice for my Pro plan."}' \
  | jq -c '{status, output}'
# {"status":"completed","output":{"category":"billing","priority":2,"summary":"Charged twice for the Pro plan and wants one payment refunded."}}

curl -s localhost:8000/orders -H "$AUTH" -H "$JSON" -d '{"text": "Refund $250 on order A-1001."}' > refund.json
jq -c '{status, reason: .approval.reason}' refund.json
# {"status":"awaiting_approval","reason":"refunds over $100 need a person from finance"}

URL="localhost:8000/runs/$(jq -r .run_id refund.json)/approvals/$(jq -r .approval.approval_id refund.json)"
curl -s "$URL" -H "Authorization: Bearer token-fiona" -H "$JSON" -d '{"decision": "approve"}' \
  | jq -c '{status, output}'
# {"status":"completed","output":"Done: the refund is on its way to your card."}
```

Answering as Ann instead gets `403`, because approving needs the `finance` role, and answering again gets `404`, because the approval is no longer pending. The repository's tests run this app through each of these steps.

## What the app does

**It loads the harness once.** `hw.load` runs in the app's lifespan, so the spec is validated before the service takes a request, and a spec that doesn't load stops it from starting. `async with` keeps the harness open for background runs (`submit`, below) and closes its state store at shut-down. One harness serves every request: each run has its own envelope, budget and trace.

**Each run acts for the caller.** `principal=` is who the run acts for: policy rules read its roles, and approvals check them. Take it from your authentication, never from what the client sends; `USERS` stands in for that here. A multi-tenant service passes `tenant=` the same way, from the same verified identity, so memory, idempotency keys and telemetry are kept per tenant.

**Retries are safe.** A client that retries with the same `Idempotency-Key` header gets the first run's result instead of a second run. The harness keeps one run per tenant, task and key, so `own_key` prefixes the key with the caller's id: two users who send the same key never see each other's result.

**Every ending has an HTTP status.** Runs don't raise when a control stops them; they end with a status, and `reply` maps it:

| Run status | HTTP | What the body says |
| --- | --- | --- |
| `completed` | 200 | `output` |
| `awaiting_approval` | 202 | `approval`: why it waits, who may answer, and the tool call it is about |
| `escalated` | 202 | `error`: why it was handed to a person |
| `blocked` | 422 | `error`: `details.code` names the control, such as `policy_denied`, `guard_blocked` or `budget_exceeded` |
| `failed` | 502 | `error`: usually the model provider ([When a run fails](troubleshooting.md#when-a-run-fails)) |
| `cancelled` | 503 | The run was cancelled, for example because the service stopped |

Map them as your API's clients expect: these are choices, not rules. `reply` leaves the trace out of the body, and keeps everything else, approval details included; return less to callers who shouldn't see it. The harness raises only for mistakes in the code, such as an unknown task or a budget override out of bounds, and FastAPI answers those with `500`.

**Approvals are a request of their own.** The `orders` run suspended at the refund, with its state in the spec's SQLite store, so it waits for as long as `approvals.timeout` allows, through restarts. `harness.approve` checks the approver's role, claims the approval so that only one answer wins, and continues the run: the refund runs and the run completes. Requests can also reach people by webhook; see [Approvals](../tutorial/approvals.md#where-requests-go).

## Stream an answer

A task whose steps stream, such as the `chat` task of the `chat` [template](../resources/templates.md#chat), whose step calls `s.generate(..., stream=True)`, publishes each chunk as it arrives, once the `stream` guards have passed it. Start the run with `harness.submit` and forward its chunks as server-sent events. Add this to `app.py`:

```python
import json

from fastapi.responses import StreamingResponse


@app.post("/chat")
async def chat(ticket: Ticket, desk: Desk, user: User) -> StreamingResponse:
    """Stream the answer to the caller as server-sent events."""

    async def events() -> AsyncIterator[str]:
        # Follow the run straight after starting it, with nothing awaited in between,
        # so the stream is listening before the first chunk is published.
        run_id = await desk.submit("chat", ticket.text, principal=user)
        async for event in desk.stream(run_id):
            if event.type == "chunk" and event.chunk is not None:
                yield f"data: {json.dumps(event.chunk.delta)}\n\n"
        result = await desk.result(run_id)
        yield f"event: end\ndata: {json.dumps(result.status.value)}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream")
```

`submit` needs the open harness that the lifespan provides. The `end` event carries the run's status, so the client knows whether the answer it got is complete.

## In production

- Pick the environment with `HARNESSWEAVER_ENV=prod`, so `harness.prod.yaml` points the models at your gateway ([Models and environments](../tutorial/models.md#environments)).
- Enable the logs you want with `logger.enable("harnessweaver")`, and send traces to your OpenTelemetry collector ([Observability](../tutorial/observability.md)).
- Go through the [production checklist](../deployment/index.md#production-checklist).

Apps in other languages call the same spec through the [harnessd sidecar](../advanced/sidecar.md), which serves it over HTTP in much this way.
