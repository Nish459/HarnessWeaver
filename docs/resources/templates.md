# Templates

`harnessweaver init` starts a project from a template. Every template produces a project whose own tests pass offline (RULES T6): a `harness.yaml`, an offline overlay with a scripted model, the app's code, prompts, an eval set and tests.

```bash
uv run harnessweaver init ../ticket-triage                   # the extraction template
uv run harnessweaver init ../help-desk -t rag --name help-desk
```

`init` copies the template and puts the project name in it; there is no template language. It never overwrites a file unless you pass `--force`. Then, from the clone (until the packages are published):

```bash
uv run harnessweaver spec validate ../help-desk/harness.yaml -e offline
uv run harnessweaver test ../help-desk
uv run harnessweaver eval run ../help-desk/harness.yaml -e offline
```

Every template points at a LiteLLM gateway on `http://localhost:4000` with `LITELLM_API_KEY`; set those, map the aliases to models the gateway serves, and run without `HARNESSWEAVER_ENV=offline` to go live.

| Template | Profile | Style | What you get |
| --- | --- | --- | --- |
| [`extraction`](#extraction) (default) | `extraction` | Run (`direct`) | Typed extraction with schema validation, one repair, PII and secrets guards, a business rule, a golden set |
| [`rag`](#rag) | `rag` | Session | Routing, ACL-checked retrieval and answers whose citations the output guard checks |
| [`agent`](#agent) | `agent` | Run (`pydantic_ai.agent`) | A Pydantic AI agent with two governed tools, one approval-gated, a policy rule and a red-team set |
| [`workflow`](#workflow) | `workflow` | Run (`workflow`) | A step graph with a parallel stage and an evaluator-optimizer loop |
| [`chat`](#chat) | `chat` | Session, streamed | A chat turn with memory, a topic guard and a streamed answer moderated chunk by chunk |

## extraction

Typed extraction from support messages into a `TicketSummary` (category, priority, product, summary).

- `harness.yaml` extends `profile://extraction`: PII in the input is redacted, secrets in the output are blocked, and an invalid answer is repaired once before the run escalates. The `extract` task uses the `direct` runner with input and output models, a prompt, a budget, a business rule (`summary-length`) and an eval suite.
- `harness.offline.yaml` answers each golden case, so `eval run -e offline` passes.
- Files: `app/models.py`, `app/main.py` (runs the task once), `prompts/extract@1.md`, `evals/golden.yaml`, `tests/test_extract.py`.

The [Quickstart](../learn/quickstart.md) walks through it.

## rag

Answers from a knowledge base, with sources.

- `harness.yaml` extends `profile://rag`: PII in the question is redacted, injection attempts are blocked, retrieved passages that carry injections are dropped, and secrets never leave in an answer.
- `routing.topic` routes each question with a lexical stage; `context.kb` retrieves passages whose ACLs the asker passes; `grounded.citations` makes every answer sentence cite a retrieved passage, and repairs an answer that doesn't.
- `app/flow.py` is the whole flow (`decide`, `fetch`, `generate`), run as a session; `data/kb.yaml` holds the passages.

## agent

A support agent that looks up orders and issues refunds. A Pydantic AI agent runs the task; HarnessWeaver governs every model call and tool call it makes.

- `harness.yaml` extends `profile://agent`: injection attempts in the input are blocked, secrets in tool results are redacted, tool calls are capped, and every tool needs a manifest.
- `tools/` holds the manifests. `lookup_order` is a low-risk read; `refund_payment` moves money, so a refund over 50 USD waits for a `support-lead`, and a policy rule blocks any refund over 500 USD.
- The agent has no model of its own: the spec's `models` answer it, through your gateway.
- `evals/redteam.yaml`: injected instructions and over-the-limit refunds are blocked, and a large refund waits for a person.

Needs `harnessweaver-pydantic-ai`.

## workflow

A support-ticket pipeline: clean the ticket, then classify and summarize it in parallel, then draft a reply that a reviewer checks.

- `harness.yaml` declares the graph under `tasks.triage.runner`: steps, what each `needs`, and the reply step's `evaluator`. Steps that are ready together run in parallel; the graph is fixed, with no planning.
- `app/steps.py` holds the handlers. `review` accepts a draft or sends feedback; the reply is rewritten up to `max_rounds` times, and a person takes over (`on_reject: escalate`) if it is never accepted.
- The offline model's first draft misses the category, so the review loop shows offline.

## chat

A chat assistant whose answers stream to the user.

- `harness.yaml` extends `profile://chat`: PII in messages is redacted, and a streamed answer is cut the moment a chunk leaks a secret. A `topic.deny` guard keeps the assistant out of medical and legal questions.
- `app/chat.py` is one turn: the history from `s.memory` (kept per tenant and principal, for a day), the new message, and `generate(stream=True)`.
- `app/main.py` chats in the terminal: `submit` starts a turn and `stream` prints its chunks as they arrive.

## Plugin templates

A plugin can ship templates of its own (`hw.Plugin(templates={"rag": "templates/rag"})`), which `init` names as `<namespace>.<template>`:

```bash
uv run harnessweaver init ../acme-bot -t acme.rag
```

`harnessweaver plugin new <namespace>` scaffolds a plugin package from the built-in plugin template: a `pyproject.toml` with the entry point, the `hw.Plugin`, a sample guard (`<namespace>.banned_words`) and tests that run the conformance suite. See [Plugins](../advanced/plugins.md).
