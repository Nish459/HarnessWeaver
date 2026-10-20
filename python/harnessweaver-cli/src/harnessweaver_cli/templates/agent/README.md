# __app_name__

A support agent that looks up orders and issues refunds. A Pydantic AI agent runs the task; HarnessWeaver governs every model call and tool call it makes.

- `harness.yaml` extends `profile://agent`: injection attempts in the input are blocked, secrets in tool results are redacted, tool calls are capped, and every tool needs a manifest.
- `tools/` holds the manifests. `lookup_order` is a low-risk read; `refund_payment` moves money, so a refund over 50 USD waits for a `support-lead`, and `policy.rules` blocks any refund over 500 USD.
- `app/agent.py` is the agent and `app/tools.py` the tools. The agent has no model of its own: the spec's `models` answer it, through your gateway.
- `evals/redteam.yaml` is the red-team set: injected instructions and over-the-limit refunds are blocked, and a large refund waits for a person.

```bash
harnessweaver spec validate --env offline     # check the spec
harnessweaver test                            # run the tests offline
harnessweaver eval run --env offline          # grade the red-team set
harnessweaver policy test                     # once you write policy_tests.yaml
HARNESSWEAVER_ENV=offline python -m app.main  # ask the agent once
```

Approve a waiting refund with `harness.approve(run_id, approval_id, approver=...)`; the agent continues from where it stopped, and only the approved call runs. After changing a tool's description or schema, review it and run `harnessweaver tools pin`.
