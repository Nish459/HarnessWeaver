# __app_name__

A chat assistant whose answers stream to the user, governed by HarnessWeaver.

- `harness.yaml` extends `profile://chat`: PII in messages is redacted, and a streamed answer is cut the moment a chunk leaks a secret. A `topic.deny` guard keeps the assistant out of medical and legal questions.
- `app/chat.py` is one turn: the history from `s.memory` (kept per tenant and principal, for a day), the new message, and `generate(stream=True)`.
- `app/main.py` chats in the terminal: `submit` starts a turn and `stream` prints its chunks as they arrive.
- `harness.offline.yaml` swaps the model for a scripted one that streams, so everything runs with no network.

```bash
harnessweaver spec validate --env offline     # check the spec
harnessweaver test                            # run the tests offline
harnessweaver eval run --env offline          # grade evals/golden.yaml
HARNESSWEAVER_ENV=offline python -m app.main  # chat in the terminal
```
