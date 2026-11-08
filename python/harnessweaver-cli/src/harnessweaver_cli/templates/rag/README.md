# __app_name__

Answers from a knowledge base, with sources, governed by HarnessWeaver.

- `harness.yaml` extends `profile://rag`: PII in the question is redacted, injection attempts are blocked, retrieved passages that carry injections are dropped, and secrets never leave in an answer.
- `routing.topic` routes each question with a lexical stage; `context.kb` retrieves passages whose ACLs the asker passes; `grounded.citations` makes every answer sentence cite a retrieved passage, and repairs an answer that doesn't.
- `app/flow.py` is the whole flow: `decide`, `fetch`, `generate`. The session governs each step.
- `harness.offline.yaml` swaps the model for a scripted one, so everything runs with no network.

```bash
uv sync                                              # install the project and its tools
uv run harnessweaver spec validate --env offline     # check the spec
uv run harnessweaver test                            # run the tests offline
uv run harnessweaver eval run --env offline          # grade evals/golden.yaml
HARNESSWEAVER_ENV=offline uv run python -m app.main  # answer one question
```

Add passages to `data/kb.yaml`, or replace the `memory` provider with a vector store plugin; the ACL re-check and the citation guard stay the same.
