import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

const source = (path: string): string => fileURLToPath(new URL(`../../typescript/packages/${path}`, import.meta.url));

// Tests run against the packages' sources, so no build is needed first. The sidecar
// tests start harnessd, which takes a few seconds.
export default defineConfig({
  resolve: { alias: { "@harnessweaver/core": source("core/src/index.ts"), "@harnessweaver/ai-sdk": source("ai-sdk/src/index.ts") } },
  test: { include: ["test/**/*.test.ts"], env: { HARNESSWEAVER_TEST_MODE: "1" }, hookTimeout: 60_000 },
});
