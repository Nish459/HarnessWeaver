/**
 * Example 04 through harnessd: the sidecar is started on Example 02's spec (offline, on
 * 127.0.0.1), and must answer as the TypeScript app does; the README's curl walkthrough
 * runs as written and prints what the README says (D3). Needs the Python workspace
 * installed (`uv sync --all-packages`).
 */

import { execFileSync, spawn, type ChildProcess } from "node:child_process";
import { readFileSync } from "node:fs";
import { createServer } from "node:net";
import { fileURLToPath } from "node:url";
import { FakeClock, load, SidecarClient } from "@harnessweaver/core";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { CUSTOMER, main, modelFor, ORG, OUTAGE, SPEC } from "../src/run.js";
import { answer } from "../src/support.js";

const at = (path: string): string => fileURLToPath(new URL(path, import.meta.url));
const REPO = at("../../..");
const TOKEN = "sk-test-example04";

let harnessd: ChildProcess;
let url: string;
let client: SidecarClient;

/** A port nothing listens on now. */
async function freePort(): Promise<number> {
  const server = createServer();
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const { port } = server.address() as { port: number };
  await new Promise((resolve) => server.close(resolve));
  return port;
}

beforeAll(async () => {
  url = `http://127.0.0.1:${await freePort()}`;
  const args = ["run", "--no-sync", "harnessd", SPEC, "-e", "offline", "--profile-dir", ORG, "--port", url.split(":").at(-1)!];
  // Its own process group, so stopping it stops uv's Python child as well.
  harnessd = spawn("uv", args, { cwd: REPO, env: { ...process.env, HARNESSD_TOKEN: TOKEN }, detached: true, stdio: "ignore" });
  // Test mode refuses the network unless the test hands the client a fetch (R14).
  client = new SidecarClient({ url, token: TOKEN, fetch: (input, init) => fetch(input, init) });
  for (let tries = 0; ; tries++) {
    try {
      await client.health();
      return;
    } catch (error) {
      if (tries > 100 || harnessd.exitCode !== null) throw new Error(`harnessd didn't start (is the Python workspace installed?): ${String(error)}`);
      await new Promise((resolve) => setTimeout(resolve, 200));
    }
  }
});

afterAll(async () => {
  if (harnessd?.pid === undefined || harnessd.exitCode !== null) return;
  const exited = new Promise((resolve) => harnessd.once("exit", resolve));
  process.kill(-harnessd.pid, "SIGTERM");
  await exited;
});

describe("Example 02's spec through harnessd", () => {
  it("answers each golden question as the TypeScript app does", async () => {
    const h = load(SPEC, { env: "offline", profileDirs: [ORG], clock: new FakeClock() });
    for (const [question, tenant] of [
      ["How long does a refund take?", "default"],
      [OUTAGE, "globex"],
      ["How do I export a report?", "default"],
    ] as const) {
      const local = await h.session({ task: "support", principal: CUSTOMER, tenant }, (s) => answer(s, question, modelFor(h)));
      const remote = await client.startRun({ task: "support", input: question, principal: CUSTOMER, tenant });
      expect(remote.status, question).toBe("completed");
      expect(remote.output, question).toEqual(local);
    }
  });

  it("is asked by the script after its own answer", async () => {
    const lines: string[] = [];
    process.env.HARNESSWEAVER_ENV = "offline";
    try {
      await main((line) => lines.push(line), client);
    } finally {
      delete process.env.HARNESSWEAVER_ENV;
    }
    expect(lines.at(-1)).toMatch(/^harnessd: completed, .*\[help-globex-sla\]/);
  });

  it("runs the README's curl walkthrough as written", () => {
    const readme = readFileSync(at("../README.md"), "utf8");
    const block = (marker: string): string => readme.match(new RegExp(`<!-- ${marker}[^>]*-->\\n\`\`\`\\w+\\n([\\s\\S]*?)\`\`\``))![1]!;
    const printed = execFileSync("bash", ["-euo", "pipefail", "-c", block("walkthrough:")], { env: { ...process.env, HARNESSD_URL: url, HARNESSD_TOKEN: TOKEN }, encoding: "utf8" });
    expect(printed).toBe(block("walkthrough output"));
  });
});
