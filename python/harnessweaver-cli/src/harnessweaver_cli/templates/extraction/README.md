# __app_name__

Typed extraction from customer support messages, governed by HarnessWeaver.

- `harness.yaml` extends `profile://extraction`: PII in the input is redacted, secrets in the output are blocked, and an invalid answer is repaired once before the run escalates.
- `harness.offline.yaml` swaps the model for a scripted one, so everything runs with no network.

```bash
harnessweaver spec validate --env offline     # check the spec
harnessweaver doctor --env offline            # adoption level and what to do next
harnessweaver test                            # run the tests offline
harnessweaver eval run --env offline          # grade evals/golden.yaml; exits 1 on a regression
HARNESSWEAVER_ENV=offline python -m app.main  # run the task once
```

To call a real model, run LiteLLM Proxy at `base_url`, set `LITELLM_API_KEY`, and map the `fast` alias to a model in `harness.yaml`.
