# Learn

Start here: the concepts, the quickstart, and a tutorial that builds one app chapter by chapter.

## Where to start

| If you | Read |
| --- | --- |
| Have fifteen minutes and want to see it work | The [Quickstart](quickstart.md): a governed, traced and tested project from a template, offline |
| Want to learn it properly | The [Tutorial](../tutorial/index.md): one app, built chapter by chapter, every feature, tested code |
| Want the mental model first | [Concepts](../concepts/index.md), then [Lifecycle and hook points](../concepts/lifecycle.md) |
| Already have an app calling a model | [Govern an existing client](../how-to/wrap-a-client.md): three lines |
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
