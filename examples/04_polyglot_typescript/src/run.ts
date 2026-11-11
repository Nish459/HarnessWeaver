/**
 * Example 04 as a script: Example 02's question, answered by this TypeScript app on
 * Example 02's own spec, and again by harnessd serving that spec when `HARNESSD_URL`
 * and `HARNESSD_TOKEN` are set.
 *
 *     pnpm -C typescript build
 *     HARNESSWEAVER_ENV=offline node examples/04_polyglot_typescript/dist/run.js
 */

import { fileURLToPath, pathToFileURL } from "node:url";
import type { LanguageModelV4 } from "@ai-sdk/provider";
import { load, SidecarClient, SpecError, type Harness, type RunResult } from "@harnessweaver/core";
import { scriptedModel, type Script } from "./offline.js";
import { answer } from "./support.js";

const at = (path: string): string => fileURLToPath(new URL(path, import.meta.url));

/** Example 02's spec, and the directory where `org://acme-baseline` lives. */
export const SPEC = at("../../02_support_rag/harness.yaml");
export const ORG = at("../../_org");

export const CUSTOMER = { id: "gina", roles: ["customer"] };
export const OUTAGE = "The dashboard is down, what do I do?";

/**
 * The AI SDK model for the spec's `models` section: the offline script, or, live, the
 * model the app brings.
 *
 * @throws SpecError when the spec isn't offline and no live model was given.
 */
export function modelFor(harness: Harness, live?: LanguageModelV4): LanguageModelV4 {
  const models = harness.spec.data.models as unknown as Script & { provider?: string };
  if (models.provider === "scripted") return scriptedModel(models);
  if (live !== undefined) return live;
  // No live provider package here; an app passes its own, for example
  // createOpenAI({ baseURL: "http://localhost:4000/v1" })("fast") for the LiteLLM gateway.
  throw new SpecError("set HARNESSWEAVER_ENV=offline, or pass the live AI SDK model for models.base_url");
}

/** harnessd at `HARNESSD_URL` with the token in `HARNESSD_TOKEN`, when it's set. */
function sidecarFromEnvironment(): SidecarClient | undefined {
  const url = process.env.HARNESSD_URL;
  return url === undefined ? undefined : new SidecarClient({ url, tokenEnv: "HARNESSD_TOKEN" });
}

/** Answer the outage question for Globex in TypeScript, then (when given) in harnessd. */
export async function main(print: (line: string) => void = console.log, sidecar = sidecarFromEnvironment()): Promise<void> {
  const harness = load(SPEC, { profileDirs: [ORG] });
  let ended: RunResult | undefined;
  const reply = await harness.session({ task: "support", principal: CUSTOMER, tenant: "globex", input: OUTAGE, onEnd: (r) => (ended = r) }, (s) =>
    answer(s, OUTAGE, modelFor(harness)),
  );
  print(`intent: ${reply.intent}`);
  print(`answer: ${reply.answer}`);
  print(`status: ${ended?.status ?? "?"}`);

  if (sidecar === undefined) return;
  // The same task, run by harnessd from the same spec: any language can do this over HTTP.
  const remote = await sidecar.startRun({ task: "support", input: OUTAGE, principal: CUSTOMER, tenant: "globex" });
  print(`harnessd: ${remote.status}, ${JSON.stringify(remote.output)}`);
}

if (process.argv[1] !== undefined && import.meta.url === pathToFileURL(process.argv[1]).href) await main();
