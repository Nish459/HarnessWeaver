import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

// Tests run against the core's sources, so no build is needed first.
export default defineConfig({
  resolve: { alias: { "@harnessweaver/core": fileURLToPath(new URL("../core/src/index.ts", import.meta.url)) } },
  test: { include: ["test/**/*.test.ts"], env: { HARNESSWEAVER_TEST_MODE: "1" } },
});
