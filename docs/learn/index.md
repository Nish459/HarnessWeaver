# Learn

Start here: the concepts, the quickstart, and a tutorial that builds one app chapter by chapter.

## From zero to production

1. **See it work.** The [Quickstart](quickstart.md) creates a project from a template, runs, traces, tests and grades it offline, adds a guard in shadow mode, and calls a real model. It takes about ten minutes.
2. **Learn it.** The [Tutorial](../tutorial/index.md) builds a support desk in 19 chapters. Chapters 1 to 8 take one task from a plain model call to typed, repaired, budgeted and guarded output under an org baseline. Chapters 9 to 15 add your own steps, routing, retrieval, tools, policy, approvals and durable state. Chapters 16 to 19 cover observability, testing, evals and debugging.
3. **Ship it.** [Serve it from a web app](../how-to/web-app.md), then work through [Deployment](../deployment/index.md) and its production checklist, and [Security](../deployment/security.md).
4. **Run it across teams.** [Write an org baseline](../how-to/org-baseline.md) that every app inherits and none can weaken, extend HarnessWeaver with [plugins](../advanced/plugins.md) of your own, and serve the same spec to [TypeScript](../advanced/typescript.md) and, through the [harnessd sidecar](../advanced/sidecar.md), to any language.

When something doesn't work, [Troubleshooting](../how-to/troubleshooting.md) explains each load error, blocked run and failed run.

## Where to start

| If you | Read |
| --- | --- |
| Have ten minutes and want to see it work | The [Quickstart](quickstart.md): a governed, traced and tested project from a template, offline, then a real model |
| Want a spec for your own app now | The [Spec generator](spec-generator.md): pick what you need, and copy the `harness.yaml`, profile, overlay, tool manifest or eval suite it writes |
| Want to learn it properly | The [Tutorial](../tutorial/index.md): one app, built chapter by chapter, every feature, tested code |
| Want the mental model first | [Concepts](../concepts/index.md), then [Lifecycle and hook points](../concepts/lifecycle.md) |
| Already have an app calling a model | [Govern an existing client](../how-to/wrap-a-client.md): three lines |
| Are building an HTTP API | [Serve it from a web app](../how-to/web-app.md): load once, run each request as its caller, approvals and streaming |
| Are on the platform or security team | [Profiles and the org baseline](../tutorial/profiles.md), then [Write an org baseline](../how-to/org-baseline.md) and [Security](../deployment/security.md) |
| Aren't on Python | [TypeScript](../advanced/typescript.md), or any language through the [harnessd sidecar](../advanced/sidecar.md) |

## Concepts

Background that the tutorial assumes, and explains again as it goes:

- [Concepts](../concepts/index.md): who writes what, the layers, and the twelve concepts.
- [The spec](../concepts/spec.md): the documents, the YAML rules, the sections, and the files next to a spec.
- [Lifecycle and hook points](../concepts/lifecycle.md): the 13 hook points, a run end to end, event payloads, statuses and the trace.
- [The hook bus](../concepts/hook-bus.md): bands, the onion order, and how outcomes combine.
- [Outcomes and errors](../concepts/outcomes.md): what middleware can answer, how a run ends, and the error taxonomy.
- [Envelope, labels and budgets](../concepts/envelope.md): who a run acts for, what it has seen, and what it may still spend.
- [Integration styles](../concepts/integration-styles.md): Wrap, Session and Run.
- [Adoption levels](../concepts/adoption-levels.md): L0 to L4, and what each one needs.

## After the tutorial

- The [Advanced guide](../advanced/index.md) covers layering in depth, the tool governor, approvals in depth, TypeScript, the sidecar, and writing plugins.
- The [HarnessWeaver CLI](../cli.md) reference.
- [Deployment](../deployment/index.md) and [Recipes](../how-to/index.md).
