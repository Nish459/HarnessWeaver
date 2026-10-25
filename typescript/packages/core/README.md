# @harnessweaver/core

The TypeScript core of [HarnessWeaver](https://github.com/Wise-DreamerZ/HarnessWeaver), *the composable AI harness framework*. It loads the same `harness.yaml` as the Python core (layers, locks, bounds, org profiles, overlays) and runs the same hook bus, budgets, guards, cel-lite policy and rules, routing, tool governor, context governance, prompts and eval graders, held to the same language-neutral fixtures.

```bash
npm install @harnessweaver/core
npm install @harnessweaver/ai-sdk ai @ai-sdk/provider     # to govern Vercel AI SDK models
```

> Pre-release: the package isn't published yet; build it from the repository (`pnpm -C typescript install && pnpm -C typescript build`).

```ts
import { load } from "@harnessweaver/core";
import { wrapModel } from "@harnessweaver/ai-sdk";
import { generateText } from "ai";

const harness = load("harness.yaml");

const answer = await harness.session({ task: "support", principal: user.id, tenant: user.org }, async (s) => {
  const question = String(await s.guard("input", text));
  const route = await s.decide("intent", { text: question });
  const articles = await s.context("help").fetch(question);
  const { text: reply } = await generateText({ model: wrapModel(s, model, { alias: "fast" }), prompt: ask(question, articles) });
  return s.validate("output", reply);
});
```

Node 22 or later, ESM only. Runtime dependency: `yaml`.

Documentation: [TypeScript](https://github.com/Wise-DreamerZ/HarnessWeaver/blob/main/docs/tooling/typescript.md).
