/** Runner for the `governor` suite: digests, rates, schemas, policy, steps 1-7 and step 9. */

import { describe, expect, it } from "vitest";
import { FakeClock } from "../src/clock.js";
import { canonicalJson, definitionDigest } from "../src/digests.js";
import { newEnvelope, withLabels } from "../src/envelope.js";
import { checkSchema, SchemaError, validate } from "../src/jsonschema.js";
import { CelLitePolicy } from "../src/policy.js";
import { Governor } from "../src/tools/governor.js";
import { limitKey } from "../src/tools/limits.js";
import { approvalRules, describeManifest, parseManifest, parseRate, type ToolDescription } from "../src/tools/manifests.js";
import { sanitize } from "../src/tools/sanitize.js";
import { RunTrace } from "../src/trace.js";
import { casesOf, type Case } from "./fixtures.js";

function toolOf(spec: Record<string, any>): ToolDescription {
  const { name, manifest = true, ...rest } = spec;
  if (manifest === false) return { info: { name, ...rest }, spec: { name }, manifest: null, digestOk: true };
  return describeManifest(parseManifest({ metadata: { name }, spec: rest }));
}

async function steps(c: Case) {
  const tool = toolOf(c.tool);
  const governor = new Governor({
    policy: new CelLitePolicy(c.policy ?? {}),
    tools: c.tools ?? {},
    approvalRules: approvalRules(tool.manifest ? [tool.manifest] : []),
    taskApprovals: c.task_approvals ?? {},
  });
  const clock = new FakeClock();
  const envelope = withLabels(
    newEnvelope({ tenant: c.tenant ?? "acme", principal: c.principal ?? { id: "alice", roles: ["support"] }, task: c.task ?? null, clock }),
    c.labels ?? {},
  );
  const run = { envelope, clock, trace: new RunTrace(clock) };
  const limit = tool.manifest?.spec.rate_limit;
  for (let i = 0; i < (c.previous_calls ?? 0); i++) {
    const wanted: [string, number, number][] = [];
    if (limit?.per_principal) wanted.push([limitKey(tool.info.name, "principal", envelope.principal.id), ...parseRate(limit.per_principal)]);
    if (limit?.per_tenant) wanted.push([limitKey(tool.info.name, "tenant", envelope.tenant), ...parseRate(limit.per_tenant)]);
    expect(governor.limiter.acquire(wanted, clock.now() / 1000)).toBeDefined();
  }
  const approval = c.approved ? { approval_id: "apr_1", decision: "approve" as const, approver: { id: "bob" } } : null;
  return governor.authorize(run, { id: "call_1", name: tool.info.name, arguments: c.args }, tool, approval);
}

describe("governor", () => {
  it.each(casesOf("governor"))("%s", async (_, c) => {
    const want = c.expect;
    if ("definition" in c) {
      const d = c.definition;
      if ("canonical" in want) expect(canonicalJson(d)).toBe(want.canonical);
      expect(definitionDigest(d.name, d.description, d.input_schema)).toBe(want.digest);
    } else if ("rate" in c) {
      if (want.error) expect(() => parseRate(c.rate)).toThrow(RangeError);
      else expect(parseRate(c.rate)).toEqual([want.count, want.seconds]);
    } else if ("schema" in c) {
      if (want.error) {
        expect(() => checkSchema(c.schema)).toThrow(SchemaError);
        return;
      }
      checkSchema(c.schema);
      const problems = validate(c.value, c.schema);
      expect(problems.length === 0, problems.join("; ")).toBe(want.valid);
      if (!want.valid) expect([...new Set(problems.map((p) => p.split(": ")[0]))].sort()).toEqual(want.locations);
    } else if ("rules" in c) {
      const decision = await new CelLitePolicy({ rules: c.rules, default_effect: c.default_effect }).decide(c.request);
      expect([decision.effect, decision.rule ?? null]).toEqual([want.effect, want.rule]);
    } else if ("tool" in c) {
      const verdict = await steps(c);
      expect([verdict.decision, verdict.step, verdict.code ?? null], verdict.reason).toEqual([want.decision, want.step, want.code]);
    } else {
      const limit = c.policy.max_bytes || c.max_output_bytes || 20_000;
      const [cleaned] = await sanitize({ call_id: "call_1", output: c.output }, c.policy, limit);
      expect([cleaned.output, cleaned.truncated, cleaned.untrusted]).toStrictEqual([want.output, want.truncated, want.untrusted]);
    }
  });
});
