"""L0 (Observe): govern the OpenAI client an app already has, in three lines.

    HARNESSWEAVER_ENV=offline uv run python examples/01_invoice_extraction/l0_instrument.py

The lines marked 1, 2 and 3 are all an existing app adds. The instrumented
client is used exactly like the original, but every call now goes through
input.before, model.before, model.after and output.before: the PII redaction,
secrets check, budget and traces from instrument.yaml apply.

Offline, the client talks to a stand-in for the gateway instead of LiteLLM.
"""

import asyncio
import json
import os
from pathlib import Path

import httpx2  # the HTTP library the OpenAI SDK uses; only the offline stand-in needs it
from invoices.models import Invoice
from invoices.samples import EXPECTED, INVOICE_TEXT
from openai import AsyncOpenAI

import harnessweaver as hw  # 1

SPEC = Path(__file__).resolve().parent / "instrument.yaml"
RECEIVED: list[str] = []  # what reached the stand-in gateway


def stand_in_gateway(request: httpx2.Request) -> httpx2.Response:
    """Answers like LiteLLM's Chat Completions route, including its cost header."""
    RECEIVED.append(json.loads(request.content)["messages"][-1]["content"])
    message = {"role": "assistant", "content": json.dumps(EXPECTED)}
    completion = {
        "id": "chatcmpl-offline",
        "object": "chat.completion",
        "created": 1_790_000_000,
        "model": "fast-chat",
        "choices": [{"index": 0, "message": message, "finish_reason": "stop", "logprobs": None}],
        "usage": {"prompt_tokens": 180, "completion_tokens": 120, "total_tokens": 300},
    }
    return httpx2.Response(200, json=completion, headers={"x-litellm-response-cost": "0.00029"})


def existing_client() -> AsyncOpenAI:
    """The client the app already has. The gateway owns retries, so the SDK doesn't (R5)."""
    if os.environ.get("HARNESSWEAVER_ENV") == "offline":
        transport = httpx2.MockTransport(stand_in_gateway)
        return AsyncOpenAI(
            api_key="sk-test-offline",
            base_url="http://gateway.test/v1",
            max_retries=0,
            http_client=httpx2.AsyncClient(transport=transport),
        )
    return AsyncOpenAI(
        base_url="http://localhost:4000", api_key=os.environ["LITELLM_API_KEY"], max_retries=0
    )


async def main() -> Invoice:
    harness = hw.load(SPEC)  # 2
    client = harness.instrument(existing_client(), tenant="acme")  # 3

    # Unchanged app code from here on.
    reply = await client.chat.completions.create(
        model="fast-chat",
        messages=[
            {"role": "system", "content": "Extract the invoice as JSON."},
            {"role": "user", "content": INVOICE_TEXT},
        ],
    )
    invoice = Invoice.model_validate_json(reply.choices[0].message.content or "")
    print(f"invoice: {invoice.invoice_number}, total {invoice.total:.2f} {invoice.currency}")
    for line in RECEIVED[-1].splitlines():
        if "Billed to" in line or "Call" in line:
            print(f"the gateway saw: {line.strip()}")
    return invoice


if __name__ == "__main__":
    asyncio.run(main())
