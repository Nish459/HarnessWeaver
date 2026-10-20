# __app_name__

A support-ticket pipeline: clean the ticket, then classify and summarize it in parallel, then draft a reply that a reviewer checks. HarnessWeaver runs the graph and governs every model call.

- `harness.yaml` extends `profile://workflow` and declares the graph under `tasks.triage.runner`: steps, what each `needs`, and the reply step's `evaluator`. Steps that are ready together run in parallel; there is no planning (the graph is fixed).
- `app/steps.py` holds the handlers. `review` accepts a draft or sends feedback; the reply is rewritten up to `max_rounds` times, and a person takes over (`on_reject: escalate`) if it is never accepted.
- `harness.offline.yaml` swaps the model for a scripted one whose first draft misses the category, so the review loop shows offline.

```bash
harnessweaver spec validate --env offline     # check the spec
harnessweaver test                            # run the tests offline
harnessweaver eval run --env offline          # grade evals/golden.yaml
HARNESSWEAVER_ENV=offline python -m app.main  # triage one ticket
```

Finished steps are checkpointed: after an approval, only the interrupted step runs again.
