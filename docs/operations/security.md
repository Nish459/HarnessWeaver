# Security

HarnessWeaver's job is to keep AI applications inside the lines their owners draw. This page lists the threats it is designed against and the controls that answer each, the invariants an operator can rely on, and how to harden a deployment. To report a vulnerability, see the [security policy](../project/security.md).

## Threats and controls

| Threat | Controls |
| --- | --- |
| Prompt injection through retrieved content or tool output | `untrusted` labels on context and tool results, `injection.heuristic` on input and context, the lethal-trifecta check, approvals for egress |
| A tool's definition swapped after review ("rug pull") | `definition_digest` pinning, checked at governor step 1 on every call |
| Data exfiltration | `egress` lists in manifests, the trifecta check, approval for risky tools, gateway allow-lists |
| PII leaking to logs or vendors | `pii.regex` redaction (or a stronger provider), `capture_content: false` locked by the baseline, the R9 conformance check |
| Privilege escalation through an LLM decision | Deterministic policy only (R3); judges and classifiers may only tighten |
| Cost runaway, denial of wallet | Per-run budgets and deadlines checked before every call; tenant budgets at the gateway; tool-call caps |
| Malicious generated code | `transport: code` with a sandbox such as `monty`; never `eval` or `exec` in the host (S4) |
| Supply-chain compromise | Locked dependencies, SHA-pinned CI actions, digest-pinned images (S5); plugin allow-lists (S8) |
| Sidecar exposure | Binds 127.0.0.1 by default; a bearer token on every route except health, compared in constant time (S6) |
| Apps switching controls off | Locks and bounds enforced when a spec loads (R1, R10); `require_level` by risk tier |

## Invariants you can rely on

These are the framework's promises, enforced in code and tests ([RULES.md](https://github.com/Wise-DreamerZ/HarnessWeaver/blob/main/RULES.md)):

| Rule | Promise |
| --- | --- |
| R1 | A locked path or baseline item can't be overridden, removed or reordered by any later layer; trying is a load error |
| R2 | Baseline middleware fails closed; declaring it open is a load error |
| R3 | Probabilistic components never grant: they may route or tighten a decision, never turn a deny or an approval into an allow |
| R4 | No silent gaps: unknown keys, providers and hook names fail loading, and a runner or adapter that can't reach a hook the baseline needs fails loading |
| R9 | Prompts, outputs, tool arguments and tool results never reach logs, spans or traces before redaction; content capture is off by default |
| R10 | A value outside its bound fails loading; nothing is clamped. Per-run overrides may only lower overridable fields |
| R13 | Every decision (route, guard, tool allowed or denied, budget hit, approval, middleware failure) is a traced event with its reason |
| R14 | Everything runs offline; live providers refuse to call out in test mode |
| S1 | Keys come from the environment or the gateway, never from spec files |
| S2 | No tool runs without a manifest; a digest mismatch blocks the call |
| S3 | Tool output, retrieved context and network content are untrusted; the trifecta check runs on every tool call |
| S6 | harnessd binds locally and needs a token |
| S8 | Plugins are inert until a spec uses them; the org can lock `plugins.allow` |

## Hardening a deployment

- **Lock the baseline.** At least `plugins.allow`, `observability.capture_content`, the PII and secrets guards, `tools.require_manifest` and `tools.approval_by_risk`. Bound budgets and deadlines.
- **Require levels by risk.** `require_level` with `customer_facing: L2` and `takes_actions: L3` (or stricter) keeps risky apps from shipping without tool governance and policy.
- **Gate egress.** Give every tool with network access an `egress` list; keep `tools.trifecta` at `require_approval`, or `block` where nobody should be asked.
- **Pin tools.** `harnessweaver tools pin`, and fail CI on `doctor` digest errors.
- **Treat injection checks as one layer.** `injection.heuristic` is cheap and easy to evade; rely on labels, the trifecta check, approvals and least-privilege tools as well, and add a model-based detector where the stakes need it.
- **Keep keys at the gateway.** Apps hold a gateway key, not provider keys.
- **Run code in a sandbox.** Only through `transport: code` with a sandbox provider.
- **Protect the sidecar.** Local binding, a per-environment token from a secret store, rotation.
- **Watch shadow guards.** Promote guards on eval evidence (R8), and review `eval report` for guards that would fire in production.
- **Keep recordings deliberate.** `state.record` stores content; enable it only where you can protect the store, or lock it off.
- **Review spec changes.** Post `harnessweaver spec diff` on every pull request; a removed guard or a new plugin is visible before it merges.
