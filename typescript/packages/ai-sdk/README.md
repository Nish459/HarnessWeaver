# @harnessweaver/ai-sdk

Vercel AI SDK (v7) models governed by a [HarnessWeaver](https://github.com/Wise-DreamerZ/HarnessWeaver) session. Every call through a wrapped model checks the allowed aliases and the run's budget, fires `model.before` (whose redactions reach the model) and `model.after` (whose redactions reach your app), meters usage and cost, and, when streamed, fires `stream.chunk` for each text delta so stream guards can redact a chunk or cut the stream.

```bash
npm install @harnessweaver/core @harnessweaver/ai-sdk ai @ai-sdk/provider
```

```ts
import { wrapModel, harnessMiddleware } from "@harnessweaver/ai-sdk";
import { generateText, streamText, wrapLanguageModel } from "ai";

await harness.session({ principal: user.id }, async (s) => {
  const { text } = await generateText({ model: wrapModel(s, model, { alias: "fast" }), prompt });
  const stream = streamText({ model: wrapModel(s, model, { alias: "fast" }), prompt });
  // or compose with other AI SDK middleware:
  const composed = wrapLanguageModel({ model, middleware: [harnessMiddleware(s, { alias: "fast" })] });
});
```

`ai` and `@ai-sdk/provider` are peer dependencies. Documentation: [TypeScript](https://github.com/Wise-DreamerZ/HarnessWeaver/blob/main/docs/advanced/typescript.md#models).
